"""Web terminal — a real PTY bridged over a WebSocket.

This is a genuine interactive shell (`journalctl -f`, `htop`, `vi` all work),
not a command-runner, because the things an operator actually needs to do on
a camera in the field are interactive. That also makes it the single most
dangerous endpoint in the app: it runs as whatever user caelum runs as, with
that user's full privileges. It is admin-only and can be switched off
entirely with `auth.terminal_enabled = false`.

Wire protocol:

* client → server: JSON text frames — ``{"type": "input", "data": "..."}`` and
  ``{"type": "resize", "cols": n, "rows": n}``.
* server → client: raw binary frames of PTY output. Binary rather than text
  because a UTF-8 sequence can straddle a read boundary; xterm.js decodes
  the byte stream itself and handles the split correctly.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from caelum.api.deps import get_settings
from caelum.api.security import WS_POLICY_VIOLATION, authorize_websocket, get_auth_config

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_CHUNK = 65536
_DEFAULT_SHELL = "/bin/bash"


def _spawn_shell(shell: str, cwd: str) -> tuple[int, int]:
    """Fork a shell attached to a new PTY; returns (pid, master_fd).

    Forking a process that has threads and an event loop is only safe because
    the child immediately `exec`s — no Python runs in the child beyond the
    handful of calls below.
    """
    pid, master_fd = pty.fork()
    if pid == 0:  # child
        try:
            os.chdir(cwd)
        except OSError:
            pass
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env.setdefault("HOME", os.path.expanduser("~"))
        os.execvpe(shell, [shell, "-i"], env)
        os._exit(127)  # only reached if exec failed
    return pid, master_fd


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    with contextlib.suppress(OSError):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _terminate(pid: int, master_fd: int) -> None:
    """Close the PTY and make sure the shell and its children are gone.

    Closing the master sends SIGHUP to the session, which is enough for a
    well-behaved shell; the explicit SIGKILL covers processes that ignore it.
    """
    with contextlib.suppress(OSError):
        os.close(master_fd)
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, 0)


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket) -> None:
    auth_cfg = get_auth_config(websocket)
    if not auth_cfg.terminal_enabled:
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Terminal is disabled")
        return
    if await authorize_websocket(websocket, admin=True) is None:
        return

    await websocket.accept()

    settings = get_settings(websocket)
    shell = os.environ.get("CAELUM_TERMINAL_SHELL") or os.environ.get("SHELL") or _DEFAULT_SHELL
    try:
        pid, master_fd = _spawn_shell(shell, str(settings.data_dir))
    except OSError:
        logger.exception("Failed to start terminal shell %r", shell)
        await websocket.close(code=1011, reason="Failed to start shell")
        return

    logger.info("Terminal session opened (pid=%d, shell=%s)", pid, shell)
    loop = asyncio.get_running_loop()
    os.set_blocking(master_fd, False)

    # The reader callback cannot await, so it hands chunks to this queue and
    # a single sender task drains it — which also keeps output frames in
    # order, something a task-per-chunk approach would not guarantee.
    outbound: asyncio.Queue[bytes | None] = asyncio.Queue()

    def on_readable() -> None:
        try:
            data = os.read(master_fd, _READ_CHUNK)
        except BlockingIOError:
            return
        except OSError:
            # EIO on Linux is how a closed slave end (the shell exited)
            # surfaces; treat any read error as end-of-stream.
            data = b""
        outbound.put_nowait(data or None)
        if not data:
            loop.remove_reader(master_fd)

    loop.add_reader(master_fd, on_readable)

    async def pump_output() -> None:
        while True:
            chunk = await outbound.get()
            if chunk is None:
                # The shell exited. Nothing else will ever close this socket
                # — the receive loop below would block on the client forever
                # — so say so in-band and hang up from this side.
                with contextlib.suppress(Exception):
                    await websocket.send_bytes(b"\r\n\x1b[2m[caelum] session ended\x1b[0m\r\n")
                    await websocket.close(code=1000)
                return
            await websocket.send_bytes(chunk)

    sender = asyncio.create_task(pump_output())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = message.get("type")
            if kind == "input":
                os.write(master_fd, str(message.get("data", "")).encode("utf-8"))
            elif kind == "resize":
                _set_winsize(master_fd, int(message.get("rows", 24)), int(message.get("cols", 80)))
    except WebSocketDisconnect:
        pass
    except (OSError, RuntimeError):
        # The shell exited while we were writing to it, or `pump_output`
        # closed the socket out from under this receive — both are the
        # normal end of a session, not errors.
        pass
    except Exception:
        logger.exception("Error serving /ws/terminal")
    finally:
        with contextlib.suppress(ValueError, OSError):
            loop.remove_reader(master_fd)
        outbound.put_nowait(None)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        _terminate(pid, master_fd)
        logger.info("Terminal session closed (pid=%d)", pid)
