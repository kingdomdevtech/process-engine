from datetime import datetime, timedelta, timezone

from process_engine_core.models import ProcessDefinition, Step, Trigger
from process_engine.scheduler import LATE_TOLERANCE_SECONDS, Scheduler
from process_engine_core.storage import Database


def _cron_process(db: Database, cron: str = "* * * * *") -> ProcessDefinition:
    definition = ProcessDefinition(
        name="cron job",
        steps=[Step(id="s", plugin="log")],
        triggers=[Trigger(type="schedule", cron=cron)],
    )
    db.save_process(definition)
    db.publish_process(definition.id)
    return definition


def test_tick_fires_when_cron_is_due():
    db = Database("sqlite://")
    definition = ProcessDefinition(
        name="cron job",
        steps=[Step(id="s", plugin="log")],
        triggers=[Trigger(type="schedule", cron="* * * * *")],
    )
    db.save_process(definition)
    db.publish_process(definition.id)

    fired: list[tuple[str, dict]] = []
    scheduler = Scheduler(db, lambda d, trigger_input: (fired.append((d.id, trigger_input)), "run-1")[1])

    base = datetime(2026, 8, 17, 12, 0, 30, tzinfo=timezone.utc)
    assert scheduler.tick(base) == []  # first sighting primes next_due (12:01:00), no fire
    assert scheduler.tick(base + timedelta(seconds=10)) == []  # 12:00:40 — not due yet
    assert scheduler.tick(base + timedelta(seconds=40)) == ["run-1"]  # 12:01:10 — due
    assert fired[0][0] == definition.id
    assert fired[0][1]["cron"] == "* * * * *"
    assert scheduler.tick(base + timedelta(seconds=50)) == []  # next due is 12:02:00


def test_unpublished_and_disabled_triggers_do_not_fire():
    db = Database("sqlite://")
    draft_only = ProcessDefinition(
        steps=[Step(id="s", plugin="log")],
        triggers=[Trigger(type="schedule", cron="* * * * *")],
    )
    db.save_process(draft_only)  # never published

    disabled = ProcessDefinition(
        steps=[Step(id="s", plugin="log")],
        triggers=[Trigger(type="schedule", cron="* * * * *", enabled=False)],
    )
    db.save_process(disabled)
    db.publish_process(disabled.id)

    scheduler = Scheduler(db, lambda d, t: "never")
    base = datetime(2026, 8, 17, 12, 0, 30, tzinfo=timezone.utc)
    scheduler.tick(base)
    assert scheduler.tick(base + timedelta(minutes=5)) == []


def test_two_schedulers_on_one_database_fire_a_window_once():
    """Every engine host schedules for itself, so several watch the same cron."""
    db = Database("sqlite://")
    definition = _cron_process(db)

    fired: list[str] = []
    linux = Scheduler(db, lambda d, t: (fired.append("linux"), "run-linux")[1])
    windows = Scheduler(db, lambda d, t: (fired.append("windows"), "run-windows")[1])

    base = datetime(2026, 8, 17, 12, 0, 30, tzinfo=timezone.utc)
    linux.tick(base)  # first sighting arms next_due = 12:01:00
    windows.tick(base)  # already armed; must not re-arm or fire

    due = base + timedelta(seconds=40)  # 12:01:10
    launched = linux.tick(due) + windows.tick(due)
    assert launched == ["run-linux"], "the loser of the claim must not launch a second run"
    assert fired == ["linux"]
    assert definition.id  # (the definition is the one both saw)

    later = base + timedelta(seconds=95)  # 12:02:05 — the next window, other way round
    assert windows.tick(later) + linux.tick(later) == ["run-windows"]


def test_a_window_nobody_was_running_for_is_skipped_not_owed():
    """Cron semantics: a missed window is spent. Restarting must not stampede."""
    db = Database("sqlite://")
    _cron_process(db)

    fired: list[str] = []
    scheduler = Scheduler(db, lambda d, t: (fired.append(d.id), "run-1")[1])

    base = datetime(2026, 8, 17, 12, 0, 30, tzinfo=timezone.utc)
    scheduler.tick(base)  # arms 12:01:00, then nothing runs for an hour
    stale = base + timedelta(seconds=LATE_TOLERANCE_SECONDS + 3600)
    assert scheduler.tick(stale) == []
    assert fired == []
    # ...but the window was rolled forward, so the next one fires normally
    assert scheduler.tick(stale + timedelta(minutes=1)) == ["run-1"]
