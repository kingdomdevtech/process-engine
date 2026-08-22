---
name: new-plugin
description: Scaffold a built-in Plugin end to end — module, registration, config form, tests, docs
agent: agent
argument-hint: what the plugin should do (e.g. "post a message to a Teams webhook")
---

Add a new built-in Plugin: **${input:purpose:What should the plugin do?}**

Follow `.github/instructions/plugins.instructions.md`. Before writing anything, read
`packages/process_engine_core/plugin.py` and **both halves** of the closest existing plugin —
`http_request.py` for a network call, `file_purge.py` for filesystem work, `mysql_query.py` for
a blocking client, `condition.py` for port branching. Each of those exists twice: the spec in
`packages/process_engine_core/plugins/`, the implementation in `packages/process_engine/plugins/`.

A plugin is split along the deployment seam, so this is two modules and two list entries. Do
all of it, not just the code:

1. **Spec module** in `packages/process_engine_core/plugins/`. Unique `manifest.key`, a
   `category` matching an existing one where possible, ports declared in the manifest, and a
   class docstring an editor would understand — that half is installed on every host, including
   the one that only draws the form.
2. **`Config`** designed as a UI contract, not a data one: `ui()` groups, `show_if=when(...)` for
   modal fields, `labels=` for enum wording, `secret=True` for credentials, `Field(examples=[...])`
   so *Show example* and the placeholders are useful. Prefer one field that needs no explanation
   over two that need a paragraph. It lives beside the spec, in core.
3. **Implementation module** in `packages/process_engine/plugins/`, as
   `class XPlugin(XSpec, Plugin)` — subclass the spec rather than restating the manifest, so the
   halves cannot disagree. `execute` raises on failure (the engine owns retries, timeout and
   error routing), wraps any blocking call in `await asyncio.to_thread(...)`, resolves every path
   through `workspace.resolve()`, and imports optional dependencies lazily so the plugin still
   registers without them.
4. **Register both**: import *and* add the spec to `BUILTIN_SPECS` in
   `packages/process_engine_core/plugins/__init__.py`, and the implementation to
   `BUILTIN_PLUGINS` in `packages/process_engine/plugins/__init__.py`. All four, or the palette
   and the engines disagree about what exists.
5. **Dependencies**: any new package becomes an extra in the **engine** package's
   `pyproject.toml` — the SDK is only needed where `execute` runs, and core stays light because
   the API host installs it.
6. **Tests**: behaviour in `tests/`, mocking only at the outside edge, plus confirm
   `pytest tests/test_config_forms.py tests/test_registry.py` passes for the new schema and the
   new pair.
7. **Docs**: add it to `docs/runbook.html` if it has credentials, network or platform constraints.

Then run `pytest` and report what passed. Say explicitly that the API **and every engine host**
must be restarted before the plugin appears — discovery runs at startup only, and the palette must
not offer a step no engine can execute. Write no designer code: if the form needs something the
schema can't express, say so rather than special-casing the plugin in the frontend.
