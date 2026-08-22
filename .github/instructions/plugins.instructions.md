---
name: Plugin authoring
description: The Plugin contract, config-form UI hints, the filesystem sandbox and the registration checklist
applyTo: "packages/process_engine_core/plugins/**/*.py,packages/process_engine/plugins/**/*.py,examples/**/plugins/**/*.py,packages/process_engine_core/plugin.py,packages/process_engine_core/ui.py"
---

# Writing a Plugin

A Plugin is three things: a `manifest` (identity + input/output ports), a `Config` (pydantic
model), and `async execute(ctx) -> PluginResult | dict | None`. The first two are what a step
*is*; the third is what it *does* and only an engine host ever calls it — so the class is split
across two modules, along the same line the deployment is split on.

```python
# packages/process_engine_core/plugins/thing.py — the form half, installed everywhere
class ThingConfig(BaseModel):
    target: str = Field(default="", title="Folder", json_schema_extra=ui(group="Source", widget="path"))

class ThingSpec(PluginSpec):
    """One line an editor would understand, shown in the palette."""
    manifest = PluginManifest(key="thing", name="Thing", description="…", category="files")
    Config = ThingConfig
```

```python
# packages/process_engine/plugins/thing.py — the behaviour, installed on engine hosts only
from process_engine_core.plugin import Plugin, PluginContext, PluginResult
from process_engine_core.plugins.thing import ThingConfig, ThingSpec

class ThingPlugin(ThingSpec, Plugin):
    async def execute(self, ctx: PluginContext) -> PluginResult:
        ...
```

The runnable class *is* the spec plus behaviour, so the two halves cannot disagree about the
key or what the step accepts. Put the editor-facing docstring on the spec — that is the module
the designer's palette copy comes from — and the operator-facing detail (what it touches on
disk, which credential it needs) on the implementation.

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
via `ui()` from `process_engine_core.ui`:

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

1. Spec module in `packages/process_engine_core/plugins/`, with a unique `manifest.key` and a
   `category` that matches an existing one where possible (the designer tints by category).
2. Imported **and** listed in `BUILTIN_SPECS` in that package's `plugins/__init__.py` — both,
   or it won't register.
3. Implementation module in `packages/process_engine/plugins/`, imported **and** listed in
   `BUILTIN_PLUGINS` in *that* package's `plugins/__init__.py`. Two modules, two list entries.
4. Any new optional dependency added as an extra in the **engine** package's `pyproject.toml`
   (`packages/process_engine/`) — the SDK is only needed where `execute` runs. Core stays
   dependency-light: the API host installs it and must not have to pull boto3 in.
5. Tests: behaviour in `tests/`, plus `tests/test_config_forms.py` covers the schema (it fails
   on a `show_if` naming a missing field, wording for a renamed option, a list widget on a
   dict, or a required field hidden by default). `test_both_tiers_advertise_exactly_the_same_plugins`
   in `tests/test_registry.py` fails if a spec has no implementation or vice versa.
6. `docs/runbook.html` updated if it has operational constraints (credentials, COM, network).
7. Restart the API **and every engine host** — discovery runs at startup only, and the palette
   must only offer what an engine can actually execute.

That is the whole story: **a new plugin lives in this repository.** There is deliberately no
drop-in folder — a step runs on whichever engine claims its job, so it cannot depend on a loose
`.py` file somebody dropped on one of them. The one alternative is a pip package with an entry
point in group `process_engine.plugins` (template at `examples/hello-plugin`), which has to be
installed on every host that executes.
