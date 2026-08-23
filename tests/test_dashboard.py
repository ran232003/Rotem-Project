"""The page the lawyer actually clicks.

Two things are worth testing here rather than trusting. That the switch reaches
the control layer at all, and that a page on some other site she has open cannot
reach through the browser and turn her agent off.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from rotem_agent.dashboard import PAGE, _already_serving, _Handler, serve


class _Stub:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.forced = 0
        self.refreshed = []

    def _payload(self):
        return {"watcher": {"running": bool(self.started > self.stopped)}, "recent": []}

    def status(self):
        return self._payload()

    def start(self):
        self.started += 1
        return self._payload()

    def stop(self):
        self.stopped += 1
        return self._payload()

    def force_stop(self):
        self.forced += 1
        return self._payload()

    def refresh_outcomes(self, force=False):
        self.refreshed.append(force)


@pytest.fixture
def server():
    stub = _Stub()
    handler = type("_Bound", (_Handler,), {"dashboard": stub})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, stub
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def free_port():
    """A port nothing is listening on, by taking one and giving it straight back."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def _post(url, origin=None):
    request = urllib.request.Request(url, data=b"", method="POST")
    request.add_header("Content-Type", "application/json")
    if origin:
        request.add_header("Origin", origin)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def test_the_page_is_served_right_to_left(server):
    base, _ = server
    status, body = _get(base + "/")
    assert status == 200
    assert 'dir="rtl"' in body


def test_the_page_file_exists_beside_the_module():
    """It is loaded from disk, so a missing file is a blank dashboard."""
    assert PAGE.exists()


def test_status_is_json(server):
    base, _ = server
    status, body = _get(base + "/api/status")
    assert status == 200
    assert json.loads(body)["watcher"]["running"] is False


def test_reading_the_status_also_refreshes_the_sent_figures(server):
    """Throttled inside the dashboard, so this only checks it is asked."""
    base, stub = server
    _get(base + "/api/status")
    assert stub.refreshed == [False]


def test_the_switch_starts_the_agent(server):
    base, stub = server
    status, body = _post(base + "/api/start")
    assert status == 200
    assert stub.started == 1
    assert json.loads(body)["watcher"]["running"] is True


def test_the_switch_stops_the_agent(server):
    base, stub = server
    _post(base + "/api/start")
    _post(base + "/api/stop")
    assert stub.stopped == 1


def test_a_stop_that_never_lands_can_be_forced(server):
    """Reachable only from a page that has been waiting on 'stopping'."""
    base, stub = server
    _post(base + "/api/force-stop")
    assert stub.forced == 1


def test_refresh_is_forced_when_asked_for_by_hand(server):
    base, stub = server
    _post(base + "/api/refresh")
    assert stub.refreshed == [True]


def test_a_request_from_our_own_page_is_allowed(server):
    base, stub = server
    _post(base + "/api/start", origin=base)
    assert stub.started == 1


def test_another_site_cannot_turn_the_agent_off(server):
    """Loopback is not a boundary: any page she visits can post to localhost."""
    base, stub = server
    with pytest.raises(urllib.error.HTTPError) as caught:
        _post(base + "/api/stop", origin="https://example.com")
    assert caught.value.code == 403
    assert stub.stopped == 0


def test_an_unknown_path_is_not_found(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(base + "/secrets")
    assert caught.value.code == 404


def test_a_live_dashboard_is_recognised(server):
    base, _ = server
    assert _already_serving(base + "/") is True


def test_a_dead_port_is_not_mistaken_for_one(free_port):
    assert _already_serving(f"http://127.0.0.1:{free_port}/") is False


def test_clicking_the_icon_twice_shows_the_page_instead_of_starting_a_second(server, monkeypatch):
    """Windows honours SO_REUSEADDR, so a second bind would quietly succeed."""
    base, stub = server
    opened = []
    monkeypatch.setattr("rotem_agent.dashboard.webbrowser.open", opened.append)

    port = int(base.rsplit(":", 1)[1])
    serve(port=port, open_browser=True)

    assert opened == [base + "/"]
    # The stub belongs to the server already running; a second one never got built.
    assert stub.started == 0
