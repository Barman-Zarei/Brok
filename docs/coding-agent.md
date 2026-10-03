# Coding agent

Tools: read_file, write_file, create_file, move_file, delete_file, list_directory, search_text, search_code,
inspect_project, git_status/diff/log/branch/checkout/stash/commit/push, run_command, run_tests, run_linter,
run_formatter (+ optional github_*, web_search, fetch_url, calculate, notes).

Loop (`agent/loop.py`): model turn → tool calls → results → repeat → summary. Hard limits: `max_iterations`,
`timeout_seconds`, `token_budget` (≈chars/4), `tool_budget`, plus cancellation. Status is returned
(`done|max_iterations|timeout|token_budget|tool_budget|cancelled|error`).

Diff-first: `write_file`/`create_file` show a unified BEFORE/AFTER diff in the approval dialog (Apply / Reject;
Reject is the default). Retry = ask again. `security.auto_approve_medium=true` applies file edits without asking
(HIGH/CRITICAL tools still always ask).

Project understanding: `detect_project` (Python, Dart/Flutter, Node/React/Next, Java, C++, C#, HTML, Rust) and
`ProjectIndex` (symbols/imports/TODOs; `retrieve()` returns only relevant snippets, never the whole repo).
Index is lexical today; `ProjectIndex.retrieve` is the seam for future vector search.

CLI: `brok-agent ask|code|fix|debug|learn|health|doctor|privacy|memory`. GUI: right-click → *Coding Workspace…*.
