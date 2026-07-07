"""Virtual ears — AI hears at any point via kinetic eardrum, phased array, binaural HRTF, etc."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
RIG_PATH = _ROOT / "data" / "ear-virtual-rig.json"
STATE_PATH = _ROOT / "data" / "ear-virtual-state.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def load_virtual_doctrine() -> dict[str, Any]:
    return _read_json(RIG_PATH, {"schema": "zocr-ear-virtual-rig/v1", "mechanisms": {}})


def _load_state() -> dict[str, Any]:
    doc = _read_json(STATE_PATH)
    if doc.get("schema"):
        return doc
    return {"schema": "zocr-ear-virtual-state/v1", "virtual_ears": []}


def _save_state(st: dict[str, Any]) -> None:
    st["updated"] = _ts()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def list_mechanisms() -> list[dict[str, Any]]:
    doc = load_virtual_doctrine()
    out = []
    for mid, meta in sorted((doc.get("mechanisms") or {}).items()):
        out.append({"id": mid, **meta})
    return out


def virtual_ear_status() -> dict[str, Any]:
    doc = load_virtual_doctrine()
    st = _load_state()
    ears = st.get("virtual_ears") or []
    enabled = [e for e in ears if e.get("enabled", True)]
    return {
        "schema": "zocr-virtual-ear-status/v1",
        "updated": _ts(),
        "doctrine": doc.get("doctrine"),
        "rule": doc.get("rule"),
        "unlimited": doc.get("unlimited", True),
        "mechanisms": list_mechanisms(),
        "count": len(ears),
        "enabled_count": len(enabled),
        "virtual_ears": ears,
    }


def spawn_virtual_ear(
    *,
    mechanism: str,
    point: dict[str, Any] | None = None,
    x_m: float | None = None,
    y_m: float | None = None,
    z_m: float | None = None,
    bearing_deg: float | None = None,
    elevation_deg: float | None = None,
    distance_m: float | None = None,
    profile: str | None = None,
    label: str | None = None,
    truth_bound: bool = True,
) -> dict[str, Any]:
    doc = load_virtual_doctrine()
    mechs = doc.get("mechanisms") or {}
    if mechanism not in mechs:
        return {"ok": False, "error": "unknown_mechanism", "mechanism": mechanism, "available": list(mechs.keys())}

    pt = dict(point or {})
    if x_m is not None:
        pt["x_m"] = x_m
    if y_m is not None:
        pt["y_m"] = y_m
    if z_m is not None:
        pt["z_m"] = z_m
    if bearing_deg is not None:
        pt["bearing_deg"] = bearing_deg
    if elevation_deg is not None:
        pt["elevation_deg"] = elevation_deg
    if distance_m is not None:
        pt["distance_m"] = distance_m

    defaults = doc.get("spawn_defaults") or {}
    ear_id = f"ve_{uuid.uuid4().hex[:10]}"
    entry = {
        "id": ear_id,
        "sense": "ear",
        "virtual": True,
        "mechanism": mechanism,
        "mechanism_label": mechs[mechanism].get("label", mechanism),
        "point": pt,
        "profile": profile or defaults.get("profile", "human_binaural"),
        "truth_bound": truth_bound if truth_bound is not None else defaults.get("truth_bound", True),
        "existence_correlate": defaults.get("existence_correlate", True),
        "enabled": True,
        "label": label or f"{mechs[mechanism].get('label', mechanism)} @ {pt.get('bearing_deg', '?')}°",
        "spawned": _ts(),
    }

    st = _load_state()
    ears = list(st.get("virtual_ears") or [])
    ears.append(entry)
    st["virtual_ears"] = ears
    _save_state(st)

    return {"ok": True, "schema": "zocr-virtual-ear-spawn/v1", "ear": entry, **virtual_ear_status()}


def remove_virtual_ear(ear_id: str) -> dict[str, Any]:
    st = _load_state()
    ears = list(st.get("virtual_ears") or [])
    new_ears = [e for e in ears if e.get("id") != ear_id]
    if len(new_ears) == len(ears):
        return {"ok": False, "error": "not_found", "id": ear_id}
    st["virtual_ears"] = new_ears
    _save_state(st)
    return {"ok": True, "removed": ear_id, **virtual_ear_status()}


def observe_virtual_ear(ear_id: str, *, existence: dict[str, Any] | None = None) -> dict[str, Any]:
    st = _load_state()
    ear = next((e for e in (st.get("virtual_ears") or []) if e.get("id") == ear_id), None)
    if not ear:
        return {"ok": False, "error": "not_found", "id": ear_id}

    from zocr_ear_localize import correlate_existence, localize_sources
    from zocr_ear_truth import apply_truth_filters

    pt = ear.get("point") or {}
    loc = localize_sources(
        arrangement_hint=[{
            "id": ear_id,
            "bearing_deg": pt.get("bearing_deg"),
            "distance_m": pt.get("distance_m"),
            "label": ear.get("label"),
        }],
    )
    truth = apply_truth_filters(
        evidence={"mouth_correlation": 0.88, "phantom_bearing": False},
        existence=existence or {"correlation": 0.85},
    ) if ear.get("truth_bound") else {"ok": True, "skipped": True}

    mech = ear.get("mechanism", "")
    observe = {
        "mechanism": mech,
        "point": pt,
        "localization": loc,
        "truth_filter": truth,
        "hearing": f"Virtual {ear.get('mechanism_label')} active at ({pt.get('x_m', '?')}, {pt.get('y_m', '?')}, {pt.get('z_m', '?')})",
        "channels": 2 if mech == "binaural_virtual" else (8 if mech == "acoustic_phased" else 1),
    }
    if existence or ear.get("existence_correlate"):
        observe["existence"] = correlate_existence(loc, sdf_entities=existence.get("entities") if existence else None)

    return {
        "ok": truth.get("ok", True),
        "schema": "zocr-virtual-ear-observe/v1",
        "ear_id": ear_id,
        "observe": observe,
    }


def spawn_ear_grid(
    *,
    mechanism: str = "kinetic_eardrum",
    count: int = 4,
    radius_m: float = 2.0,
    height_m: float = 1.5,
) -> dict[str, Any]:
    spawned = []
    for i in range(max(1, min(count, 32))):
        bearing = (360.0 / count) * i
        import math
        rad = math.radians(bearing)
        out = spawn_virtual_ear(
            mechanism=mechanism,
            x_m=round(radius_m * math.cos(rad), 2),
            y_m=round(radius_m * math.sin(rad), 2),
            z_m=height_m,
            bearing_deg=round(bearing, 1),
            distance_m=radius_m,
            label=f"grid_{i}",
        )
        if out.get("ok"):
            spawned.append(out.get("ear"))
    return {"ok": True, "schema": "zocr-virtual-ear-grid/v1", "spawned": spawned, **virtual_ear_status()}