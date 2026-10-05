# Branch `NO_GPU` — computers without a usable GPU

Default profile `no-gpu`: sets Qt's software renderer (`QT_OPENGL=software`, `QT_QUICK_BACKEND=software`, software GL for XCB) before the window is created. Use it on virtual machines, remote desktops and old graphics drivers.

Built into OS-specific files by `.github/workflows/build-all.yml` (Actions → run → Artifacts).
The main line of development is `brok-migration`; this branch is kept in sync by merging it.
