"""Self-update for a managed install (scripts/install-system.sh layout).

Every release gets its own venv under `<root>/releases/<version>`;
`<root>/current` points at the one systemd runs (through
`scripts/caelum-launch`, the boot guard that rolls back a release that never
comes up healthy). Updating is: install the new wheel into a fresh venv next
to the running one, flip the symlink, exit and let systemd restart us.

Outside a managed install (`CAELUM_RELEASES_DIR` unset — a dev checkout, a
plain `pip install`) none of this is active.
"""
