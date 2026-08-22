"""Run notifications: who is emailed, when, and what the message says.

The relay itself is never touched — every test injects a recorder in place of
SMTP, so what is asserted is the decision to send and the content sent.
"""

import time

import pytest
from fastapi.testclient import TestClient

from process_engine_api import create_app
from process_engine_core.models import (
    NotificationEvent,
    NotificationSettings,
    ProcessDefinition,
    ProcessInstance,
    RunStatus,
    StepRun,
    utcnow,
)
from process_engine_core.notifications import (
    MAIL_SETTINGS_KEY,
    MailSettings,
    MailSettingsStore,
    Notifier,
    event_for,
    recipients_for,
    render,
)
from process_engine_core.registry import spec_registry
from process_engine_core.storage import Database

TOKEN = "test-token"
RELAY = {"host": "smtp.example.com", "sender": "engine@example.com"}


class Relay:
    """Stands in for SMTP and records what would have gone out."""

    def __init__(self, fail: bool = False) -> None:
        self.messages = []
        self.fail = fail

    def __call__(self, settings: MailSettings, message) -> None:
        if self.fail:
            raise OSError("relay refused the connection")
        self.messages.append(message)

    def to(self, index: int = 0) -> list[str]:
        return [address.strip() for address in self.messages[index]["To"].split(",")]

    def body(self, index: int = 0) -> str:
        return "\n".join(part.get_content() for part in self.messages[index].walk() if part.get_content_type().startswith("text/"))

    def wait(self, count: int, tries: int = 60):
        """Notifications are dispatched as background tasks, so give the loop
        a chance to run them before asserting."""
        for _ in range(tries):
            if len(self.messages) >= count:
                return self.messages
            time.sleep(0.05)
        raise AssertionError(f"expected {count} email(s), got {len(self.messages)}")


def make_definition(**notifications) -> ProcessDefinition:
    return ProcessDefinition(
        name="Daily sales",
        created_by="creator@example.com",
        notifications=NotificationSettings(**notifications),
    )


def make_instance(status: RunStatus = RunStatus.SUCCEEDED, **kwargs) -> ProcessInstance:
    return ProcessInstance(
        process_id="p1",
        process_version=3,
        status=status,
        started_at=utcnow(),
        finished_at=utcnow(),
        **kwargs,
    )


def make_notifier(relay: Relay, db: Database | None = None) -> Notifier:
    store = MailSettingsStore(db or Database("sqlite://"))
    store.save(MailSettings(**RELAY))
    return Notifier(store, send=relay, public_url=lambda: "https://engine.example.com")


# -- which event a run is reported under --------------------------------------


@pytest.mark.parametrize(
    ("subscribed", "status", "expected"),
    [
        (["succeeded"], RunStatus.SUCCEEDED, NotificationEvent.SUCCEEDED),
        (["failed"], RunStatus.FAILED, NotificationEvent.FAILED),
        (["completed"], RunStatus.SUCCEEDED, NotificationEvent.COMPLETED),
        (["completed"], RunStatus.FAILED, NotificationEvent.COMPLETED),
        (["completed"], RunStatus.CANCELLED, NotificationEvent.COMPLETED),
        # the specific subscription wins, so this is one email and not two
        (["succeeded", "completed"], RunStatus.SUCCEEDED, NotificationEvent.SUCCEEDED),
        (["failed", "completed"], RunStatus.FAILED, NotificationEvent.FAILED),
        # subscribed, but not to what happened
        (["succeeded"], RunStatus.FAILED, None),
        (["failed"], RunStatus.SUCCEEDED, None),
        (["succeeded", "failed"], RunStatus.CANCELLED, None),
        (["started"], RunStatus.SUCCEEDED, None),
        ([], RunStatus.SUCCEEDED, None),
    ],
)
def test_event_for_picks_the_most_specific_subscription(subscribed, status, expected):
    assert event_for(NotificationSettings(events=subscribed), status) is expected


@pytest.mark.parametrize("status", [RunStatus.PAUSED, RunStatus.RUNNING, RunStatus.PENDING])
def test_a_run_that_has_not_ended_reports_nothing(status):
    """A paused run is not a finished one — it has a resume waiting for it."""
    settings = NotificationSettings(events=["succeeded", "failed", "completed"])
    assert event_for(settings, status) is None


