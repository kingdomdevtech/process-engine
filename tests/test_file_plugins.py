import logging
import os
import time
from datetime import datetime, timezone
from importlib.util import find_spec
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from process_engine_core import workspace
from process_engine.engine import Engine
from process_engine_core.models import Connection, ProcessDefinition, RunStatus, Step
from process_engine_core.plugin import PluginContext
from process_engine.plugins.azure_blob_download import AzureBlobDownloadPlugin, _account_url
from process_engine.plugins.file_purge import FilePurgePlugin
from process_engine.plugins.s3_download import S3DownloadPlugin
from process_engine.registry import default_registry

DAY = 86_400


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    """Point the sandbox at a scratch folder for the duration of a test."""
    monkeypatch.setenv(workspace.WORK_DIR_ENV, str(tmp_path))
    return tmp_path.resolve()


async def run(plugin_cls, config, **ctx_kwargs) -> dict:
    ctx = PluginContext(
        run_id="r1",
        step_id="s1",
        step_name="step",
        config=plugin_cls.Config(**config),
        input=None,
        all_inputs={},
        variables={},
        logger=logging.getLogger("test"),
        **ctx_kwargs,
    )
    result = await plugin_cls().execute(ctx)
    return result.outputs["main"]


def write(path, text="x", *, age_days=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if age_days:
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))
    return path


# -- the sandbox ---------------------------------------------------------------


def test_relative_paths_resolve_inside_the_working_directory(work_dir):
    assert workspace.resolve("downloads/report.csv") == work_dir / "downloads" / "report.csv"
    assert workspace.resolve("") == work_dir
    assert workspace.relative(work_dir / "a" / "b.csv") == "a/b.csv"


def test_traversal_and_outside_absolute_paths_are_rejected(work_dir):
    for attempt in ("../escape.csv", "a/../../escape.csv", str(work_dir.parent / "escape.csv")):
        with pytest.raises(workspace.PathNotAllowed):
            workspace.resolve(attempt)


def test_a_critical_system_path_is_rejected(work_dir):
    critical = r"C:\Windows\System32\drivers\etc\hosts" if os.name == "nt" else "/etc/passwd"
    with pytest.raises(workspace.PathNotAllowed, match="outside the working directory"):
        workspace.resolve(critical)


def test_absolute_paths_inside_the_working_directory_are_allowed(work_dir):
    assert workspace.resolve(str(work_dir / "reports" / "q3.xlsx")) == work_dir / "reports" / "q3.xlsx"


def test_must_exist_reports_a_missing_path(work_dir):
    with pytest.raises(FileNotFoundError):
        workspace.resolve("nope", must_exist=True)


def test_describe_reports_the_configured_root(work_dir):
    info = workspace.describe()
    assert info == {
        "path": str(work_dir),
        "env_var": "PROCESS_ENGINE_WORK_DIR",
        "configured": True,
        "exists": True,
        "writable": True,
    }


# -- s3_download ---------------------------------------------------------------


