from fastapi.testclient import TestClient

from process_engine.api import create_app
from process_engine.datapicker import build_picker, upstream_step_ids
from process_engine.models import Connection, ProcessDefinition, Step
from process_engine.registry import PluginRegistry
from process_engine.storage import Database

TOKEN = "test-token"


def make_client() -> TestClient:
    registry = PluginRegistry()
    registry.load_builtins()
    client = TestClient(create_app(db=Database("sqlite://"), registry=registry, auth_token=TOKEN))
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def chain():
    return ProcessDefinition(
        steps=[
            Step(id="a", name="fetch", plugin="transform"),
            Step(id="b", name="middle", plugin="transform"),
            Step(id="c", name="last", plugin="log"),
            Step(id="side", name="unrelated", plugin="log"),
        ],
        connections=[Connection(source="a", target="b"), Connection(source="b", target="c")],
    )


def test_upstream_walks_transitively_and_excludes_unrelated():
    assert upstream_step_ids(chain(), "c") == ["a", "b"]
    assert upstream_step_ids(chain(), "a") == []
    assert upstream_step_ids(chain(), "side") == []


def test_picker_without_run_lists_upstream_steps():
    groups = build_picker(chain(), "c", None)
    assert [group["key"] for group in groups] == ["trigger", "a", "b"]
    assert groups[1]["fields"][0]["path"] == "{{ steps.fetch.output }}"


def test_picker_flattens_recorded_outputs():
    client = make_client()
    definition = {
        "name": "picker demo",
        "steps": [
            {"id": "a", "name": "fetch", "plugin": "transform",
             "config": {"mode": "replace",
                        "values": {"customer": {"id": 7, "name": "ACME"}, "tags": ["x", "y"]}}},
            {"id": "b", "name": "next", "plugin": "log"},
        ],
        "connections": [{"source": "a", "target": "b"}],
    }
    process_id = client.post("/api/processes", json=definition).json()["id"]
    run = client.post(f"/api/processes/{process_id}/run",
                      json={"draft": True, "trigger_input": {"order": {"total": 250}}}).json()
    assert run["status"] == "succeeded"

    picker = client.get(f"/api/processes/{process_id}/steps/b/picker").json()
    groups = {group["key"]: group for group in picker["groups"]}

    trigger_paths = {field["path"] for field in groups["trigger"]["fields"]}
    assert "{{ trigger.order.total }}" in trigger_paths

    upstream = groups["a"]["fields"]
    paths = {field["path"]: field for field in upstream}
    assert "{{ steps.fetch.output.customer.id }}" in paths
    assert paths["{{ steps.fetch.output.customer.name }}"]["preview"] == "ACME"
    assert "{{ steps.fetch.output.tags }}" in paths          # the array itself
    assert "{{ steps.fetch.output.tags.0 }}" in paths        # and a sample element


def test_names_that_are_not_identifiers_fall_back_to_the_step_id():
    """A display name with a space cannot be addressed as a dotted path."""
    definition = ProcessDefinition(
        steps=[
            Step(id="abc123", name="fetch orders", plugin="transform"),
            Step(id="later", name="later", plugin="log"),
        ],
        connections=[Connection(source="abc123", target="later")],
    )
    groups = build_picker(definition, "later", None)
    paths = [field["path"] for group in groups for field in group["fields"]]
    assert "{{ steps.abc123.output }}" in paths
    assert not any(" orders" in path for path in paths)


def test_picker_reports_branch_ports():
    client = make_client()
    definition = {
        "name": "branch picker",
        "steps": [
            {"id": "check", "name": "check", "plugin": "condition",
             "config": {"left": 5, "operator": "greater_than", "right": 1}},
            {"id": "after", "name": "after", "plugin": "log"},
        ],
        "connections": [{"source": "check", "source_port": "true", "target": "after"}],
    }
    process_id = client.post("/api/processes", json=definition).json()["id"]
    client.post(f"/api/processes/{process_id}/run", json={"draft": True, "trigger_input": {"v": 1}})

    picker = client.get(f"/api/processes/{process_id}/steps/after/picker").json()
    check_group = next(group for group in picker["groups"] if group["key"] == "check")
    assert any(field.get("port") == "true" for field in check_group["fields"])