# -- who gets it ---------------------------------------------------------------


def test_recipients_combine_the_creator_and_the_extra_list():
    definition = make_definition(events=["failed"], recipients=["ops@example.com"])
    assert recipients_for(definition) == ["creator@example.com", "ops@example.com"]


def test_the_creator_can_be_left_off():
    definition = make_definition(
        events=["failed"], notify_creator=False, recipients=["ops@example.com"]
    )
    assert recipients_for(definition) == ["ops@example.com"]


def test_a_creator_who_is_not_an_email_address_is_skipped():
    """Local accounts (and the api-token principal) need not be addresses."""
    definition = make_definition(events=["failed"], recipients=["ops@example.com"])
    definition.created_by = "api-token"
    assert recipients_for(definition) == ["ops@example.com"]


def test_recipients_are_deduplicated_regardless_of_case():
    definition = make_definition(
        events=["failed"],
        recipients=["Creator@Example.com", "ops@example.com", " ops@example.com "],
    )
    assert recipients_for(definition) == ["creator@example.com", "ops@example.com"]


def test_junk_recipients_never_reach_the_relay():
    definition = make_definition(
        events=["failed"], notify_creator=False, recipients=["", "  ", "not-an-address", "ops@example.com"]
    )
    assert recipients_for(definition) == ["ops@example.com"]


# -- the message ---------------------------------------------------------------


def test_a_failed_run_is_worded_as_failed_even_when_subscribed_to_completed():
    definition = make_definition(events=["completed"])
    instance = make_instance(
        RunStatus.FAILED,
        error="step 'Load' failed: timeout",
        step_runs=[StepRun(step_id="s1", step_name="Load", status=RunStatus.FAILED, error="timeout")],
    )
    subject, text, html = render(
        definition, instance, NotificationEvent.COMPLETED, "https://engine.example.com"
    )

    assert subject == "Daily sales — run failed"
    for body in (text, html):
        assert "failed" in body
        assert "Load" in body  # the step that ended it
        assert instance.id in body
        assert f"https://engine.example.com/app/runs?run={instance.id}" in body


def test_a_started_email_does_not_claim_a_duration():
    definition = make_definition(events=["started"])
    instance = make_instance(RunStatus.RUNNING)
    instance.finished_at = None
    subject, text, _ = render(definition, instance, NotificationEvent.STARTED, "")

    assert subject == "Daily sales — run started"
    assert "Duration" not in text
    assert "Open the run" not in text  # no public URL configured, so no link


def test_the_message_escapes_a_process_name_that_looks_like_markup():
    definition = make_definition(events=["succeeded"])
    definition.name = "Sales <b>&</b> stock"
    _, _, html = render(definition, make_instance(), NotificationEvent.SUCCEEDED, "")
    assert "Sales &lt;b&gt;&amp;&lt;/b&gt; stock" in html


# -- the stored relay ----------------------------------------------------------


def test_the_mail_password_is_encrypted_at_rest_and_never_returned():
    db = Database("sqlite://")
    store = MailSettingsStore(db)
    store.save(MailSettings(**RELAY, username="engine", password="hunter2"))

    stored = db.get_setting(MAIL_SETTINGS_KEY)
    assert "hunter2" not in str(stored)
    assert stored["password_encrypted"]
    assert store.get().password == "hunter2"  # round-trips for the sender

    public = store.public()
    assert "password" not in public
    assert public["password_set"] is True
    assert public["configured"] is True and public["active"] is True


def test_a_relay_without_a_host_is_not_usable():
    store = MailSettingsStore(Database("sqlite://"))
    assert store.get().configured is False
    store.save(MailSettings(host="smtp.example.com"))  # no sender
    assert store.get().configured is False


# -- Amazon SES as the transport -----------------------------------------------


