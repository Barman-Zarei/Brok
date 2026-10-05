# Branch `LITE` — smaller install

Depends on `pyside6-essentials` instead of the full `pyside6` meta-package. Brok only imports QtCore, QtGui, QtWidgets and QtNetwork, all in Essentials, so nothing is lost; the Addons wheel (Multimedia, WebEngine, 3D, ...) is simply not installed. `openai` is not bundled in frozen builds.

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