class FakeS3Error(Exception):
    """Shaped like botocore's ClientError, which the plugin reads duck-typed."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.downloads: list[tuple[str, str, str]] = []

    def head_object(self, **kwargs):
        body = self.objects.get(kwargs["Key"])
        if body is None:
            raise FakeS3Error(404)
        return {
            "ContentLength": len(body),
            "ContentType": "text/csv",
            "ETag": '"abc123"',
            "VersionId": kwargs.get("VersionId", "v1"),
        }

    def download_file(self, Bucket, Key, Filename, ExtraArgs=None):  # noqa: N803 — boto3's signature
        self.downloads.append((Bucket, Key, Filename))
        with open(Filename, "wb") as handle:
            handle.write(self.objects[Key])


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3({"exports/orders.csv": b"id,total\n1,10\n"})
    monkeypatch.setattr(S3DownloadPlugin, "_client", staticmethod(lambda cfg: client))
    return client


async def test_download_saves_under_the_object_name_by_default(work_dir, fake_s3):
    output = await run(S3DownloadPlugin, {"bucket": "b", "key": "exports/orders.csv"})

    assert (work_dir / "orders.csv").read_text() == "id,total\n1,10\n"
    assert output["path"] == str(work_dir / "orders.csv")  # absolute: feeds attachments
    assert output["relative_path"] == "orders.csv"
    assert output["size_bytes"] == 14
    assert output["content_type"] == "text/csv"
    assert output["etag"] == "abc123"
    assert not list(work_dir.glob("*.part"))


async def test_download_into_a_folder_keeps_the_object_file_name(work_dir, fake_s3):
    output = await run(
        S3DownloadPlugin, {"bucket": "b", "key": "exports/orders.csv", "destination": "in/box/"}
    )
    assert output["relative_path"] == "in/box/orders.csv"
    assert (work_dir / "in" / "box" / "orders.csv").is_file()


async def test_download_renames_when_the_destination_is_a_file_path(work_dir, fake_s3):
    output = await run(
        S3DownloadPlugin,
        {"bucket": "b", "key": "exports/orders.csv", "destination": "archive/2026-08.csv"},
    )
    assert output["relative_path"] == "archive/2026-08.csv"


@pytest.mark.parametrize(
    "destination",
    ["../escape.csv", r"C:\Windows\Temp\escape.csv" if os.name == "nt" else "/tmp/escape.csv"],
)
async def test_download_refuses_a_destination_outside_the_working_directory(
    work_dir, fake_s3, destination
):
    with pytest.raises(workspace.PathNotAllowed):
        await run(
            S3DownloadPlugin,
            {"bucket": "b", "key": "exports/orders.csv", "destination": destination},
        )
    assert fake_s3.downloads == []  # rejected before any S3 call


async def test_download_honours_overwrite_false(work_dir, fake_s3):
    write(work_dir / "orders.csv", "keep me")
    with pytest.raises(FileExistsError):
        await run(
            S3DownloadPlugin,
            {"bucket": "b", "key": "exports/orders.csv", "overwrite": False},
        )
    assert (work_dir / "orders.csv").read_text() == "keep me"


async def test_missing_object_raises_a_clear_error(work_dir, fake_s3):
    with pytest.raises(FileNotFoundError, match="s3://b/exports/missing.csv"):
        await run(S3DownloadPlugin, {"bucket": "b", "key": "exports/missing.csv"})


async def test_a_failed_download_leaves_no_partial_file(work_dir, fake_s3, monkeypatch):
    def explode(Bucket, Key, Filename, ExtraArgs=None):  # noqa: N803
        open(Filename, "wb").write(b"half")
        raise TimeoutError("connection reset")

    monkeypatch.setattr(fake_s3, "download_file", explode)
    with pytest.raises(TimeoutError):
        await run(S3DownloadPlugin, {"bucket": "b", "key": "exports/orders.csv"})

    assert list(work_dir.iterdir()) == []


# -- azure_blob_download -------------------------------------------------------


class FakeAzureError(Exception):
    """Shaped like azure.core's HttpResponseError, which the plugin reads duck-typed."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class FakeBlobClient:
    def __init__(self, body: bytes | None, version_id: str):
        self.body = body
        self.version_id = version_id

    def get_blob_properties(self):
        if self.body is None:
            raise FakeAzureError(404)
        return SimpleNamespace(
            size=len(self.body),
            content_settings=SimpleNamespace(content_type="text/csv"),
            last_modified=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc),
            etag='"0x8DC123"',
            version_id=self.version_id,
        )

    def download_blob(self):
        return SimpleNamespace(readinto=lambda handle: handle.write(self.body))


class FakeBlobService:
    account_name = "mycompanyreports"

    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs
        self.requests: list[tuple[str, str, dict]] = []
        self.closed = False

    def get_blob_client(self, container, blob, **kwargs):
        self.requests.append((container, blob, kwargs))
        return FakeBlobClient(self.blobs.get(f"{container}/{blob}"), kwargs.get("version_id", ""))

    def close(self):
        self.closed = True


BLOB_CONFIG = {
    "container": "reports",
    "blob": "exports/orders.csv",
    "connect_using": "account_key",
    "account": "mycompanyreports",
    "account_key": "k",
}


@pytest.fixture
def fake_blobs(monkeypatch):
    service = FakeBlobService({"reports/exports/orders.csv": b"id,total\n1,10\n"})
    monkeypatch.setattr(AzureBlobDownloadPlugin, "_client", staticmethod(lambda cfg: service))
    return service


