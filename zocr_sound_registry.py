"""Permanent sound registry — stable IDs bound to neural assist network."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = _ROOT / "data" / "sound-registry.json"
DOCTRINE_PATH = _ROOT / "data" / "sound-tracker-doctrine.json"
NET_PATH = _ROOT / "data" / "ear-neural-assist.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_registry(doc: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updated"] = _ts()
    REGISTRY_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _ledger_path() -> Path:
    nexus = Path(os.environ.get("NEXUS_STATE_DIR", _ROOT / ".nexus-state"))
    return nexus / "sound-registry-ledger.jsonl"


def _row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _append_ledger(row: dict[str, Any]) -> dict[str, Any]:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = None
    if path.is_file():
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                prev = json.loads(line).get("hash")
                break
            except json.JSONDecodeError:
                continue
    entry = {**row, "ts": row.get("ts") or _ts(), "prev_hash": prev}
    entry["hash"] = _row_hash(entry)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def fingerprint(obs: dict[str, Any]) -> str:
    """Stable fingerprint from ingress + source identity + coarse bearing bucket."""
    parts = [
        str(obs.get("ingress_lane") or "unknown"),
        str(obs.get("source_key") or obs.get("label") or "anon"),
        str(obs.get("kind") or ""),
        str(int(round(float(obs.get("bearing_deg") or 0) / 15.0) * 15)),
    ]
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def permanent_sound_id(fp: str) -> str:
    doc = _read(DOCTRINE_PATH, {})
    prefix = (doc.get("neural_bind") or {}).get("permanent_id_prefix", "snd_")
    return f"{prefix}{fp[:12]}"


def register_sound(obs: dict[str, Any], *, neural_label: str | None = None) -> dict[str, Any]:
    """Assign or refresh permanent sound_id — never drops on error."""
    fp = fingerprint(obs)
    sound_id = permanent_sound_id(fp)
    net = _read(NET_PATH, {})
    doc = _read(REGISTRY_PATH, {"schema": "zocr-sound-registry/v1", "sounds": {}})
    sounds: dict[str, Any] = dict(doc.get("sounds") or {})
    existing = sounds.get(sound_id) or {}
    now = _ts()
    entry = {
        **existing,
        "sound_id": sound_id,
        "fingerprint": fp,
        "ingress_lane": obs.get("ingress_lane"),
        "source_key": obs.get("source_key"),
        "label": obs.get("label") or existing.get("label") or sound_id,
        "kind": obs.get("kind") or existing.get("kind"),
        "neural_network_id": net.get("network_id", "FINAL_EAR_ASSIST_v1"),
        "neural_label": neural_label or existing.get("neural_label") or "clear_audio",
        "first_seen": existing.get("first_seen") or now,
        "last_seen": now,
        "tick_count": int(existing.get("tick_count") or 0) + 1,
        "permanent": True,
    }
    sounds[sound_id] = entry
    lanes: dict[str, int] = {}
    for s in sounds.values():
        lane = s.get("ingress_lane") or "unknown"
        lanes[lane] = lanes.get(lane, 0) + 1
    doc["sounds"] = sounds
    doc["stats"] = {
        "total": len(sounds),
        "active": sum(1 for s in sounds.values() if s.get("tick_count", 0) > 0),
        "lanes": lanes,
    }
    _save_registry(doc)
    _append_ledger({"event": "register", "sound_id": sound_id, "fingerprint": fp, "label": entry["label"]})
    return {"ok": True, "sound_id": sound_id, "fingerprint": fp, "entry": entry, "new": not bool(existing)}


def resolve_sound(sound_id: str) -> dict[str, Any]:
    doc = _read(REGISTRY_PATH, {"sounds": {}})
    entry = (doc.get("sounds") or {}).get(sound_id)
    if not entry:
        return {"ok": False, "error": "unknown_sound_id", "sound_id": sound_id}
    return {"ok": True, "entry": entry}


def registry_status() -> dict[str, Any]:
    doc = _read(REGISTRY_PATH, {"sounds": {}, "stats": {}})
    sounds = list((doc.get("sounds") or {}).values())
    sounds.sort(key=lambda s: s.get("last_seen") or "", reverse=True)
    return {
        "ok": True,
        "schema": "zocr-sound-registry-status/v1",
        "updated": doc.get("updated") or _ts(),
        "stats": doc.get("stats") or {},
        "permanent_bind": "ear-neural-assist",
        "network_id": _read(NET_PATH, {}).get("network_id"),
        "recent": sounds[:16],
    }