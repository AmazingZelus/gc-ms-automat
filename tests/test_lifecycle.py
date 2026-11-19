"""When does the server stop? Tested with a fake clock (no waiting)."""

from gcms_automat.lifecycle import ClientTracker, LifecycleSettings


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make(**kw):
    clock = FakeClock()
    settings = LifecycleSettings(heartbeat_timeout_s=150, closing_grace_s=8, startup_timeout_s=120, **kw)
    return clock, ClientTracker(settings=settings, clock=clock)


def test_stops_if_no_browser_ever_connects():
    clock, t = make()
    clock.now = 119
    assert t.exit_reason() is None
    clock.now = 121
    assert t.exit_reason() is not None


def test_keeps_running_while_heartbeats_arrive():
    clock, t = make()
    for second in range(0, 1000, 60):  # background tab: one heartbeat per minute
        clock.now = second
        t.heartbeat("a")
        assert t.exit_reason() is None


def test_stops_after_tab_closed_and_grace_period():
    clock, t = make()
    t.heartbeat("a")
    t.closing("a")
    clock.now = 7
    assert t.exit_reason() is None
    clock.now = 9
    assert t.exit_reason() is not None


def test_reload_within_grace_keeps_running():
    clock, t = make()
    t.heartbeat("old-page")
    t.closing("old-page")
    clock.now = 2
    t.heartbeat("new-page")  # reloaded page has a new id
    clock.now = 100
    assert t.exit_reason() is None


def test_other_tab_keeps_running():
    clock, t = make()
    t.heartbeat("a")
    t.heartbeat("b")
    t.closing("a")
    clock.now = 20
    assert t.exit_reason() is None


def test_stops_when_heartbeats_stop():
    clock, t = make()
    t.heartbeat("a")
    clock.now = 151
    assert t.exit_reason() is not None


def test_quit_button():
    _, t = make()
    t.heartbeat("a")
    t.request_shutdown()
    assert t.exit_reason() is not None
