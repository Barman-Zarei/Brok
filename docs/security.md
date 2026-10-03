# Security model

| Tool | Risk | Confirmation |
|---|---|---|
| read/list/search, git status/diff/log/branch, inspect | LOW | none |
| write/create/move, git checkout/stash, run_tests/linter/formatter, fetch_url | MEDIUM | configurable |
| delete_file, git_commit, github_create_* | HIGH | required |
| git_push, sudo/system/remote-changing commands | CRITICAL | always (no setting can skip) |
| dangerous commands (`rm -rf /`, mkfs, dd to disk, curl\|sh, credential files, fork bomb…) | BLOCKED | refused before any prompt |

- Workspace jail: paths are resolved with `realpath`; escaping the project (`..`, absolute, symlink) is refused.
- Secrets files (`.env`, `*.pem`, `*.key`, ssh keys) cannot be read or written by the agent; `git_commit` never stages them.
- Commands run without a shell (argv), with API-key/token env vars scrubbed, with a timeout and output cap.
- Git refs are validated (no option injection). `fetch_url` rejects non-http(s)/private/loopback addresses (SSRF).
- Keys come from env vars or the OS keyring only; never from config, logs or memory (`redact()` masks them;
  `MemoryStore` refuses text that looks like a secret).
- Plugins cannot lower risk: their tools are floored at MEDIUM/configurable.
- `health` findings are heuristic, **not** a security audit.

Limits you should know: command classification is pattern-based (it can be fooled by obfuscation, which is why
anything unlisted asks first); there is no OS-level sandbox/container yet.
