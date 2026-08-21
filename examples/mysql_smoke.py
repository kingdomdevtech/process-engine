"""Verify the MySQL storage backend end-to-end: save, publish, run, reload.

    docker compose up -d mysql
    $env:PROCESS_ENGINE_DB_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
    python examples\\mysql_smoke.py
"""

import asyncio

from process_engine.engine import Engine
from process_engine.models import Connection, ProcessDefinition, Step
from process_engine.registry import PluginRegistry
from process_engine.storage import Database


def main() -> None:
    db = Database()  # honours PROCESS_ENGINE_DB_URL
    print("dialect:", db.engine.dialect.name)

    definition = ProcessDefinition(
        name="MySQL smoke test",
        steps=[
            Step(id="set", plugin="transform", config={"values": {"msg": "stored in mysql"}}),
            Step(id="log", plugin="log", config={"message": "{{ steps.set.output.msg }}"}),
        ],
        connections=[Connection(source="set", target="log")],
    )
    db.save_process(definition)
    published = db.publish_process(definition.id)
    print("published version:", published.version)

    registry = PluginRegistry()
    registry.load_builtins()
    instance = asyncio.run(Engine(registry).run(db.get_version(definition.id)))
    db.save_instance(instance)

    print("reloaded process:", db.get_process(definition.id).name)
    print("run status from db:", db.get_instance(instance.id).status)
    print("runs listed:", len(db.list_instances(definition.id)))


if __name__ == "__main__":
    main()
