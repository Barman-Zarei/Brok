# Development

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[calendar,secure]" pytest pytest-forked pytest-timeout ruff
QT_QPA_PLATFORM=offscreen python -m pytest -q --forked --timeout=60 --timeout-method=thread
ruff check .
```
Python 3.8+ rules: keep `from __future__ import annotations`; no `match`, `str.removeprefix`, `ast.unparse`,
runtime `list[str]`/`X | Y`. Providers are tested with a fake transport (no keys/network needed).
