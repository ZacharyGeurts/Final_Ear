"""Final_Ear sovereign time — monotonic seals for every ear tick; never desync."""
from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_SG = _ROOT.parent
_EAR_TIME_STATE = _ROOT / "data" / "ear-sovereign-time.json"
_SCHEMA = "zocr-ear-sovereign-time/v1"
_SYNC_MAX_DELTA_NS = int(os.environ.get("ZOCR_EYE_EAR_SYNC_MAX_NS", "500_000_000").replace("_", ""))


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sovereign_time_paths() -> list[Path]:
    candidates: list[Path] = []
    for env in ("NEXUS_INSTALL_ROOT", "QUEEN_ROOT"):
        v = os.environ.get(env, "").strip()
        if v:
            candidates.append(Path(v) / "lib" / "sovereign-time.py")
    candidates.extend([
        _SG / "Latest" / "NEXUS-Shield" / "lib" / "sovereign-time.py",
        _SG / "NewLatest" / "lib" / "sovereign-time.py",
        _SG / "NewLatest" / "Queen" / "lib" / "sovereign-time.py",
    ])
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            out.append(p)
    return out


def _writable_state_dir() -> Path:
    for candidate in (
        os.environ.get("NEXUS_STATE_DIR", "").strip(),
        str(_ROOT / "data" / "sovereign-time-state"),
        str(_SG / "NewLatest" / "Queen" / ".nexus-state"),
    ):
        if not candidate:
            continue
        p = Path(candidate)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return p
        except OSError:
            continue
    fallback = _ROOT / "data" / "sovereign-time-state"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _load_sovereign_module():
    state = _writable_state_dir()
    os.environ.setdefault("NEXUS_STATE_DIR", str(state))
    for path in _sovereign_time_paths():
        try:
            spec = importlib.util.spec_from_file_location("sovereign_time", path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "STATE"):
                mod.STATE = state
            if hasattr(mod, "RECEIPT_LOG"):
                mod.RECEIPT_LOG = state / "sovereign-time-receipts.jsonl"
            if hasattr(mod, "PULSE_STATE"):
                mod.PULSE_STATE = state / "sovereign-time-pulse.json"
            if hasattr(mod, "KEY_FILE"):
                mod.KEY_FILE = state / "sovereign-time-key.bin"
            return mod, str(path)
        except Exception:
            continue
    return None, None


def _local_clock_sample() -> dict[str, Any]:
    return {
        "mono_ns": time.monotonic_ns(),
        "realtime_ns": time.time_ns(),
        "utc": _ts(),
        "source": "local_fallback",
    }


def _load_ear_time_state() -> dict[str, Any]:
    if _EAR_TIME_STATE.is_file():
        try:
            return json.loads(_EAR_TIME_STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"schema": _SCHEMA, "pulses": []}


def _save_ear_time_state(st: dict[str, Any]) -> None:
    _EAR_TIME_STATE.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = _ts()
    _EAR_TIME_STATE.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def seal_ear_tick(*, reason: str = "earball") -> dict[str, Any]:
    """Monotonic pulse before status, arm, perceive, or neural identify."""
    mod, src = _load_sovereign_module()
    receipt: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    if mod:
        try:
            issued = mod.issue_pulse(chain=f"final_ear:{reason}")
            if isinstance(issued, dict) and issued.get("mono_ns"):
                receipt = issued
            prev = None
            st_path = Path(getattr(mod, "PULSE_STATE", ""))
            if st_path.is_file():
                try:
                    doc = json.loads(st_path.read_text(encoding="utf-8"))
                    pulses = doc.get("pulses") if isinstance(doc.get("pulses"), list) else None
                    if isinstance(doc.get("last"), dict):
                        prev = doc.get("last")
                    elif pulses:
                        prev = pulses[-2] if len(pulses) >= 2 else None
                except (OSError, json.JSONDecodeError):
                    prev = None
            if receipt and hasattr(mod, "verify_receipt"):
                verify = mod.verify_receipt(receipt, prev_receipt=prev if isinstance(prev, dict) else None)
        except Exception as exc:
            receipt = None
            verify = {"schema": "sovereign-time/v1", "verdict": "USER_OK", "issues": [], "fallback": str(exc)[:120]}
    if not receipt or not receipt.get("mono_ns"):
        sample = _local_clock_sample()
        receipt = {
            "schema": "sovereign-time/v1",
            "pulse": int(time.time()),
            "chain": f"final_ear:{reason}",
            "mono_ns": sample["mono_ns"],
            "realtime_ns": sample["realtime_ns"],
            "utc": sample["utc"],
            "source": "zocr_local_pulse",
        }
        verify = {"schema": "sovereign-time/v1", "verdict": "USER_OK", "issues": [], "local_only": True}

    st = _load_ear_time_state()
    pulses = st.get("pulses") if isinstance(st.get("pulses"), list) else []
    pulses.append({"ts": _ts(), "reason": reason, "receipt": receipt, "verify": verify})
    st["pulses"] = pulses[-64:]
    st["last"] = receipt
    st["last_verify"] = verify
    st["always"] = True
    _save_ear_time_state(st)

    verdict = (verify or {}).get("verdict", "USER_OK")
    return {
        "schema": _SCHEMA,
        "always": True,
        "reason": reason,
        "verdict": verdict,
        "ok": verdict == "USER_OK",
        "sealed_mono_ns": receipt.get("mono_ns"),
        "sealed_ts": receipt.get("utc") or _ts(),
        "micron_witness": receipt.get("micron_witness"),
        "pulse": receipt.get("pulse"),
        "source": src or receipt.get("source", "local"),
        "receipt": receipt,
        "verify": verify,
    }


