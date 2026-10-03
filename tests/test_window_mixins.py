"""BrokWindow keeps its public surface after being split into mixins."""

from brok import main
from brok.window_dialogs import DialogsMixin
from brok.window_geometry import GeometryMixin
from brok.window_update import UpdateMixin

NAMES = [
    "open_workspace", "open_privacy", "open_settings", "open_reminder", "open_update", "download_update",
    "load_position", "reset_position", "clamp_to_screens", "place_beside_cat", "on_update_checked",
]  # fmt: skip


def test_methods_still_reachable_on_window():
    for n in NAMES:
        assert callable(getattr(main.BrokWindow, n)), n


def test_mixins_are_in_the_mro():
    assert {DialogsMixin, UpdateMixin, GeometryMixin} <= set(main.BrokWindow.__mro__)


def test_legacy_alias_kept():
    assert main.PixelCatWindow is main.BrokWindow
