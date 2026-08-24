"""Which mailboxes this Outlook is signed in to, asked out of process.

The dashboard needs this to check the configured mailbox against reality, and
cannot ask Outlook directly: COM belongs to the thread that initialised it, and
a request handler is the wrong thread. So it shells out to `cli accounts`.

That costs several seconds, and the answer changes about as often as someone
adds an account to Outlook, so it is cached. The page fills the cache in the
background; an edit waits for it, because refusing a change on the strength of
an empty cache would be a claim about Outlook that was never checked.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from rotem_agent.config import PROJECT_ROOT

TTL_SECONDS = 600.0

# Outlook can take a while to answer the first COM call of the day, especially
# while it is still opening.
TIMEOUT_SECONDS = 90.0


class Accounts:
    def __init__(self, *, python: str | None = None, ttl: float = TTL_SECONDS) -> None:
        self.python = python or sys.executable
        self.ttl = ttl
        self._state = threading.Lock()
        self._fetching = threading.Lock()
        self._known: list[str] = []
        self._at = 0.0
        self._busy = False

    def cached(self) -> list[str]:
        """Whatever is known now, possibly nothing. Never blocks."""
        with self._state:
            return list(self._known)

    def known(self) -> list[str]:
        """Ask Outlook if what we have is stale or missing. Blocks.

        An empty result is not cached, so a failure because Outlook was closed
        is retried on the next edit rather than remembered for ten minutes.
        """
        if self._fresh():
            return self.cached()
        with self._fetching:
            # Another caller may have filled it while we waited for the lock.
            if self._fresh():
                return self.cached()
            found = self._fetch()
            with self._state:
                if found:
                    self._known = found
                    self._at = time.monotonic()
                return list(self._known)

    def prime(self) -> None:
        """Fill the cache in the background, so the page has it to show."""
        with self._state:
            if self._busy or self._is_fresh():
                return
            self._busy = True

        def run() -> None:
            try:
                self.known()
            finally:
                with self._state:
                    self._busy = False

        threading.Thread(target=run, daemon=True).start()

    # ----------------------------------------------------------------- internals

    def _fresh(self) -> bool:
        with self._state:
            return self._is_fresh()

    def _is_fresh(self) -> bool:
        """Caller holds the state lock."""
        return bool(self._known) and time.monotonic() - self._at < self.ttl

    def _fetch(self) -> list[str]:
        try:
            done = subprocess.run(
                [self.python, "-m", "rotem_agent.cli", "accounts"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            return []
        if done.returncode != 0:
            return []
        return [
            line.strip()
            for line in (done.stdout or "").splitlines()
            if "@" in line and line.strip()
        ]
