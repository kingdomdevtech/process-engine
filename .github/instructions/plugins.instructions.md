---
name: Plugin authoring
description: The Plugin contract, config-form UI hints, the filesystem sandbox and the registration checklist
applyTo: "src/process_engine/plugins/**/*.py,plugins/**/*.py,examples/**/plugins/**/*.py,src/process_engine/plugin.py,src/process_engine/ui.py"
---

# Writing a Plugin

A Plugin is three things: a `manifest` (identity + input/output ports), a `Config` (pydantic
model), and `async execute(ctx) -> PluginResult | dict | None`.

```python
class ThingConfig(BaseModel):
    target: str = Field(default="", title="Folder", json_schema_extra=ui(group="Source", widget="path"))

class ThingPlugin(Plugin):
    """One line an editor would understand, shown in the palette."""
    manifest = PluginManifest(key="thing", name="Thing", description="…", category="files")
    Config = ThingConfig

    async def execute(self, ctx: PluginContext) -> PluginResult:
        ...
```

- **Failure is a raise.** The engine owns retries, timeout and error routing. Don't catch an
  exception just to return `{"ok": False}` — a failed step routes `{error, step}` to its
  `error` port if connected, otherwise fails the run.
- **Blocking work still goes through `await asyncio.to_thread(...)`** — each plugin attempt
  runs on its own worker thread, so a sync client (COM, PyMySQL, smtplib, boto3) no longer
  stalls the engine, but it does block that thread's event loop, and a blocked loop cannot
  enforce the step's `timeout_seconds`. See `excel_refresh.py` and `send_email.py`.
- **Branch by emitting on a named port**: `PluginResult.on("true", data)`, with the ports
  declared in `manifest.outputs=[Port(name="true"), Port(name="false")]`.
- **Optional dependencies import lazily**, inside `execute` or a helper, so the plugin still
  registers on a machine without boto3/pywin32/PyMySQL installed.
- **Shared behaviour lives in a `_`-prefixed module.** `_download.py` owns `target_path`
  resolution and the `.part`-then-rename discipline so `s3_download` and
  `azure_blob_download` cannot drift; `_mysql.py` owns connection config. Two plugins doing
  the same thing differently is the bug.

## Paths — always sandboxed

Step config is data an editor authors, so any path must be resolved with `workspace.resolve()`.
Relative paths join onto `PROCESS_ENGINE_WORK_DIR` (default `./workdir`); absolute paths must
already be inside it; containment is checked *after* symlink/junction resolution.
`PathNotAllowed` (a `ValueError`) fails the step. A plugin that walks a tree must re-check
every entry it discovers — see `file_purge._matches`.

## The Config is a UI contract

Step forms are aimed at people who don't know what a header or a bind parameter is. The
designer builds every form from `Config.model_json_schema()` and ships **no per-plugin
frontend code**, so anything about *how* a field should be edited travels inside the schema
via `ui()` from `process_engine.ui`:

- `group="…"` splits the form into sections; `advanced=True` folds a field into that section's
  collapsed disclosure — use it sparingly, only for genuine expert knobs.
- `show_if=when("auth", "oauth2")` hides a field until it applies. It is presentation only:
  a hidden field keeps its value and the plugin still validates what it needs.
- `labels={...}` gives enum options human wording; `secret=True` offers the stored secrets by
  name so `{{ secrets.x }}` never has to be typed; `unit=`, `placeholder=`, `add_label=`,
  `key_label=`/`value_label=` refine the control.
- `widget=` overrides the type-derived control and is validated against `ui.WIDGETS` at import
  time — a typo raises there, not silently in the browser. Types already imply the right
  control: `list[str]` is a chip editor, `dict[str, X]` a name/value editor.
- `Field(examples=[...])` drives both the placeholder and the *Show example* JSON. Steer that
  through examples rather than special-casing the plugin in the designer.
- `format: "html"` on a string renders the HTML editor (see `send_email_ses.body_html`).

Prefer a field that needs no explanation: one `encryption` dropdown beats `use_tls` +
`use_ssl`; `action: statement | procedure` beats "leave `statement` empty to mean procedure".

## Checklist for a new built-in

1. Module in `src/process_engine/plugins/`, with a unique `manifest.key` and a `category` that
   matches an existing one where possible (the designer tints by category).
2. Imported **and** listed in `BUILTIN_PLUGINS` in `src/process_engine/plugins/__init__.py` —
   both, or it won't register.
3. Any new optional dependency added as an extra in `pyproject.toml`.
4. Tests: behaviour in `tests/`, plus `tests/test_config_forms.py` covers the schema (it fails
   on a `show_if` naming a missing field, wording for a renamed option, a list widget on a
   dict, or a required field hidden by default).
5. `docs/runbook.html` updated if it has operational constraints (credentials, COM, network).
6. Restart the API — discovery runs at startup only.

Third-party plugins do **not** go in `src/process_engine/plugins/`. Ship them as drop-in `.py`
files in `./plugins` (or `PROCESS_ENGINE_PLUGINS_DIR`), or as a pip package with an entry point
in group `process_engine.plugins` — template at `examples/hello-plugin`.
