from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from caelum.mount.alpaca import AlpacaTelescope
from caelum.mount.indi import IndiTelescope


def _alpaca_server(values: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            prop = self.path.split("?")[0].rsplit("/", 1)[1]
            if prop in values:
                body = {"Value": values[prop], "ErrorNumber": 0, "ErrorMessage": ""}
            else:
                body = {"ErrorNumber": 0x400, "ErrorMessage": "not implemented"}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a): ...

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_alpaca_tracking_and_optional_properties_missing():
    server = _alpaca_server(
        {
            "connected": True,
            "rightascension": 6.0,
            "declination": 10.0,
            "tracking": True,
            "slewing": False,
            "atpark": False,
        }
    )
    state = AlpacaTelescope("127.0.0.1", server.server_port).read()
    server.shutdown()
    assert state.status == "tracking" and state.ra_deg == 90.0 and state.dec_deg == 10.0 and state.alt_deg is None


def test_alpaca_states():
    base = {
        "connected": True,
        "rightascension": 1.0,
        "declination": 0.0,
        "tracking": False,
        "slewing": False,
        "atpark": False,
    }
    for patch, expected in (
        ({}, "idle"),
        ({"slewing": True}, "slewing"),
        ({"atpark": True}, "parked"),
        ({"connected": False}, "disconnected"),
    ):
        server = _alpaca_server({**base, **patch})
        assert AlpacaTelescope("127.0.0.1", server.server_port).read().status == expected
        server.shutdown()


INDI_XML = (
    '<defSwitchVector device="Mount" name="CONNECTION" state="Ok"><defSwitch name="CONNECT">On</defSwitch>'
    '<defSwitch name="DISCONNECT">Off</defSwitch></defSwitchVector>'
    '<defNumberVector device="Mount" name="EQUATORIAL_EOD_COORD" state="{state}">'
    '<defNumber name="RA">6:00:00</defNumber><defNumber name="DEC">-10.5</defNumber></defNumberVector>'
    '<defSwitchVector device="Mount" name="TELESCOPE_TRACK_STATE" state="Ok"><defSwitch name="TRACK_ON">On</defSwitch>'
    "</defSwitchVector>"
)


def _indi_server(state: str):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(INDI_XML.format(state=state).encode())
        threading.Event().wait(2)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv


def test_indi_reads_tracking_and_slewing():
    for state, expected in (("Ok", "tracking"), ("Busy", "slewing")):
        srv = _indi_server(state)
        client = IndiTelescope("127.0.0.1", srv.getsockname()[1])
        result = client.read()
        client.close()
        srv.close()
        assert result.status == expected
        assert result.ra_deg == 90.0 and result.dec_deg == -10.5 and result.epoch == "jnow"