async def test_blob_download_saves_under_the_blob_name_by_default(work_dir, fake_blobs):
    output = await run(AzureBlobDownloadPlugin, BLOB_CONFIG)

    assert (work_dir / "orders.csv").read_text() == "id,total\n1,10\n"
    assert output["path"] == str(work_dir / "orders.csv")  # absolute: feeds attachments
    assert output["relative_path"] == "orders.csv"
    assert output["account"] == "mycompanyreports"
    assert output["size_bytes"] == 14
    assert output["content_type"] == "text/csv"
    assert output["last_modified"] == "2026-08-01T09:30:00+00:00"
    assert output["etag"] == "0x8DC123"
    assert not list(work_dir.glob("*.part"))
    assert fake_blobs.closed is True  # the SDK client holds a session


async def test_blob_download_into_a_folder_keeps_the_blob_file_name(work_dir, fake_blobs):
    output = await run(AzureBlobDownloadPlugin, {**BLOB_CONFIG, "destination": "in/box/"})
    assert output["relative_path"] == "in/box/orders.csv"
    assert (work_dir / "in" / "box" / "orders.csv").is_file()


async def test_blob_download_pins_a_version_when_asked(work_dir, fake_blobs):
    output = await run(AzureBlobDownloadPlugin, {**BLOB_CONFIG, "version_id": "2026-08-01T09:30:00.1Z"})
    assert fake_blobs.requests[0][2] == {"version_id": "2026-08-01T09:30:00.1Z"}
    assert output["version_id"] == "2026-08-01T09:30:00.1Z"

    await run(AzureBlobDownloadPlugin, BLOB_CONFIG)
    assert fake_blobs.requests[1][2] == {}  # unset means "current version", not version_id=""


@pytest.mark.parametrize(
    "destination",
    ["../escape.csv", r"C:\Windows\Temp\escape.csv" if os.name == "nt" else "/tmp/escape.csv"],
)
async def test_blob_download_refuses_a_destination_outside_the_working_directory(
    work_dir, fake_blobs, destination
):
    with pytest.raises(workspace.PathNotAllowed):
        await run(AzureBlobDownloadPlugin, {**BLOB_CONFIG, "destination": destination})
    assert fake_blobs.requests == []  # rejected before any Azure call


async def test_blob_download_honours_overwrite_false(work_dir, fake_blobs):
    write(work_dir / "orders.csv", "keep me")
    with pytest.raises(FileExistsError):
        await run(AzureBlobDownloadPlugin, {**BLOB_CONFIG, "overwrite": False})
    assert (work_dir / "orders.csv").read_text() == "keep me"


async def test_missing_blob_raises_a_clear_error(work_dir, fake_blobs):
    with pytest.raises(FileNotFoundError, match="reports/exports/missing.csv"):
        await run(AzureBlobDownloadPlugin, {**BLOB_CONFIG, "blob": "exports/missing.csv"})


async def test_a_failed_blob_download_leaves_no_partial_file(work_dir, fake_blobs, monkeypatch):
    def explode(self):
        return SimpleNamespace(readinto=_boom)

    def _boom(handle):
        handle.write(b"half")
        raise TimeoutError("connection reset")

    monkeypatch.setattr(FakeBlobClient, "download_blob", explode)
    with pytest.raises(TimeoutError):
        await run(AzureBlobDownloadPlugin, BLOB_CONFIG)

    assert list(work_dir.iterdir()) == []


@pytest.mark.parametrize(
    "config, missing",
    [
        ({"connect_using": "connection_string"}, "Connection string is required"),
        ({"connect_using": "account_key", "account": "a"}, "Account key is required"),
        ({"connect_using": "sas_token", "account": "a"}, "SAS token is required"),
        ({"connect_using": "account_key", "account_key": "k"}, "Storage account is required"),
        ({"connect_using": "azure_identity"}, "Storage account is required"),
    ],
)
def test_sign_in_settings_say_which_box_is_empty(config, missing):
    with pytest.raises(ValidationError, match=missing):
        AzureBlobDownloadPlugin.Config(container="c", blob="b.csv", **config)


def test_the_machine_identity_needs_no_secret():
    config = AzureBlobDownloadPlugin.Config(
        container="c", blob="b.csv", connect_using="azure_identity", account="mycompanyreports"
    )
    assert config.account_key == "" and config.connection_string == ""


@pytest.mark.parametrize(
    "account, url",
    [
        ("mycompanyreports", "https://mycompanyreports.blob.core.windows.net"),
        ("  mycompanyreports  ", "https://mycompanyreports.blob.core.windows.net"),
        ("https://mycompanyreports.blob.core.chinacloudapi.cn/", "https://mycompanyreports.blob.core.chinacloudapi.cn"),
    ],
)
def test_account_names_and_full_addresses_both_work(account, url):
    assert _account_url(account) == url


