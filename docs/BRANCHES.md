# Branches

`brok-migration` is the main line. Every other branch is a variant that shares its code; fixes are merged from
`brok-migration` into them. Each branch has `.github/workflows/build-all.yml` (or its own mobile workflow) that turns
the branch into OS-specific files on GitHub Actions: **Actions → the run → Artifacts**.

| Branch | What it is | Python | Verified here |
|---|---|---|---|
| `brok-migration` | Main version | 3.10+ | tests on 3.12; CI 3.10–3.13 |
| `PYTHON38` | Python 3.8 compatibility | 3.8+ | tests on CPython 3.8.20 |
| `LEGACY` | Older OS versions + pinned old dependencies | 3.9 | tests on CPython 3.9.25 |
| `WIN7` | Windows 7 via Qt 5.15 / PySide2 | 3.8–3.10 | tests + frozen start on Linux; **not on Windows 7** |
| `LOW-END` | Weak PCs: ~15 fps avatar, no update check | 3.8+ | tests |
| `OFFLINE` | Ollama only, no cloud AI, no update check | 3.8+ | tests (incl. config override) |
| `LITE` | `pyside6-essentials` instead of full PySide6 | 3.8+ | tests; install 233 MB vs 650 MB |
| `NO_GPU` | Qt software rendering | 3.8+ | tests (env vars asserted) |
| `EXPERIMENTAL` | Unstable work, DEBUG logging | 3.8+ | tests |
| `ANDROID` | APK via `pyside6-android-deploy` | 3.10+ | entry point only; workflow never run |
| `IOS` | Xcode project via Qt 6.12 tooling | 3.10+ | entry point only; workflow never run |

Runtime profile = one line (`DEFAULT_PROFILE` in `brok/profile.py`); override anywhere with `BROK_PROFILE=<name>`
(`standard`, `lite`, `low-end`, `no-gpu`, `offline`, `experimental`).

## Which files each branch builds (build-all.yml)
Windows `.exe`, macOS `.app` zip (Apple Silicon + Intel), Linux binary `.tar.gz`. `WIN7` and `PYTHON38` skip the
Apple Silicon job (no Python 3.8 there). Not run on GitHub yet: Windows/macOS jobs are unverified until they run.
`ANDROID`/`IOS` use `build-android.yml` / `build-ios.yml` (manual runs, experimental, need extra inputs).
PyPI publishing and release workflows exist only on `brok-migration`.
