"""Field manuals — AI-accessible corpus for vision, audio, and per-function doctrine."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
INDEX_PATH = _ROOT / "data" / "field-manual-index.json"


def _sg_root() -> Path:
    return Path(os.environ.get("SG_ROOT", _ROOT.parent))


def _resolve_root(env_key: str, *candidates: Path) -> Path | None:
    env = os.environ.get(env_key, "").strip()
    if env and Path(env).is_dir():
        return Path(env)
    for c in candidates:
        if c.is_dir():
            return c
    return None


def load_index() -> dict[str, Any]:
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "zocr-field-manual-index/v1", "senses": {}, "functions": {}}


def _read_manual_file(root: Path, rel: str) -> dict[str, Any] | None:
    p = root / rel
    if not p.is_file():
        return None
    try:
        if p.suffix == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        return {"path": str(p), "size": p.stat().st_size, "format": p.suffix.lstrip(".")}
    except (OSError, json.JSONDecodeError):
        return None


def field_manual_for_sense(sense: str) -> dict[str, Any]:
    idx = load_index()
    senses = idx.get("senses") or {}
    sg = _sg_root()
    if sense == "all":
        out = {}
        for sid, meta in senses.items():
            out[sid] = field_manual_for_sense(sid)
        return {"ok": True, "schema": "zocr-field-manual-all/v1", "senses": out}

    meta = senses.get(sense)
    if not meta:
        return {"ok": False, "error": "unknown_sense", "available": list(senses.keys())}

    if sense == "vision":
        root = _resolve_root("FINAL_EYE_ROOT", sg / "Final_Eye", sg / "ZOCR")
    else:
        root = _resolve_root("FINAL_EAR_ROOT", _ROOT, sg / "Final_Ear")

    if not root:
        return {"ok": False, "error": "root_missing", "sense": sense}

    manual_json = meta.get("field_manual_json")
    manual_doc = _read_manual_file(root, manual_json) if manual_json else None
    textbook = root / (meta.get("textbook_html") or "docs/index.html")
    chapters: list[dict[str, Any]] = []
    ch_dir = root / "docs" / "chapters"
    if ch_dir.is_dir():
        for ch in sorted(ch_dir.glob("*.html")):
            chapters.append({"file": str(ch.relative_to(root)), "title": ch.stem})

    return {
        "ok": True,
        "schema": "zocr-field-manual/v1",
        "sense": sense,
        "product": meta.get("product"),
        "title": meta.get("title"),
        "version": meta.get("version"),
        "creed": meta.get("creed"),
        "root": str(root),
        "textbook": str(textbook) if textbook.is_file() else None,
        "manual": manual_doc,
        "chapters": chapters,
        "api_queen": meta.get("api_queen"),
        "functions": {
            k: v for k, v in (idx.get("functions") or {}).items()
            if v.get("sense") == sense
        },
    }


def field_manual_for_function(function_id: str) -> dict[str, Any]:
    idx = load_index()
    fn = (idx.get("functions") or {}).get(function_id)
    if not fn:
        return {"ok": False, "error": "unknown_function", "available": list((idx.get("functions") or {}).keys())}
    sense = fn.get("sense", "audio")
    root_env = fn.get("root", "FINAL_EAR_ROOT")
    sg = _sg_root()
    if sense == "vision":
        root = _resolve_root(root_env, sg / "Final_Eye")
    elif fn.get("root") == "QUEEN_ROOT":
        root = _resolve_root("QUEEN_ROOT", sg / "NewLatest" / "Queen")
    else:
        root = _resolve_root(root_env, _ROOT)
    manual = _read_manual_file(root, fn["manual"]) if root and fn.get("manual") else None
    return {
        "ok": True,
        "schema": "zocr-field-manual-function/v1",
        "function_id": function_id,
        "sense": sense,
        "module": fn.get("module"),
        "manual": manual,
        "root": str(root) if root else None,
    }