def azure_sdk_installed() -> bool:
    try:  # find_spec raises rather than returning None when the parent is absent
        return find_spec("azure.storage.blob") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(azure_sdk_installed(), reason="the azure extra is installed here")
def test_a_missing_sdk_names_the_extra_to_install():
    config = AzureBlobDownloadPlugin.Config(container="c", blob="b.csv", connection_string="cs")
    with pytest.raises(RuntimeError, match=r"process-engine\[azure\]"):
        AzureBlobDownloadPlugin._client(config)


ACCOUNT_KEY = "a2V5MTIzNDU2Nzg5MA=="  # any base64; nothing here reaches the network
CONNECTION_STRING = (
    "DefaultEndpointsProtocol=https;AccountName=mycompanyreports;"
    f"AccountKey={ACCOUNT_KEY};EndpointSuffix=core.windows.net"
)


@pytest.mark.skipif(not azure_sdk_installed(), reason="needs the azure extra")
@pytest.mark.parametrize(
    "credentials",
    [
        {"connect_using": "connection_string", "connection_string": CONNECTION_STRING},
        {"connect_using": "account_key", "account": "mycompanyreports", "account_key": ACCOUNT_KEY},
        {"connect_using": "sas_token", "account": "mycompanyreports", "sas_token": "?sv=2024-01-01&sig=x"},
        {"connect_using": "azure_identity", "account": "mycompanyreports"},
    ],
)
def test_the_real_sdk_accepts_every_sign_in(credentials):
    """Client construction is offline, so this catches SDK signature drift
    (a renamed keyword, a mode that stops taking a plain string) without a
    storage account to talk to."""
    service = AzureBlobDownloadPlugin._client(
        AzureBlobDownloadPlugin.Config(container="c", blob="b.csv", **credentials)
    )
    try:
        assert service.account_name == "mycompanyreports"
        blob = service.get_blob_client(container="c", blob="exports/orders.csv", version_id="v1")
        assert blob.version_id == "v1"
    finally:
        service.close()


# -- file_purge ----------------------------------------------------------------


async def test_deletes_only_files_past_the_cut_off(work_dir):
    write(work_dir / "old.csv", age_days=40)
    write(work_dir / "fresh.csv", age_days=2)

    output = await run(FilePurgePlugin, {"older_than_days": 30})

    assert output["deleted_count"] == 1
    assert output["kept_count"] == 1
    assert [entry["path"] for entry in output["deleted"]] == ["old.csv"]
    assert not (work_dir / "old.csv").exists()
    assert (work_dir / "fresh.csv").exists()


async def test_pattern_and_directory_scope_the_purge(work_dir):
    write(work_dir / "archive" / "a.csv", age_days=40)
    write(work_dir / "archive" / "a.log", age_days=40)
    write(work_dir / "other" / "b.csv", age_days=40)

    output = await run(
        FilePurgePlugin, {"directory": "archive", "pattern": "*.csv", "older_than_days": 30}
    )

    assert output["deleted_count"] == 1
    assert output["relative_directory"] == "archive"
    assert (work_dir / "archive" / "a.log").exists()
    assert (work_dir / "other" / "b.csv").exists()


async def test_recursive_reaches_sub_folders(work_dir):
    write(work_dir / "top.csv", age_days=40)
    write(work_dir / "nested" / "deep" / "inner.csv", age_days=40)

    shallow = await run(FilePurgePlugin, {"pattern": "*.csv", "older_than_days": 30})
    assert shallow["deleted_count"] == 1
    assert (work_dir / "nested" / "deep" / "inner.csv").exists()

    deep = await run(
        FilePurgePlugin, {"pattern": "*.csv", "older_than_days": 30, "recursive": True}
    )
    assert deep["deleted_count"] == 1
    assert not (work_dir / "nested" / "deep" / "inner.csv").exists()


async def test_dry_run_reports_without_deleting(work_dir):
    write(work_dir / "old.csv", "12345", age_days=40)

    output = await run(FilePurgePlugin, {"older_than_days": 30, "dry_run": True})

    assert output["dry_run"] is True
    assert output["deleted_count"] == 1
    assert output["freed_bytes"] == 5
    assert (work_dir / "old.csv").exists()