def test_ses_needs_a_region_and_sender_but_not_keys():
    """Inside AWS the instance role signs the call, so keys are optional."""
    store = MailSettingsStore(Database("sqlite://"))
    store.save(MailSettings(provider="ses", region="eu-west-1", sender="engine@example.com"))
    assert store.get().configured is True

    store.save(MailSettings(provider="ses", region="", sender="engine@example.com"))
    assert store.get().configured is False
    store.save(MailSettings(provider="ses", region="eu-west-1", sender=""))
    assert store.get().configured is False


def test_switching_to_ses_does_not_borrow_the_smtp_host():
    """An SMTP host left over from before must not make SES look configured."""
    store = MailSettingsStore(Database("sqlite://"))
    store.save(MailSettings(provider="ses", host="smtp.example.com", sender="engine@example.com", region=""))
    assert store.get().configured is False


def test_the_ses_secret_key_is_encrypted_at_rest_and_never_returned():
    db = Database("sqlite://")
    store = MailSettingsStore(db)
    store.save(
        MailSettings(
            provider="ses", region="eu-west-1", sender="engine@example.com",
            access_key_id="AKIAEXAMPLE", secret_access_key="wJalrXUtnFEMI",
        )
    )
    stored = db.get_setting(MAIL_SETTINGS_KEY)
    assert "wJalrXUtnFEMI" not in str(stored)
    assert store.get().secret_access_key == "wJalrXUtnFEMI"

    public = store.public()
    assert "secret_access_key" not in public and "password" not in public
    assert public["secret_access_key_set"] is True
    assert public["access_key_id"] == "AKIAEXAMPLE"  # the id is not a secret


async def test_ses_sends_the_same_message_smtp_would():
    """The provider decides the wire, never the content."""
    relay = Relay()
    store = MailSettingsStore(Database("sqlite://"))
    store.save(MailSettings(provider="ses", region="eu-west-1", sender="engine@example.com"))
    notifier = Notifier(store, send=relay, public_url=lambda: "https://engine.example.com")

    definition = make_definition(events=["failed"], recipients=["ops@example.com"])
    sent = await notifier.deliver(definition, make_instance(RunStatus.FAILED), NotificationEvent.FAILED)

    assert sent == ["creator@example.com", "ops@example.com"]
    assert relay.to() == ["creator@example.com", "ops@example.com"]
    assert relay.messages[0]["Subject"] == "Daily sales — run failed"


