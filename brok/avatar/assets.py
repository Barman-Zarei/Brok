"""Avatar packs: a folder of per-state GIFs + pack.json, and a legacy single-GIF zip for the existing char menu."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .renderer import render_state
from .states import AvatarState


def _save_gif(frames, path: Path, ms: int = 140) -> None:
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0, disposal=2, transparency=0)


def build_pack_dir(out: Path, theme: str = "cyan") -> Path:
    """Write ``<out>/pack.json`` and one GIF per AvatarState. Third-party packs use the same layout."""
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for st in AvatarState:
        f = out / f"{st.value}.gif"
        _save_gif(render_state(st, theme), f)
        manifest[st.value] = f.name
    (out / "pack.json").write_text(json.dumps({"name": "robot", "theme": theme, "states": manifest}, indent=2))
    return out


def build_legacy_zip(path: Path, theme: str = "cyan") -> Path:
    """``robot.zip`` (animation.gif + static.png) in the char format the existing menu already loads."""
    frames = render_state(AvatarState.IDLE, theme)
    tmp = path.parent / "_tmp_robot"
    tmp.mkdir(parents=True, exist_ok=True)
    _save_gif(frames, tmp / "animation.gif")
    frames[0].save(tmp / "static.png")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp / "animation.gif", "animation.gif")
        z.write(tmp / "static.png", "static.png")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return path


def load_pack(folder: Path) -> dict[AvatarState, Path] | None:
    """Validate a pack dir; returns {state: gif path} or None if invalid (falls back to the built-in robot)."""
    try:
        data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        res = {AvatarState(k): (folder / v) for k, v in data["states"].items()}
    except (OSError, ValueError, KeyError):
        return None
    return res if all(p.is_file() and p.resolve().parent == folder.resolve() for p in res.values()) else None
