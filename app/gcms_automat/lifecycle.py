"""Decides when the local server should stop.

The browser page sends a "heartbeat" every few seconds. The server stops when:
  * the user clicks "Ukončit" (explicit shutdown), or
  * all browser tabs are closed (each tab says goodbye when closing, then a short
    grace period lets a page reload reconnect), or
  * no heartbeat arrived for a very long time (e.g. the browser crashed), or
  * no browser connected at all shortly after start.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class LifecycleSettings:
    """Timeouts in seconds (s)."""

    # Normal closing is detected by the tab's goodbye message (closing_grace_s).
    # The heartbeat timeout is only a safety net for a crashed browser, so it is
    # long: browsers slow down or freeze background tabs (Chrome: timers once per
    # minute; Edge "sleeping tabs" freeze a tab completely after ~2 h), and the
    # app must not stop while the user is just working in another program.
    heartbeat_timeout_s: float = 4 * 60 * 60.0
    # After a tab says goodbye, wait this long for a reload/new tab to reconnect.
    closing_grace_s: float = 8.0
    # Stop if no browser connects at all within this time after start
    # (long enough to copy the address by hand if the browser did not open).
    startup_timeout_s: float = 300.0


@dataclass
class ClientTracker:
    """Keeps track of open browser tabs (clients) and their last heartbeat."""

    settings: LifecycleSettings = field(default_factory=LifecycleSettings)
    clock: Callable[[], float] = time.monotonic
    _expires_at: dict = field(default_factory=dict)
    _had_client: bool = False
    _shutdown_requested: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        # This remembers when the server started (for the startup timeout).
        self._started_at = self.clock()

    def heartbeat(self, client_id: str) -> None:
        """A tab is alive: extend its expiry by the heartbeat timeout."""
        with self._lock:
            self._had_client = True
            self._expires_at[client_id] = self.clock() + self.settings.heartbeat_timeout_s

    def closing(self, client_id: str) -> None:
        """A tab is closing: let it expire after the short grace period."""
        with self._lock:
            if client_id in self._expires_at:
                self._expires_at[client_id] = self.clock() + self.settings.closing_grace_s

    def extend_all(self, seconds: float) -> None:
        """Give every open tab extra time (used after the computer wakes from sleep)."""
        with self._lock:
            floor = self.clock() + seconds
            self._expires_at = {cid: max(t, floor) for cid, t in self._expires_at.items()}

    def request_shutdown(self) -> None:
        """The user clicked 'Ukončit'."""
        with self._lock:
            self._shutdown_requested = True

    def exit_reason(self) -> str | None:
        """Return why the server should stop now, or None to keep running."""
        with self._lock:
            now = self.clock()
            # This handles the explicit "Ukončit" button.
            if self._shutdown_requested:
                return "user clicked Ukoncit"
            # This drops tabs whose heartbeat (or grace period) has expired.
            self._expires_at = {cid: t for cid, t in self._expires_at.items() if t > now}
            # This stops the server when every tab that was ever open is gone.
            if self._had_client and not self._expires_at:
                return "all browser tabs closed or inactive"
            # This stops the server when no browser ever connected.
            if not self._had_client and now - self._started_at > self.settings.startup_timeout_s:
                return "no browser connected after start"
            return None


def start_watchdog(tracker: ClientTracker, on_exit, interval_s: float = 1.0,
                   wake_gap_s: float = 30.0, wake_grace_s: float = 60.0,
                   clock=time.monotonic) -> threading.Thread:
    """Check once per interval whether to stop; call on_exit(reason) when it is time."""
    # This runs in the background and calls on_exit exactly once.
    def loop() -> None:
        last_check = clock()
        while True:
            try:
                # This detects that the computer was asleep (a check came much later
                # than planned) and gives the browser tabs time to reconnect first.
                now = clock()
                if now - last_check > wake_gap_s:
                    tracker.extend_all(wake_grace_s)
                last_check = now

                reason = tracker.exit_reason()
            except Exception as exc:  # never let the watchdog die silently
                reason = f"internal watchdog error: {exc!r}"
            if reason:
                on_exit(reason)
                return
            time.sleep(interval_s)

    thread = threading.Thread(target=loop, name="lifecycle-watchdog", daemon=True)
    thread.start()
    return thread