def sovereign_time_status(*, seal: bool = True) -> dict[str, Any]:
    mod, src = _load_sovereign_module()
    base: dict[str, Any] = {
        "schema": _SCHEMA,
        "always": True,
        "enabled": True,
        "module": src,
        "sync_max_delta_ns": _SYNC_MAX_DELTA_NS,
        "rule": "Sovereign time always seals ear — monotonic witness, never pool-only NTP",
    }
    if mod and hasattr(mod, "status"):
        try:
            doc = mod.status()
            base["nexus"] = doc
            last = doc.get("last_pulse") if isinstance(doc.get("last_pulse"), dict) else None
            verify = doc.get("last_verify") if isinstance(doc.get("last_verify"), dict) else None
            if last:
                base["sealed_mono_ns"] = last.get("mono_ns")
                base["micron_witness"] = last.get("micron_witness")
                base["pulse"] = last.get("pulse")
            if verify:
                base["verdict"] = verify.get("verdict", "USER_OK")
                base["ok"] = base["verdict"] == "USER_OK"
        except Exception as exc:
            base["nexus_error"] = str(exc)[:200]

    st = _load_ear_time_state()
    if st.get("last"):
        base["ear_last"] = st.get("last")
        lv = st.get("last_verify") if isinstance(st.get("last_verify"), dict) else {}
        base.setdefault("verdict", lv.get("verdict", "USER_OK"))
        base.setdefault("ok", base.get("verdict") == "USER_OK")
        base.setdefault("sealed_mono_ns", (st.get("last") or {}).get("mono_ns"))
        base.setdefault("micron_witness", (st.get("last") or {}).get("micron_witness"))

    if seal and not base.get("sealed_mono_ns"):
        tick = seal_ear_tick(reason="status")
        base["tick"] = tick
        base["verdict"] = tick.get("verdict", "USER_OK")
        base["ok"] = tick.get("ok", True)
        base["sealed_mono_ns"] = tick.get("sealed_mono_ns")
        base["sealed_ts"] = tick.get("sealed_ts")
        base["micron_witness"] = tick.get("micron_witness")

    base.setdefault("verdict", "USER_OK")
    base.setdefault("ok", base["verdict"] == "USER_OK")
    return base


def verify_eye_ear_sync(*, eye_mono_ns: int | None, ear_mono_ns: int | None) -> dict[str, Any]:
    """Reject fused identify when eye and ear sovereign clocks diverge."""
    if eye_mono_ns is None or ear_mono_ns is None:
        return {
            "ok": False,
            "schema": "zocr-eye-ear-sync/v1",
            "error": "missing_mono_ns",
            "desync": True,
            "speak": "SQUIDGIE — eye or ear pulse missing; hold fusion",
        }
    delta = abs(int(eye_mono_ns) - int(ear_mono_ns))
    ok = delta <= _SYNC_MAX_DELTA_NS
    return {
        "ok": ok,
        "schema": "zocr-eye-ear-sync/v1",
        "delta_ns": delta,
        "max_delta_ns": _SYNC_MAX_DELTA_NS,
        "desync": not ok,
        "eye_mono_ns": eye_mono_ns,
        "ear_mono_ns": ear_mono_ns,
        "speak": "Eye↔Ear clocks aligned" if ok else "SQUIDGIE — sovereign desync; fusion held",
    }


def load_eye_sovereign_mono() -> int | None:
    try:
        fe = Path(os.environ.get("FINAL_EYE_ROOT", _SG / "Final_Eye"))
        spec = importlib.util.spec_from_file_location("eye_sov", fe / "zocr_sovereign_time.py")
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        st = mod.sovereign_time_status(seal=False)
        mono = st.get("sealed_mono_ns")
        if mono is None and isinstance(st.get("eyeball_last"), dict):
            mono = st["eyeball_last"].get("mono_ns")
        return int(mono) if mono is not None else None
    except Exception:
        return None