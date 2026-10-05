# Branch `LOW-END` — weak computers

Default profile `low-end`: avatar repaint at ~15 fps (instead of ~30) and no background update check. Smaller download: optional `openai` not bundled. Override at run time with `BROK_PROFILE=standard`.

The activity diary is unchanged (it is local-only and cheap).

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
