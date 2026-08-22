"""Seed a two-process MySQL -> Excel demo into the same database the API uses.

    docker compose up -d mysql
    python examples\\mysql_excel_demo.py           # create table, secret, both processes; publish
    python examples\\mysql_excel_demo.py --run     # ...and run the parent once, engine-only
    python examples\\mysql_excel_demo.py --make-workbook --run
                                                   # ...also create the workbook first: a live
                                                   # ODBC connection to demo_orders if a MySQL
                                                   # ODBC driver is installed, else a placeholder
                                                   # Power Query (Windows + Excel + pywin32)

Re-running this script is also the reset switch: each demo process is matched
by name and its draft overwritten with the original definition, then published
as a new version — so a demo mangled while experimenting comes back pristine
(along with the demo_orders rows). A *renamed* demo is treated as your own fork
and left alone; the canonical name is simply recreated alongside it.

What it builds (both land in the "Demo" folder of the dashboard):

* "Demo - Triage one order" — the sub-process ``for_each`` fans out to. A
  condition compares ``{{ trigger.item.total }}`` against the process variable
  ``priority_threshold``; each branch UPDATEs the row's status in MySQL, and
  both branches converge on a log step.
* "Demo - Order review + Excel refresh" — the parent. Reads pending rows from
  ``demo_orders``, guards against an empty result, iterates them through the
  sub-process, then refreshes an Excel workbook whose Power Query pulls from
  that same table. The refresh step's ``error`` port is wired to a warning log,
  so the run still completes on a machine without Excel or the workbook. A
  disabled weekday-morning schedule trigger shows where automation would go.

Environment (all optional):

    DEMO_MYSQL_URL          where demo_orders lives; defaults to the
                            docker-compose MySQL from the repo root
    DEMO_WORKBOOK           workbook to refresh; defaults to
                            <cwd>\\workdir\\demo-orders.xlsx
    PROCESS_ENGINE_DB_URL   where the processes are stored — run this from the
                            same directory (and env) as ``python -m process_engine_api``
                            so the API sees them

The MySQL password is stored as the secret ``demo_mysql_password`` and the
steps reference ``{{ secrets.demo_mysql_password }}`` — the definition itself
never contains the credential.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from process_engine.engine import Engine
from process_engine_core.models import (
    Connection,
    ProcessDefinition,
    RetryPolicy,
    Step,
    Trigger,
)
from process_engine.registry import default_registry
from process_engine_core.secrets_store import SecretsManager
from process_engine_core.storage import Database

DEFAULT_MYSQL_URL = "mysql+pymysql://process_engine:process_engine@127.0.0.1:3306/process_engine"
SECRET_NAME = "demo_mysql_password"

ORDERS = [
    ("ACME", 250.00),
    ("Globex", 42.50),
    ("Initech", 180.00),
    ("Umbrella", 75.00),
    ("Stark Industries", 990.00),
    ("Wayne Enterprises", 12.00),
]


def seed_orders(mysql_url: str) -> int:
    """Create demo_orders and (re)fill it so the demo is re-runnable."""
    engine = create_engine(mysql_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS demo_orders (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        customer VARCHAR(80) NOT NULL,
                        total DECIMAL(10, 2) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'new'
                    )
                    """
                )
            )
            connection.execute(text("DELETE FROM demo_orders"))
            for customer, total in ORDERS:
                connection.execute(
                    text("INSERT INTO demo_orders (customer, total, status) VALUES (:c, :t, 'new')"),
                    {"c": customer, "t": total},
                )
    finally:
        engine.dispose()
    return len(ORDERS)


def mysql_step_connection(mysql_url: str) -> dict[str, Any]:
    """The Database section of each MySQL step; the password stays a secret reference."""
    url = make_url(mysql_url)
    return {
        "connect_using": "fields",
        "host": url.host or "127.0.0.1",
        "port": url.port or 3306,
        "database": url.database or "",
        "username": url.username or "",
        "password": "{{ secrets." + SECRET_NAME + " }}",
    }


