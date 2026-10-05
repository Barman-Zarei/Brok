"""Android/iOS entry point: pyside6-android-deploy and the Xcode project expect a top-level ``main.py``."""

from brok.mobile import main

if __name__ == "__main__":
    raise SystemExit(main())
