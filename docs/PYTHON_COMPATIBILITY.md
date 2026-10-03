# Python Compatibility

**Brok runs on Python 3.8+ (verified: full test suite, 408 tests, passes on 3.8.20 and 3.12.3).**

Earlier audit note claiming 3.8 was impossible was wrong; it was corrected after actually testing.

## Pinned constraints on Python 3.8
- PySide6: newest installable wheel on 3.8 is **6.6.3.1** (6.7+ ship cp39+ wheels). pip picks it automatically; Python 3.9+ gets the latest PySide6.
- Pillow: **10.4.x** is the last series supporting 3.8 (`pillow>=10.4`).
- Python 3.8 is end-of-life; it works, but gets no security fixes. Prefer 3.10+ when you can.

## Code changes made for 3.8
- `from __future__ import annotations` added to all modules (enables `X | None` annotations).
- `collections.abc.Callable[...]` evaluated at runtime (ai_char.py) replaced with a string alias.
- Tests: `str.removeprefix` and `ast.unparse` (3.9+) replaced with 3.8-safe equivalents.
- Rule for new code: no `match`, no runtime `list[str]`/`X | Y`, no `removeprefix`, no `zip(strict=)`, no `ast.unparse`.

## Future features
Planned AI features (Claude/Ollama over HTTP via stdlib or httpx) have no 3.8 blocker. Anything needing a newer-only dependency will be flagged and gated by a Python-version marker.

## Verified
Full test suite (425 tests) passes on CPython 3.8.20 and 3.12.3 (offscreen Qt). PySide6 6.6.3.1 / Pillow 10.4 are what pip resolves on 3.8.
