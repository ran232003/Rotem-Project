"""A small page showing what the agent has done, with a switch to turn it off.

Deliberately built on the standard library. This is installed on a lawyer's
computer by someone who is not a programmer, so every dependency is a thing that
can fail during setup for reasons nobody present can diagnose. There is no
framework, no build step and nothing to install beyond what the agent already
needs.

It binds to the loopback address only. The page lists client names and email
subjects, which is privileged material and has no business being reachable from
the office network.

Neither Outlook nor the model is touched from inside a request. Reading Sent
Items happens in a separate short-lived process, because COM is bound to the
thread that initialised it and a request handler is the wrong thread.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rotem_agent import accounts as accounts_module
from rotem_agent import control, outcomes, senders, stats
from rotem_agent.config import PROJECT_ROOT
from rotem_agent.pricing import load_prices
from rotem_agent.state import DraftLedger
from rotem_agent.usage import UsageLog

PAGE = Path(__file__).resolve().parent / "dashboard.html"

# Refreshing walks Sent Items, so it is not done on every poll of a page that
# polls every few seconds.
REFRESH_EVERY_SECONDS = 300.0


class Dashboard:
    """Everything the handler needs, so the handler itself stays trivial."""

    def __init__(self, *, interval_seconds: int = 60, python: str | None = None) -> None:
        self.interval_seconds = interval_seconds
        self.python = python or sys.executable
        self.accounts = accounts_module.Accounts(python=self.python)
        self._refreshing = False
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def status(self) -> dict:
        watcher = control.watcher_status()
        snapshot = stats.build(
            entries=DraftLedger().entries(),
            records=UsageLog().read(),
            prices=load_prices(),
            outcomes=outcomes.load(),
        )
        snapshot["watcher"] = {
            "running": watcher.running,
            "pid": watcher.pid,
            "since": watcher.since,
            # A stop that has been asked for but not yet acted on is its own
            # state. Showing it as still running makes the button look broken.
            "stopping": watcher.running and control.stop_requested(),
            "stop_pending_seconds": control.stop_pending_seconds(),
        }
        snapshot["refreshing"] = self._refreshing
        snapshot["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot["senders"] = self.senders()
        snapshot["start_date"] = self.start_date()
        snapshot["mailbox"] = self.mailbox()
        snapshot["accounts"] = self.accounts.cached()
        return snapshot

    def mailbox(self) -> str:
        """The address config/mailbox.yaml declares, or empty if unreadable."""
        try:
            return senders.read_mailbox()
        except senders.SenderError:
            return ""

    def set_mailbox(self, address: str) -> dict:
        """Change the declared mailbox, checked against Outlook first.

        Blocks for as long as asking Outlook takes. That is the point: the field
        is a claim `doctor` verifies, and a page that let her save an address
        Outlook has never heard of would turn a wrong setting into a startup
        warning she sees days later, with nothing linking it to this click.
        """
        senders.set_mailbox(address, self.accounts.known())
        return self.status()

    def start_date(self) -> str | None:
        """The day before which mail is left alone, as a local date.

        Shown because otherwise its effect — old mail never being drafted — is
        indistinguishable from the agent being broken.
        """
        try:
            floor = senders.start_date()
        except senders.SenderError:
            return None
        return floor.astimezone().strftime("%d.%m.%Y") if floor else None

    def senders(self) -> list[str]:
        """The allowlist, or an empty list if the file cannot be read.

        A page that fails to load because of a malformed config would take the
        off switch down with it, which is the one control that must keep working.
        """
        try:
            return senders.read()
        except senders.SenderError:
            return []

    def add_sender(self, address: str) -> dict:
        senders.add(address)
        return self.status()

    def remove_sender(self, address: str) -> dict:
        senders.remove(address)
        return self.status()

    def start(self) -> dict:
        # Generous, because it returns the moment the lock is taken. A watcher
        # spends several seconds importing before it gets that far, and a
        # timeout shorter than that reports a start that worked as a failure.
        control.start_watcher(
            interval_seconds=self.interval_seconds,
            python=self.python,
            wait_seconds=30.0,
        )
        return self.status()

    def stop(self) -> dict:
        """Ask, and return at once. The watcher finishes its message first."""
        if control.watcher_status().running:
            control.request_stop()
        else:
            control.clear_stop()
        return self.status()

    def force_stop(self) -> dict:
        control.force_stop()
        return self.status()

    def refresh_outcomes(self, *, force: bool = False) -> None:
        """Update the sent/discarded figures in the background."""
        import time

        with self._lock:
            if self._refreshing:
                return
            if not force and time.monotonic() - self._last_refresh < REFRESH_EVERY_SECONDS:
                return
            self._refreshing = True

        def run() -> None:
            import time as clock

            try:
                subprocess.run(
                    [self.python, "-m", "rotem_agent.cli", "outcomes"],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    timeout=180,
                )
            except Exception:
                pass
            finally:
                with self._lock:
                    self._refreshing = False
                    self._last_refresh = clock.monotonic()

        threading.Thread(target=run, daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    dashboard: Dashboard
    server_version = "RotemDashboard/1.0"

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_page()
        elif self.path.startswith("/api/status"):
            self.dashboard.refresh_outcomes()
            self.dashboard.accounts.prime()
            self._send_json(self.dashboard.status())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if not self._same_origin():
            self.send_error(403, "cross-origin request refused")
            return
        if self.path == "/api/start":
            self._send_json(self.dashboard.start())
        elif self.path == "/api/stop":
            self._send_json(self.dashboard.stop())
        elif self.path == "/api/force-stop":
            self._send_json(self.dashboard.force_stop())
        elif self.path == "/api/refresh":
            self.dashboard.refresh_outcomes(force=True)
            self._send_json(self.dashboard.status())
        elif self.path == "/api/senders/add":
            self._change(self.dashboard.add_sender)
        elif self.path == "/api/senders/remove":
            self._change(self.dashboard.remove_sender)
        elif self.path == "/api/mailbox":
            self._change(self.dashboard.set_mailbox)
        else:
            self.send_error(404)

    def _change(self, action: Callable[[str], dict]) -> None:
        """Every config edit takes one address and may be refused with a reason.

        Refusals come back as 400 carrying the text, because each is something
        the person at the keyboard can correct: a typo, an address already
        listed, the last one being removed, or a mailbox Outlook does not have.
        """
        try:
            address = str(self._body().get("address", ""))
        except ValueError:
            self.send_error(400, "malformed request")
            return
        try:
            self._send_json(action(address))
        except senders.SenderError as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        # Bounded because the only callers post one address.
        raw = self.rfile.read(min(length, 4096))
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("not JSON") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _same_origin(self) -> bool:
        """Refuse a POST driven by some other page open in the same browser.

        Loopback is not a boundary: any site she visits can post to localhost.
        A browser will not let a cross-site request forge the Origin header, so
        an absent or matching one is the check.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.rstrip("/").endswith(f"//{self.headers.get('Host', '')}")

    def _send_page(self) -> None:
        try:
            body = PAGE.read_bytes()
        except OSError:
            self.send_error(500, "dashboard.html is missing")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        """Silence the per-request console spam; the page polls every few seconds."""


class _Server(ThreadingHTTPServer):
    # Left off so that something else on the port is a loud failure rather than
    # a silent second bind. See the note in serve().
    allow_reuse_address = False


def _already_serving(url: str) -> bool:
    """Whether the thing holding the port is our own dashboard."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url + "api/status", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def serve(
    *,
    port: int = 8765,
    interval_seconds: int = 60,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> None:
    url = f"http://{host}:{port}/"

    # Clicking the desktop icon a second time is the normal way to find out the
    # dashboard is already open, so answer that by showing the page. Asked
    # before binding because Windows honours SO_REUSEADDR literally: a second
    # bind on the same port succeeds, and requests then land on either server.
    if _already_serving(url):
        print("The dashboard is already open. Bringing it up in the browser.")
        if open_browser:
            webbrowser.open(url)
        return

    handler = type("_Bound", (_Handler,), {"dashboard": Dashboard(interval_seconds=interval_seconds)})
    server = _Server((host, port), handler)

    print(f"Dashboard at {url}")
    print("Leave this window open. Closing it closes the dashboard, not the agent.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