async def test_keep_latest_protects_the_newest_matches(work_dir):
    for index, age in enumerate([90, 60, 45, 40]):
        write(work_dir / f"backup{index}.zip", age_days=age)

    output = await run(FilePurgePlugin, {"older_than_days": 30, "keep_latest": 2})

    assert output["deleted_count"] == 2
    assert sorted(path.name for path in work_dir.iterdir()) == ["backup2.zip", "backup3.zip"]


async def test_zero_days_purges_everything_matching(work_dir):
    write(work_dir / "now.csv")
    output = await run(FilePurgePlugin, {"older_than_days": 0})
    assert output["deleted_count"] == 1


async def test_a_directory_outside_the_working_directory_is_refused(work_dir):
    outside = work_dir.parent / "critical"
    write(outside / "keep.csv", age_days=999)

    with pytest.raises(workspace.PathNotAllowed):
        await run(FilePurgePlugin, {"directory": "../critical", "older_than_days": 30})
    with pytest.raises(workspace.PathNotAllowed):
        await run(FilePurgePlugin, {"directory": str(outside), "older_than_days": 30})

    assert (outside / "keep.csv").exists()


async def test_a_traversal_pattern_is_refused(work_dir):
    with pytest.raises(ValueError, match="must not contain"):
        await run(FilePurgePlugin, {"pattern": "../*.csv", "older_than_days": 30})


async def test_a_link_out_of_the_sandbox_is_skipped_not_followed(work_dir):
    outside = work_dir.parent / "critical"
    target = write(outside / "hosts", age_days=999)
    link = work_dir / "hosts"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs privileges on this platform")

    output = await run(FilePurgePlugin, {"older_than_days": 30})

    assert output["deleted_count"] == 0
    assert output["skipped"] == ["hosts"]
    assert target.exists() and link.is_symlink()


async def test_empty_folders_are_pruned_on_request(work_dir):
    write(work_dir / "spent" / "old.csv", age_days=40)
    (work_dir / "keep").mkdir()
    write(work_dir / "keep" / "fresh.csv", age_days=1)

    output = await run(
        FilePurgePlugin,
        {"older_than_days": 30, "recursive": True, "delete_empty_directories": True},
    )

    assert output["removed_directories"] == ["spent"]
    assert not (work_dir / "spent").exists()
    assert (work_dir / "keep" / "fresh.csv").exists()
    assert work_dir.is_dir()  # the working directory itself is never removed


async def test_undeletable_files_fail_the_step_unless_ignored(work_dir, monkeypatch):
    write(work_dir / "locked.csv", age_days=40)

    def refuse(self):
        raise PermissionError("file is in use")

    monkeypatch.setattr("pathlib.Path.unlink", refuse)

    with pytest.raises(RuntimeError, match="could not be deleted"):
        await run(FilePurgePlugin, {"older_than_days": 30})

    output = await run(FilePurgePlugin, {"older_than_days": 30, "ignore_errors": True})
    assert output["deleted_count"] == 0
    assert output["errors"][0]["path"] == "locked.csv"


async def test_purge_runs_in_a_process_with_expressions(work_dir):
    write(work_dir / "exports" / "old.csv", age_days=40)
    write(work_dir / "exports" / "fresh.csv", age_days=1)
    definition = ProcessDefinition(
        steps=[
            Step(
                id="policy",
                plugin="transform",
                config={"values": {"folder": "exports", "days": 30}},
            ),
            Step(
                id="purge",
                plugin="file_purge",
                config={
                    "directory": "{{ steps.policy.output.folder }}",
                    "older_than_days": "{{ steps.policy.output.days }}",  # keeps its number type
                    "pattern": "*.csv",
                },
            ),
        ],
        connections=[Connection(source="policy", target="purge")],
    )
    registry = default_registry()
    instance = await Engine(registry).run(definition)

    assert instance.status == RunStatus.SUCCEEDED
    output = next(r for r in instance.step_runs if r.step_id == "purge").outputs["main"]
    assert output["deleted_count"] == 1
    assert (work_dir / "exports" / "fresh.csv").exists()


# -- registration --------------------------------------------------------------


def test_the_file_plugins_are_built_in():
    registry = default_registry()
    keys = {manifest["key"] for manifest in registry.manifests()}
    assert {"s3_download", "azure_blob_download", "file_purge"} <= keys