def build_subprocess(conn: dict[str, Any]) -> ProcessDefinition:
    return ProcessDefinition(
        name="Demo - Triage one order",
        folder="Demo",
        variables={"priority_threshold": 100},
        steps=[
            Step(
                id="classify",
                name="classify",
                plugin="condition",
                config={
                    "left": "{{ trigger.item.total }}",
                    "operator": "greater_than",
                    "right": "{{ variables.priority_threshold }}",
                },
            ),
            Step(
                id="mark_priority",
                name="mark_priority",
                plugin="mysql_execute",
                config={
                    **conn,
                    "action": "statement",
                    "statement": "UPDATE demo_orders SET status = :status WHERE id = :id",
                    "params": {"status": "priority", "id": "{{ trigger.item.id }}"},
                },
            ),
            Step(
                id="mark_standard",
                name="mark_standard",
                plugin="mysql_execute",
                config={
                    **conn,
                    "action": "statement",
                    "statement": "UPDATE demo_orders SET status = :status WHERE id = :id",
                    "params": {"status": "standard", "id": "{{ trigger.item.id }}"},
                },
            ),
            Step(
                id="note",
                name="note",
                plugin="log",
                config={
                    "message": "Order {{ trigger.item.id }} ({{ trigger.item.customer }}, "
                    "total {{ trigger.item.total }}) triaged",
                },
            ),
        ],
        connections=[
            Connection(source="classify", source_port="true", target="mark_priority"),
            Connection(source="classify", source_port="false", target="mark_standard"),
            # Whichever branch ran delivers here; the dead one settles as skipped.
            Connection(source="mark_priority", target="note"),
            Connection(source="mark_standard", target="note"),
        ],
    )


def build_parent(conn: dict[str, Any], subprocess_id: str, workbook_path: str) -> ProcessDefinition:
    return ProcessDefinition(
        name="Demo - Order review + Excel refresh",
        folder="Demo",
        steps=[
            Step(
                id="fetch",
                name="fetch",
                plugin="mysql_query",
                config={
                    **conn,
                    "query": "SELECT id, customer, total, status FROM demo_orders "
                    "WHERE status = :status ORDER BY id",
                    "params": {"status": "new"},
                },
            ),
            Step(
                id="has_orders",
                name="has_orders",
                plugin="condition",
                config={
                    "left": "{{ steps.fetch.output.count }}",
                    "operator": "greater_than",
                    "right": 0,
                },
            ),
            Step(
                id="no_orders",
                name="no_orders",
                plugin="log",
                config={"message": "Nothing to do: no orders with status 'new'."},
            ),
            Step(
                id="triage",
                name="triage",
                plugin="for_each",
                config={
                    "items": "{{ steps.fetch.output.rows }}",
                    "process_id": subprocess_id,
                    "parallel": 4,
                },
            ),
            Step(
                id="refresh",
                name="refresh",
                plugin="excel_refresh",
                retry=RetryPolicy(max_attempts=2, backoff_seconds=2),
                config={
                    "workbook_path": workbook_path,
                    "connections": [],  # empty = refresh every connection in the workbook
                    "save": True,
                },
            ),
            Step(
                id="refresh_failed",
                name="refresh_failed",
                plugin="log",
                config={"message": "Excel refresh failed: {{ input.error }}", "level": "warning"},
            ),
            Step(
                id="summary",
                name="summary",
                plugin="transform",
                config={
                    "mode": "replace",
                    "values": {
                        "orders_triaged": "{{ steps.triage.output.count }}",
                        "succeeded": "{{ steps.triage.output.succeeded }}",
                        "workbook": "{{ steps.refresh.output.workbook }}",
                    },
                },
            ),
            Step(
                id="done",
                name="done",
                plugin="log",
                config={
                    "message": "Triaged {{ steps.triage.output.succeeded }}/"
                    "{{ steps.triage.output.count }} orders and refreshed "
                    "{{ steps.refresh.output.workbook }}",
                },
            ),
        ],
        connections=[
            Connection(source="fetch", target="has_orders"),
            Connection(source="has_orders", source_port="true", target="triage"),
            Connection(source="has_orders", source_port="false", target="no_orders"),
            Connection(source="triage", target="refresh"),
            Connection(source="refresh", target="summary"),
            Connection(source="summary", target="done"),
            # Failure routing: no Excel / missing workbook logs a warning
            # instead of failing the whole run.
            Connection(source="refresh", source_port="error", target="refresh_failed"),
        ],
        triggers=[
            Trigger(
                type="schedule",
                cron="0 7 * * 1-5",
                enabled=False,
                description="Weekday mornings at 07:00 - enable once the workbook path is real",
            )
        ],
    )


