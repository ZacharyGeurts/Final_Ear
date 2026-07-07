"""Hostess 7 Military EOL hearing — ear lane wired to sovereign vision inspect."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_SG = _ROOT.parent
_ENGINE = "Hostess7/MilitaryEOL/Ear"
_SCHEMA = "zocr-military-eol-ear/v1"


def _eye_military():
    eye = _SG / "Final_Eye" / "zocr_military_eol.py"
    if not eye.is_file():
        return None
    spec = importlib.util.spec_from_file_location("zocr_military_eol_ear", eye)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    if str(eye.parent) not in sys.path:
        sys.path.insert(0, str(eye.parent))
    spec.loader.exec_module(mod)
    return mod


def military_eol_ready() -> bool:
    mod = _eye_military()
    return bool(mod and mod.military_eol_ready())


def hear_glyph(path: Path | str) -> dict[str, Any]:
    mod = _eye_military()
    if not mod:
        return {"ok": False, "error": "final_eye_military_missing", "engine": _ENGINE}
    inspect = mod.inspect_image(path)
    return {
        "ok": bool(inspect.get("ok")),
        "schema": _SCHEMA,
        "engine": _ENGINE,
        "sense": "ear",
        "cross_wire": "Final_Eye.inspect_image",
        "inspect": inspect,
        "heard": inspect.get("neural", {}).get("top_label") or "silence",
    }


def military_ocr_image(path: Path | str, **kwargs: Any) -> str:
    row = hear_glyph(path)
    neural = (row.get("inspect") or {}).get("neural") or {}
    label = neural.get("top_label") or "glyph"
    return f"ear:{label}" if row.get("ok") else ""