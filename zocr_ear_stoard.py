"""Ear stoard — secure expanding storage for audio witness."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
DOCTRINE_PATH = _ROOT / "data" / "ear-stoard-doctrine.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_doctrine() -> dict[str, Any]:
    doc = _read_json(DOCTRINE_PATH)
    if doc.get("schema"):
        return doc
    return {"schema": "zocr-ear-stoard/v1", "growth": {"initial_cap_bytes": 268435456}}


def stoard_root() -> Path:
    env = os.environ.get("FINAL_EAR_STOARD_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return (_ROOT / "stoard").resolve()


def _paths() -> dict[str, Path]:
    root = stoard_root()
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "ledger": root / "ledger.jsonl",
        "witness": root / "witness",
        "blobs": root / "blobs",
        "compile": root / "compile",
        "quarantine": root / "quarantine",
    }


def _ensure_layout() -> dict[str, Path]:
    p = _paths()
    for key in ("root", "witness", "blobs", "compile", "quarantine"):
        p[key].mkdir(parents=True, exist_ok=True)
    return p


def _row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_ledger_hash() -> str | None:
    p = _paths()
    if not p["ledger"].is_file():
        return None
    for line in reversed(p["ledger"].read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
            return doc.get("hash") or _row_hash(doc)
        except json.JSONDecodeError:
            continue
    return None


def _append_ledger(row: dict[str, Any]) -> dict[str, Any]:
    p = _ensure_layout()
    prev = _last_ledger_hash()
    entry = {**row, "ts": row.get("ts") or _ts(), "prev_hash": prev}
    entry["hash"] = _row_hash(entry)
    with p["ledger"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _seal_ok() -> dict[str, Any]:
    try:
        from zocr_security import verify_code_seal
        return verify_code_seal()
    except ImportError:
        return {"ok": True, "reason": "security_module_missing"}


def _quarantine(row: dict[str, Any]) -> dict[str, Any]:
    p = _ensure_layout()
    name = f"reject-{_ts().replace(':', '').replace('.', '')}.json"
    path = p["quarantine"] / name
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    entry = _append_ledger({"event": "quarantine", **row})
    return {"ok": False, "quarantined": str(path), "ledger": entry}


def witness_compiler(*, reason: str = "field_compiler", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    seal = _seal_ok()
    if not seal.get("ok"):
        return _quarantine({"error": "seal_fail", "seal": seal, "reason": reason})
    p = _ensure_layout()
    row = {"event": "witness", "reason": reason, "payload": payload or {}}
    name = f"witness-{_ts().replace(':', '').replace('.', '')}.json"
    path = p["witness"] / name
    doc = {"schema": "zocr-ear-stoard-witness/v1", "ts": _ts(), **row}
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    entry = _append_ledger({"event": "witness", "path": str(path), "reason": reason})
    return {"ok": True, "witness": str(path), "ledger": entry}


def stoard_for_field_compiler() -> dict[str, Any]:
    st = stoard_status()
    st["write_gate"] = "code_seal"
    st["seal_ok"] = _seal_ok().get("ok")
    return st


def stoard_status() -> dict[str, Any]:
    p = _ensure_layout()
    cap = int((load_doctrine().get("growth") or {}).get("initial_cap_bytes", 268435456))
    used = 0
    witness_count = 0
    if p["manifest"].is_file():
        try:
            doc = _read_json(p["manifest"])
            used = int(doc.get("used_bytes", 0))
            cap = int(doc.get("cap_bytes", cap))
            witness_count = int(doc.get("witness_count", 0))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "schema": "zocr-ear-stoard-status/v1",
        "updated": _ts(),
        "root": str(p["root"]),
        "present": p["root"].is_dir(),
        "cap_bytes": cap,
        "used_bytes": used,
        "witness_count": witness_count,
        "doctrine": load_doctrine().get("rule"),
        "zones": {k: str(p[k]) for k in ("witness", "blobs", "compile", "quarantine")},
        "seal_ok": _seal_ok().get("ok"),
    }