---
name: new-plugin
description: Scaffold a built-in Plugin end to end — module, registration, config form, tests, docs
agent: agent
argument-hint: what the plugin should do (e.g. "post a message to a Teams webhook")
---

Add a new built-in Plugin: **${input:purpose:What should the plugin do?}**

Follow `.github/instructions/plugins.instructions.md`. Before writing anything, read
`src/process_engine/plugin.py` and the closest existing plugin — `http_request.py` for a network
call, `file_purge.py` for filesystem work, `mysql_query.py` for a blocking client, `condition.py`
for port branching.

Do all of this, not just the module:

1. **Module** in `src/process_engine/plugins/`. Unique `manifest.key`, a `category` matching an
   existing one where possible, ports declared in the manifest, and a class docstring an editor
   would understand.
2. **`Config`** designed as a UI contract, not a data one: `ui()` groups, `show_if=when(...)` for
   modal fields, `labels=` for enum wording, `secret=True` for credentials, `Field(examples=[...])`
   so *Show example* and the placeholders are useful. Prefer one field that needs no explanation
   over two that need a paragraph.
3. **`execute`** raising on failure (the engine owns retries, timeout and error routing), wrapping
   any blocking call in `await asyncio.to_thread(...)`, resolving every path through
   `workspace.resolve()`, and importing optional dependencies lazily so the plugin still registers
   without them.
4. **Register** it: import *and* add to `BUILTIN_PLUGINS` in `src/process_engine/plugins/__init__.py`.
   Both, or it never appears.
5. **Dependencies**: any new package becomes an extra in `pyproject.toml`.
6. **Tests**: behaviour in `tests/`, mocking only at the outside edge, plus confirm
   `pytest tests/test_config_forms.py` passes for the new schema.
7. **Docs**: add it to `docs/runbook.html` if it has credentials, network or platform constraints.

Then run `pytest` and report what passed. Say explicitly that the API must be restarted before
the plugin appears — discovery runs at startup only. Write no designer code: if the form needs
something the schema can't express, say so rather than special-casing the plugin in the frontend.