def _mysql_odbc_driver() -> str | None:
    """Newest installed MySQL ODBC Unicode driver, or None."""
    import winreg

    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers") as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if "MySQL ODBC" in name and "Unicode" in name and value == "Installed":
                    names.append(name)
    except OSError:
        return None

    def version(name: str) -> tuple[int, ...]:
        for token in name.split():
            if token.replace(".", "").isdigit():
                return tuple(int(part) for part in token.split("."))
        return (0,)

    return max(names, key=version) if names else None


def make_workbook(workbook_path: str, mysql_url: str) -> str:
    """Create the demo workbook; returns a description of what was built.

    With a MySQL ODBC driver installed, the workbook gets a live ODBC data
    connection against demo_orders. That classic connection type embeds the
    credentials in the connection string (fine for the throwaway demo login),
    which is what lets the engine refresh it completely unattended — a Power
    Query mashup refuses embedded credentials and insists on one interactive
    "Connect" per Windows user before headless refreshes work, so a real Power
    Query workbook needs that one-time grant done by hand first.

    Without the driver, a placeholder Power Query (static table) is created so
    the refresh step still has a genuine connection to exercise. Same
    requirements as the excel_refresh plugin: Windows, desktop Excel, pywin32.
    """
    import pythoncom
    from win32com.client import gencache

    path = Path(workbook_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    driver = _mysql_odbc_driver()
    url = make_url(mysql_url)

    pythoncom.CoInitialize()
    excel = None
    workbook = None
    try:
        excel = gencache.EnsureDispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Add()
        sheet = workbook.Worksheets(1)
        sheet.Name = "Orders"
        if driver:
            connection_string = (
                f"ODBC;DRIVER={{{driver}}};SERVER={url.host or '127.0.0.1'};"
                f"PORT={url.port or 3306};DATABASE={url.database or ''};"
                f"UID={url.username or ''};PWD={url.password or ''};"
            )
            table = sheet.ListObjects.Add(0, connection_string, None, 1, sheet.Range("A1"))
            table.QueryTable.CommandType = 2  # xlCmdSql
            table.QueryTable.CommandText = (
                "SELECT id, customer, total, status FROM demo_orders ORDER BY id"
            )
            # Excel strips PWD= from the connection string on save unless this is
            # set — and a passwordless refresh then fails *silently* inside
            # RefreshAll, which looks like a successful refresh that changed nothing.
            table.QueryTable.SavePassword = True
            built = f"live ODBC connection via '{driver}'"
        else:
            workbook.Queries.Add(
                "Orders",
                'let Source = #table({"customer","total","status"}, '
                '{{"placeholder", 0, "swap this query for one against demo_orders"}}) in Source',
            )
            table = sheet.ListObjects.Add(
                0,  # xlSrcExternal
                'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;'
                'Location=Orders;Extended Properties=""',
                None,
                1,  # xlYes: first row is headers
                sheet.Range("A1"),
            )
            table.QueryTable.CommandType = 2  # xlCmdSql
            table.QueryTable.CommandText = "SELECT * FROM [Orders]"
            built = "placeholder Power Query (no MySQL ODBC driver installed)"
        table.QueryTable.BackgroundQuery = False
        table.QueryTable.Refresh(False)
        workbook.Connections(1).Name = "MySQL - demo_orders" if driver else "Query - Orders"
        workbook.SaveAs(str(path), FileFormat=51)  # xlOpenXMLWorkbook (.xlsx)
    finally:
        if workbook is not None:
            workbook.Close(False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()
    return built


def upsert_published(db: Database, definition: ProcessDefinition) -> ProcessDefinition:
    """Match by name and overwrite: re-seeding doubles as a reset of edited demos.

    Publishing bumps the version rather than duplicating the process, and a
    renamed demo is left alone as the user's own fork.
    """
    existing = {p["name"]: p["id"] for p in db.list_processes()}
    if definition.name in existing:
        definition.id = existing[definition.name]
    db.save_process(definition)
    return db.publish_process(definition.id)


async def run_once(db: Database, process_id: str) -> None:
    registry = default_registry()
    engine = Engine(
        registry,
        definition_resolver=db.get_version,
        secrets=SecretsManager(db).view(),
    )
    instance = await engine.run(db.get_version(process_id))
    db.save_instance(instance)
    print(f"\nrun {instance.id}: {instance.status}")
    for step_run in instance.step_runs:
        took = f"{step_run.duration_ms:.1f}ms" if step_run.duration_ms is not None else "-"
        print(f"  {step_run.step_name:<15} {step_run.status:<10} {took:>9}")
        if step_run.error:
            print(f"    error: {step_run.error}")


def main() -> None:
    mysql_url = os.environ.get("DEMO_MYSQL_URL", DEFAULT_MYSQL_URL)
    workbook = os.environ.get("DEMO_WORKBOOK", str((Path("workdir") / "demo-orders.xlsx").resolve()))

    rows = seed_orders(mysql_url)
    print(f"demo_orders reset with {rows} rows (all status 'new')")

    if "--make-workbook" in sys.argv:
        built = make_workbook(workbook, mysql_url)
        print(f"workbook created at {workbook} ({built})")

    db = Database()  # honours PROCESS_ENGINE_DB_URL, same as the API
    SecretsManager(db).set(SECRET_NAME, make_url(mysql_url).password or "")
    print(f"secret '{SECRET_NAME}' stored")

    conn = mysql_step_connection(mysql_url)
    sub = upsert_published(db, build_subprocess(conn))
    parent = upsert_published(db, build_parent(conn, sub.id, workbook))
    print(f"published '{sub.name}' v{sub.version} ({sub.id})")
    print(f"published '{parent.name}' v{parent.version} ({parent.id})")

    print(
        f"""
Next steps:
  1. python -m process_engine_api          (from this same directory/env)
  2. Open the designer -> Demos -> "{parent.name}" and press Run.
     The Excel step needs Windows: on a split deployment the run has to be
     claimed by a Windows engine (python -m process_engine), not by a Linux API.
  3. Workbook: --make-workbook builds one at
       {workbook}
     with a live ODBC connection to demo_orders when a MySQL ODBC driver is
     installed (placeholder query otherwise). Rolling your own Power Query
     workbook instead? Its first refresh must be done by hand in Excel (Data ->
     Refresh All -> Connect) — Power Query stores credentials per Windows user
     and refuses them embedded in connection strings; after that one grant the
     engine refreshes it unattended. Without any workbook, the refresh step
     routes its failure to the warning log and the run still completes.

Re-run this script any time to reset: every order goes back to status 'new',
and both demo processes are restored to their original definitions (edits made
to them in the designer are overwritten; renamed copies are left alone).
"""
    )

    if "--run" in sys.argv:
        asyncio.run(run_once(db, parent.id))


if __name__ == "__main__":
    main()
