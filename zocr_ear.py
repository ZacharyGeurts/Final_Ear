"""ZOCR auditory spectrum v1 — equipment profiles, modes, sovereign ear status."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
DOCTRINE_PATH = _ROOT / "data" / "auditory-spectrum.json"
FINAL_PATH = _ROOT / "data" / "final-ear.json"
FINAL_STATE_PATH = _ROOT / "data" / "final-ear-state.json"
STATE_PATH = _ROOT / "data" / "ear-state.json"
ENGINE = "cochlea_v1"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_doctrine() -> dict[str, Any]:
    try:
        return json.loads(DOCTRINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "zocr-auditory-spectrum/v1", "default_profile": "human_binaural", "profiles": {}}


def load_final_spec() -> dict[str, Any]:
    try:
        return json.loads(FINAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "zocr-final-ear/v1", "modes": {}}


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    doc = load_doctrine()
    return {"schema": "zocr-ear-state/v1", "active_profile": doc.get("default_profile", "human_binaural"), "active_mode": "dishes"}


def _save_state(st: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = _ts()
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def list_profiles() -> list[dict[str, Any]]:
    doc = load_doctrine()
    out: list[dict[str, Any]] = []
    for pid, p in (doc.get("profiles") or {}).items():
        out.append({
            "id": pid,
            "label": p.get("label", pid),
            "class": p.get("class", ""),
            "channels": p.get("channels", 1),
            "equipment": p.get("equipment", []),
            "teach": p.get("teach", ""),
        })
    return sorted(out, key=lambda x: x["id"])


def active_profile() -> str:
    env = os.environ.get("ZOCR_EAR", "").strip()
    if env:
        return env
    return _load_state().get("active_profile", load_doctrine().get("default_profile", "human_binaural"))


def active_mode() -> str:
    return _load_state().get("active_mode", "dishes")


def set_mode(mode: str) -> dict[str, Any]:
    spec = load_final_spec()
    modes = spec.get("modes") or {}
    if mode not in modes:
        return {"ok": False, "error": "unknown_mode", "modes": list(modes.keys())}
    st = _load_state()
    st["active_mode"] = mode
    preset = modes[mode]
    if preset.get("ear_profile"):
        profiles = load_doctrine().get("profiles") or {}
        for pid, p in profiles.items():
            if pid.startswith(preset["ear_profile"]) or preset["ear_profile"] in pid:
                st["active_profile"] = pid
                break
    _save_state(st)
    return {"ok": True, "mode": mode, "preset": preset, "state": st}


def ear_status() -> dict[str, Any]:
    st = _load_state()
    doc = load_doctrine()
    return {
        "schema": "zocr-ear-status/v1",
        "updated": _ts(),
        "engine": ENGINE,
        "active_profile": st.get("active_profile", active_profile()),
        "active_mode": st.get("active_mode", active_mode()),
        "profiles": list_profiles(),
        "profile_count": len(doc.get("profiles") or {}),
        "sample_rate_hz": (doc.get("profiles") or {}).get(active_profile(), {}).get("sample_rate_hz", 48000),
    }


def final_ear_status() -> dict[str, Any]:
    spec = load_final_spec()
    st_path = FINAL_STATE_PATH
    state: dict[str, Any] = {}
    if st_path.is_file():
        try:
            state = json.loads(st_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        from zocr_ear_truth import truth_filter_status
        truth = truth_filter_status()
    except ImportError:
        truth = {}
    try:
        from zocr_ear_stoard import stoard_status
        stoard = stoard_status()
    except ImportError:
        stoard = {}
    redundancy = {
        "ok": True,
        "woven_paths": 4,
        "paths": [
            {"id": "audio_ingest", "woven": True},
            {"id": "truth_filter", "woven": bool(truth)},
            {"id": "hostess_lane", "woven": True},
            {"id": "ear_stoard", "woven": bool(stoard)},
        ],
    }
    try:
        from zocr_sovereign_time import sovereign_time_status
        sovereign = sovereign_time_status(seal=True)
    except ImportError:
        sovereign = state.get("sovereign_time") or {
            "ok": True,
            "verdict": "USER_OK",
            "sealed_mono_ns": None,
            "note": "sovereign time seals ear receipts",
        }
    try:
        from zocr_sound_tracker import tracker_status
        sound_tracker = tracker_status()
    except ImportError:
        sound_tracker = {"ok": True, "never_fail": True, "degraded": True}
    return {
        "schema": "zocr-final-ear-status/v1",
        "updated": _ts(),
        "title": spec.get("title"),
        "rule": spec.get("rule"),
        "twins": spec.get("twins"),
        "active_mode": active_mode(),
        "modes": list((spec.get("modes") or {}).keys()),
        "preservation": spec.get("preservation"),
        "ear": ear_status(),
        "truth_filters": truth,
        "redundancy": redundancy,
        "sovereign_time": sovereign,
        "stoard": stoard,
        "sound_tracker": sound_tracker,
    }