def test_ses_builds_a_raw_email_call_with_the_envelope_recipients():
    """Exercises the real boto3 request shape, with a stubbed client."""
    from process_engine_core import notifications

    calls = []

    class FakeClient:
        def send_email(self, **request):
            calls.append(request)
            return {"MessageId": "abc"}

    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            calls.append((service, kwargs))
            return FakeClient()

    settings = MailSettings(
        provider="ses", region="eu-west-1", sender="engine@example.com",
        access_key_id="AKIA", secret_access_key="shh", configuration_set="tracking",
    )
    message = notifications.build_message(
        settings, ["ops@example.com", "lead@example.com"], "Subject", "text", "<p>html</p>"
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(__import__("sys").modules, "boto3", FakeBoto)
        notifications.send_message(settings, message)

    service, kwargs = calls[0]
    assert service == "sesv2" and kwargs["region_name"] == "eu-west-1"
    assert kwargs["aws_access_key_id"] == "AKIA" and kwargs["aws_secret_access_key"] == "shh"

    request = calls[1]
    assert request["FromEmailAddress"] == "engine@example.com"
    assert request["Destination"]["ToAddresses"] == ["ops@example.com", "lead@example.com"]
    assert request["ConfigurationSetName"] == "tracking"
    assert b"Subject" in request["Content"]["Raw"]["Data"]  # raw MIME, not a template


def test_ses_without_keys_lets_boto3_find_its_own_credentials():
    from process_engine_core import notifications

    calls = []

    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            calls.append(kwargs)
            return type("C", (), {"send_email": lambda self, **r: {"MessageId": "x"}})()

    settings = MailSettings(provider="ses", region="us-east-1", sender="engine@example.com")
    message = notifications.build_message(settings, ["ops@example.com"], "s", "t", "<p>h</p>")
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(__import__("sys").modules, "boto3", FakeBoto)
        notifications.send_message(settings, message)

    assert calls[0] == {"region_name": "us-east-1"}  # no explicit credentials passed


def test_switching_the_relay_off_keeps_the_settings():
    store = MailSettingsStore(Database("sqlite://"))
    store.save(MailSettings(**RELAY, enabled=False))
    settings = store.get()
    assert settings.configured is True and settings.active is False


# -- delivery ------------------------------------------------------------------


async def test_deliver_emails_everyone_on_the_list_once():
    relay = Relay()
    definition = make_definition(events=["succeeded"], recipients=["ops@example.com"])
    sent = await make_notifier(relay).deliver(definition, make_instance(), NotificationEvent.SUCCEEDED)

    assert sent == ["creator@example.com", "ops@example.com"]
    assert len(relay.messages) == 1  # one message, two recipients
    assert relay.to() == ["creator@example.com", "ops@example.com"]
    assert relay.messages[0]["From"] == "engine@example.com"


async def test_deliver_says_nothing_when_the_process_did_not_ask():
    relay = Relay()
    definition = make_definition(events=["failed"])
    assert await make_notifier(relay).deliver(definition, make_instance(), NotificationEvent.SUCCEEDED) == []
    assert relay.messages == []


async def test_deliver_says_nothing_when_there_is_no_one_to_tell():
    relay = Relay()
    definition = make_definition(events=["succeeded"], notify_creator=False)
    assert await make_notifier(relay).deliver(definition, make_instance(), NotificationEvent.SUCCEEDED) == []
    assert relay.messages == []


async def test_deliver_is_quiet_when_no_relay_is_configured():
    store = MailSettingsStore(Database("sqlite://"))  # nothing saved
    relay = Relay()
    notifier = Notifier(store, send=relay)
    definition = make_definition(events=["succeeded"])
    assert await notifier.deliver(definition, make_instance(), NotificationEvent.SUCCEEDED) == []
    assert relay.messages == []


async def test_a_broken_relay_never_raises_at_the_caller():
    """The run is already over; a dead mail server may not surface as anything
    but a log line."""
    definition = make_definition(events=["succeeded"])
    notifier = make_notifier(Relay(fail=True))
    assert await notifier.deliver(definition, make_instance(), NotificationEvent.SUCCEEDED) == []


# -- through the API -----------------------------------------------------------


def make_client(relay: Relay | None = None) -> TestClient:
    registry = spec_registry()
    db = Database("sqlite://")
    notifier = None
    if relay is not None:
        store = MailSettingsStore(db)
        store.save(MailSettings(**RELAY))
        notifier = Notifier(store, send=relay, public_url=lambda: "https://engine.example.com")
    client = TestClient(create_app(db=db, registry=registry, auth_token=TOKEN, notifier=notifier))
    # the run is executed by an engine host, so the relay under test has to be
    # the one *it* holds — the engine_host fixture takes both from here
    client.db = db
    client.notifier = notifier
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def sign_in(client: TestClient, username: str, role: str = "editor") -> str:
    client.post("/api/users", json={"username": username, "password": "pw", "role": role})
    return client.post("/api/auth/login", json={"username": username, "password": "pw"}).json()["token"]


DEFINITION = {
    "name": "Nightly",
    "steps": [{"id": "set", "plugin": "transform", "config": {"values": {"msg": "hi"}}}],
    "connections": [],
    "notifications": {"events": ["succeeded"], "recipients": ["ops@example.com"]},
}


def test_the_creator_is_recorded_and_survives_later_edits():
    client = make_client()
    session = sign_in(client, "alice@example.com")
    mine = {"Authorization": f"Bearer {session}"}

    created = client.post("/api/processes", json=DEFINITION, headers=mine).json()
    assert created["created_by"] == "alice@example.com"

    # the designer PUTs a definition with no created_by of its own
    edited = client.put(f"/api/processes/{created['id']}", json={**DEFINITION, "name": "Renamed"}).json()
    assert edited["created_by"] == "alice@example.com"


def test_a_client_cannot_claim_someone_else_as_the_creator():
    client = make_client()
    created = client.post("/api/processes", json={**DEFINITION, "created_by": "boss@example.com"}).json()
    assert created["created_by"] == "api-token"


def test_a_copy_belongs_to_whoever_made_it():
    client = make_client()
    original = client.post("/api/processes", json=DEFINITION).json()
    session = sign_in(client, "bob@example.com")
    # bob has to be able to see it before he can copy it
    client.post(f"/api/processes/{original['id']}/share", json={"usernames": ["bob@example.com"]})
    clone = client.post(
        f"/api/processes/{original['id']}/clone", json={}, headers={"Authorization": f"Bearer {session}"}
    ).json()
    assert clone["created_by"] == "bob@example.com"
    assert clone["notifications"]["events"] == ["succeeded"]  # the subscription comes along


def test_a_run_emails_the_subscribers(engine_host):
    relay = Relay()
    with make_client(relay) as client:
        process_id = client.post("/api/processes", json=DEFINITION).json()["id"]
        run = engine_host.run(client, process_id, draft=True)
        assert run["status"] == "succeeded"

        relay.wait(1)
        assert relay.to() == ["ops@example.com"]  # api-token is not an address
        assert "Nightly — run succeeded" == relay.messages[0]["Subject"]
        assert run["id"] in relay.body()


def test_started_and_finished_are_two_separate_emails(engine_host):
    relay = Relay()
    with make_client(relay) as client:
        definition = {**DEFINITION, "notifications": {"events": ["started", "completed"],
                                                      "recipients": ["ops@example.com"]}}
        process_id = client.post("/api/processes", json=definition).json()["id"]
        engine_host.run(client, process_id, draft=True)

        relay.wait(2)
        assert [message["Subject"] for message in relay.messages] == [
            "Nightly — run started",
            "Nightly — run succeeded",
        ]


def test_iterating_a_sub_process_is_still_one_set_of_emails(engine_host):
    """A for_each over three rows is one run the user started, not four."""
    relay = Relay()
    with make_client(relay) as client:
        sub = {
            "name": "Per row",
            "steps": [{"id": "echo", "plugin": "transform",
                       "config": {"values": {"row": "{{ trigger.item }}"}}}],
            "connections": [],
            # the sub-process asks for mail too, and still must not send any:
            # it is not what anybody pressed Run on
            "notifications": {"events": ["started", "completed"], "recipients": ["ops@example.com"]},
        }
        sub_id = client.post("/api/processes", json=sub).json()["id"]
        client.post(f"/api/processes/{sub_id}/publish")

        parent = {
            "name": "Fan out",
            "steps": [{"id": "fan", "plugin": "for_each",
                       "config": {"items": ["a", "b", "c"], "process_id": sub_id}}],
            "connections": [],
            "notifications": {"events": ["started", "completed"], "recipients": ["ops@example.com"]},
        }
        parent_id = client.post("/api/processes", json=parent).json()["id"]
        run = engine_host.run(client, parent_id, draft=True)
        assert run["status"] == "succeeded"

        relay.wait(2)
        time.sleep(0.3)  # give any stray sub-process email time to show up
        assert [message["Subject"] for message in relay.messages] == [
            "Fan out — run started",
            "Fan out — run succeeded",
        ]


def test_a_process_nobody_subscribed_to_sends_nothing(engine_host):
    relay = Relay()
    with make_client(relay) as client:
        definition = {**DEFINITION, "notifications": {"events": []}}
        process_id = client.post("/api/processes", json=definition).json()["id"]
        engine_host.run(client, process_id, draft=True)
        time.sleep(0.3)
        assert relay.messages == []


def test_a_failed_run_reports_the_failure(engine_host):
    relay = Relay()
    with make_client(relay) as client:
        definition = {
            "name": "Breaks",
            "steps": [{"id": "boom", "plugin": "http_request", "config": {"url": "http://127.0.0.1:1/nope"}}],
            "connections": [],
            "notifications": {"events": ["failed"], "recipients": ["ops@example.com"]},
        }
        process_id = client.post("/api/processes", json=definition).json()["id"]
        run = engine_host.run(client, process_id, draft=True)
        assert run["status"] == "failed"

        relay.wait(1)
        assert relay.messages[0]["Subject"] == "Breaks — run failed"
        assert "boom" in relay.body()


# -- the relay settings endpoints ----------------------------------------------


def test_mail_settings_round_trip_without_ever_returning_the_password():
    client = make_client()
    assert client.get("/api/notifications/mail").json()["configured"] is False

    saved = client.put(
        "/api/notifications/mail",
        json={"host": "smtp.example.com", "sender": "engine@example.com",
              "username": "engine", "password": "hunter2", "port": 465, "encryption": "ssl"},
    ).json()
    assert saved["password_set"] is True and saved["configured"] is True
    assert "password" not in saved
    assert saved["port"] == 465 and saved["encryption"] == "ssl"

    # saving again without a password keeps the stored one
    again = client.put(
        "/api/notifications/mail",
        json={"host": "smtp.example.com", "sender": "engine@example.com", "username": "engine"},
    ).json()
    assert again["password_set"] is True

    # ...and an explicit empty string clears it, for a relay that needs no login
    cleared = client.put(
        "/api/notifications/mail",
        json={"host": "smtp.example.com", "sender": "engine@example.com", "password": ""},
    ).json()
    assert cleared["password_set"] is False


def test_the_relay_can_be_switched_to_ses_through_the_api():
    client = make_client()
    saved = client.put(
        "/api/notifications/mail",
        json={"provider": "ses", "region": "eu-west-1", "sender": "engine@example.com",
              "access_key_id": "AKIA", "secret_access_key": "shh", "configuration_set": "tracking"},
    ).json()
    assert saved["provider"] == "ses" and saved["configured"] is True
    assert saved["secret_access_key_set"] is True
    assert "secret_access_key" not in saved

    # saving again without the key keeps it; "" clears it back to the instance role
    again = client.put(
        "/api/notifications/mail",
        json={"provider": "ses", "region": "eu-west-1", "sender": "engine@example.com"},
    ).json()
    assert again["secret_access_key_set"] is True
    cleared = client.put(
        "/api/notifications/mail",
        json={"provider": "ses", "region": "eu-west-1", "sender": "engine@example.com",
              "secret_access_key": ""},
    ).json()
    assert cleared["secret_access_key_set"] is False and cleared["configured"] is True

    assert client.put("/api/notifications/mail", json={"provider": "carrier-pigeon"}).status_code == 422


def test_only_admins_may_change_the_relay():
    client = make_client()
    editor = {"Authorization": f"Bearer {sign_in(client, 'ed@example.com')}"}

    assert client.get("/api/notifications/mail", headers=editor).status_code == 200  # readable
    assert client.put("/api/notifications/mail", json={"host": "x"}, headers=editor).status_code == 403
    assert client.post("/api/notifications/test", json={}, headers=editor).status_code == 403


def test_the_test_email_reports_what_the_relay_said():
    relay = Relay(fail=True)
    client = make_client(relay)
    response = client.post("/api/notifications/test", json={"to": "me@example.com"})
    assert response.status_code == 502
    assert "relay refused" in response.json()["detail"]

    working = Relay()
    ok = make_client(working).post("/api/notifications/test", json={"to": "me@example.com"})
    assert ok.status_code == 200 and ok.json()["sent_to"] == "me@example.com"
    assert working.to() == ["me@example.com"]


def test_the_test_email_needs_a_real_address():
    client = make_client(Relay())
    # the api-token principal has no address of its own to fall back to
    assert client.post("/api/notifications/test", json={}).status_code == 422
    assert client.post("/api/notifications/test", json={"to": "nonsense"}).status_code == 422


def test_the_directory_offers_addressable_users_to_any_editor():
    client = make_client()
    sign_in(client, "alice@example.com")
    sign_in(client, "local-admin")  # not an address, so not offerable
    editor = {"Authorization": f"Bearer {sign_in(client, 'ed@example.com')}"}

    directory = client.get("/api/users/directory", headers=editor).json()
    assert directory == ["alice@example.com", "ed@example.com"]

    client.put("/api/users/alice@example.com", json={"disabled": True})
    assert client.get("/api/users/directory").json() == ["ed@example.com"]
