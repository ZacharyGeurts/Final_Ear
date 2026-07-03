"""Final Ear mandate security — code seal, kill gate, truth floor."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
SEAL_PATH = _ROOT / "data" / "code-seal.json"
MANDATE_PATH = _ROOT / "data" / "zocr-field-mandate.json"
_CODE_GLOB = ("zocr*.py",)
_PROTECTED_OPS = frozenset({
    "listen", "analyze_audio", "audio_offense", "countermeasure", "stoard_write",
    "nn_analyze", "virtual_observe", "truth_filter", "hardware_bind",
})


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_mandate() -> dict[str, Any]:
    try:
        return json.loads(MANDATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mandate_id": "ZOCR_FIELD_AUDIO_MANDATE_v1", "security": {}}


def _code_files() -> list[Path]:
    found: list[Path] = []
    for pattern in _CODE_GLOB:
        found.extend(_ROOT.glob(pattern))
    return sorted({p.resolve() for p in found if p.is_file()})


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def seal_codebase() -> dict[str, Any]:
    m = load_mandate()
    mid = m.get("mandate_id", "ZOCR_FIELD_AUDIO_MANDATE_v1")
    files = {str(p.relative_to(_ROOT)): _hash_file(p) for p in _code_files()}
    chain = "|".join(f"{k}:{v}" for k, v in sorted(files.items()))
    root = hashlib.sha256(f"{mid}|{chain}".encode()).hexdigest()
    doc = {
        "schema": "zocr-ear-code-seal/v1",
        "mandate_id": mid,
        "ts": _ts(),
        "files": files,
        "file_count": len(files),
        "root_seal": root,
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def verify_code_seal() -> dict[str, Any]:
    if not SEAL_PATH.is_file():
        return {"ok": False, "reason": "seal_missing", "hint": "pythong zocr_security.py seal"}
    try:
        doc = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "reason": "seal_corrupt"}
    sealed = doc.get("files") or {}
    current = {str(p.relative_to(_ROOT)): _hash_file(p) for p in _code_files()}
    errors = [r for r, e in sealed.items() if r in current and current[r] != e]
    missing = [r for r in sealed if r not in current]
    ok = not errors and not missing
    return {
        "ok": ok,
        "mandate_id": doc.get("mandate_id"),
        "root_seal": doc.get("root_seal"),
        "tampered": errors[:8],
        "missing": missing[:8],
    }


def mandate_gate(*, client_host: str | None = None) -> dict[str, Any]:
    host = (client_host or "127.0.0.1").strip()
    if host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("127."):
        return {"ok": False, "reason": "localhost_only", "client": host}
    return {"ok": True, "client": host}


def mandate_enforce(
    operation: str,
    *,
    client_host: str | None = None,
    require_seal: bool = True,
) -> dict[str, Any]:
    if os.environ.get("ZOCR_MANDATE_OFF", "").strip().lower() in ("1", "true", "yes"):
        return {"ok": True, "override": True, "operation": operation}
    if os.environ.get("QUEEN_SOVEREIGN_WIRE", "") == "1":
        return {"ok": True, "sovereign_wire": True, "operation": operation}
    from zocr_kill import check as kill_check
    kill = kill_check(operation)
    if not kill.get("ok"):
        return kill
    gate = mandate_gate(client_host=client_host)
    if not gate.get("ok"):
        return {"ok": False, "error": "mandate_gate", "operation": operation, **gate}
    m = load_mandate()
    if require_seal and m.get("security", {}).get("code_seal_required", True):
        if operation in _PROTECTED_OPS:
            seal = verify_code_seal()
            if not seal.get("ok"):
                return {"ok": False, "error": "code_seal", "operation": operation, **seal}
    return {"ok": True, "operation": operation, "mandate_id": m.get("mandate_id")}


def security_status() -> dict[str, Any]:
    return {
        "schema": "zocr-ear-security-status/v1",
        "updated": _ts(),
        "code_seal": verify_code_seal(),
        "mandate": load_mandate().get("mandate_id"),
        "protected_operations": sorted(_PROTECTED_OPS),
    }


def main() -> int:
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "seal":
        print(json.dumps(seal_codebase(), indent=2))
        return 0
    if cmd == "verify":
        print(json.dumps(verify_code_seal(), indent=2))
        return 0
    print(json.dumps(security_status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())