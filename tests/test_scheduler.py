from datetime import datetime, timedelta, timezone

from process_engine.models import ProcessDefinition, Step, Trigger
from process_engine.scheduler import Scheduler
from process_engine.storage import Database


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
