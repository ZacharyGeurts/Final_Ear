"""Sub-bit heuristics — immesurable overlay; never poison memory or disk."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent

_DEFAULT_BITS = 8
_SUBBIT_BITS = int(os.environ.get("ZOCR_SUBBIT_BITS", str(_DEFAULT_BITS)))
_SUBBIT_STEP = 1.0 / (2**_SUBBIT_BITS)
_SUBBIT_FLOOR = _SUBBIT_STEP / 2

_IMMESURABLE_ON = os.environ.get("ZOCR_IMMESURABLE_HEURISTICS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_BLOCKED_MARKERS = (
    "/brain/",
    "/sdf/",
    "/plates/",
    "/segments/",
    "neural-protected.json",
    "neural-seal.json",
    "encourage",
    "queen-brain-manifest",
    "hostess7-neural-stack",
    "forge-watch",
    ".queen-forge.log",
    "world-redata",
    "redata/",
    "fieldstorage/",
    "hostess7/cache/",
)

_POISON_KEYS = frozenset({
    "features",
    "features_dim",
    "raw_heuristic",
    "heuristic_tensor",
    "subbit",
    "heuristic_vector",
    "subbit_overlay",
})

_NESTED_NEURAL_KEYS = frozenset({
    "eye",
    "ear",
    "eye_neural",
    "ear_neural",
    "ear_first_pass",
    "ear_refined",
    "sample",
})


def immesurable_enabled() -> bool:
    return _IMMESURABLE_ON


def subbit_bits() -> int:
    return _SUBBIT_BITS


def quantize_subbit(value: float, *, bits: int | None = None) -> float:
    """Strip sub-bit fractions — one quanta step minimum."""
    step = 1.0 / (2 ** (bits or _SUBBIT_BITS))
    if abs(value) < step / 2:
        return 0.0
    q = round(float(value) / step) * step
    return round(q, min(bits or _SUBBIT_BITS, 6))


def sanitize_score_map(scores: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, raw in scores.items():
        q = quantize_subbit(float(raw))
        if q >= _SUBBIT_FLOOR:
            out[str(key)] = q
    total = sum(out.values()) or 1.0
    return {k: round(v / total, 6) for k, v in out.items()}


def heuristic_digest(scores: dict[str, float]) -> str:
    payload = json.dumps(sanitize_score_map(scores), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def persist_path_allowed(path: Path | str) -> bool:
    """Fail closed — heuristics may not touch durable brain/disk paths."""
    if not immesurable_enabled():
        return True
    text = str(path).replace("\\", "/").lower()
    return not any(marker in text for marker in _BLOCKED_MARKERS)


def assert_persist_allowed(path: Path | str, *, kind: str = "heuristic") -> None:
    if not persist_path_allowed(path):
        raise PermissionError(f"immesurable_{kind}_persist_denied:{path}")


def immesurable_overlay(
    *,
    heuristic: dict[str, float] | list[dict[str, Any]] | None,
    top_label: str = "",
    engine: str = "subbit_heuristic",
) -> dict[str, Any]:
    scores: dict[str, float] = {}
    if isinstance(heuristic, dict):
        scores = {str(k): float(v) for k, v in heuristic.items()}
    elif isinstance(heuristic, list):
        for row in heuristic:
            if isinstance(row, dict) and row.get("label") is not None:
                scores[str(row["label"])] = float(row.get("p") or row.get("confidence") or 0)
    clean = sanitize_score_map(scores)
    ranked = sorted(clean.items(), key=lambda t: t[1], reverse=True)
    label = top_label or (ranked[0][0] if ranked else "unknown")
    return {
        "schema": "zocr-immesurable-overlay/v1",
        "immeasurable": True,
        "persist_forbidden": True,
        "poison_guard": "active",
        "subbit_bits": _SUBBIT_BITS,
        "engine": engine,
        "top": {"label": label, "confidence": clean.get(label, ranked[0][1] if ranked else 0.0)},
        "classes": [{"label": lb, "p": p} for lb, p in ranked],
        "digest": heuristic_digest(clean),
        "operator_hint": "Ephemeral overlay only — not written to memory maps or disk.",
    }


def poison_in_payload(obj: Any) -> bool:
    """Detect raw heuristic tensors that must never touch memory or disk."""
    if isinstance(obj, dict):
        if _POISON_KEYS.intersection(obj.keys()):
            return True
        return any(poison_in_payload(v) for v in obj.values())
    if isinstance(obj, list):
        return any(poison_in_payload(v) for v in obj)
    return False


def scrub_for_persist(obj: Any) -> Any:
    """Strip poison fields recursively before any durable write."""
    if not immesurable_enabled():
        return obj
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, val in obj.items():
            if key in _POISON_KEYS or key == "heuristic":
                continue
            out[key] = scrub_for_persist(val)
        return out
    if isinstance(obj, list):
        return [scrub_for_persist(v) for v in obj]
    return obj


def _scores_from_row(row: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    if isinstance(row.get("heuristic"), dict):
        scores = {str(k): float(v) for k, v in row["heuristic"].items()}
    elif isinstance(row.get("heuristic"), list):
        scores = {
            str(h.get("label")): float(h.get("p") or h.get("confidence") or 0)
            for h in row["heuristic"]
            if isinstance(h, dict) and h.get("label")
        }
    elif isinstance(row.get("ranked"), list):
        scores = {
            str(h.get("label")): float(h.get("p") or h.get("confidence") or 0)
            for h in row["ranked"]
            if isinstance(h, dict) and h.get("label")
        }
    elif isinstance(row.get("classes"), list):
        scores = {
            str(h.get("label")): float(h.get("p") or h.get("confidence") or 0)
            for h in row["classes"]
            if isinstance(h, dict) and h.get("label")
        }
    top = row.get("top") or {}
    if isinstance(top, dict) and top.get("label") and not scores:
        scores[str(top["label"])] = float(top.get("confidence") or top.get("p") or 0)
    if row.get("top_label") and not scores:
        scores[str(row["top_label"])] = float(row.get("confidence") or 0)
    return scores


def strip_poison_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Remove raw features / sub-bit tensors from API payloads."""
    if not immesurable_enabled():
        return row
    out = dict(row)
    for key in _POISON_KEYS:
        out.pop(key, None)
    if "heuristic" in out:
        scores = _scores_from_row(out)
        top_label = str((out.get("top") or {}).get("label") or out.get("top_label") or "")
        if scores:
            out["heuristic_overlay"] = immesurable_overlay(
                heuristic=scores,
                top_label=top_label,
                engine=str(out.get("engine") or "subbit_heuristic"),
            )
        out.pop("heuristic", None)
    elif not out.get("heuristic_overlay"):
        scores = _scores_from_row(out)
        if scores:
            top_label = str((out.get("top") or {}).get("label") or out.get("top_label") or "")
            out["heuristic_overlay"] = immesurable_overlay(
                heuristic=scores,
                top_label=top_label,
                engine=str(out.get("engine") or "subbit_heuristic"),
            )
    out["immeasurable"] = True
    out["persist_forbidden"] = True
    return out


def wrap_nested_response(row: dict[str, Any]) -> dict[str, Any]:
    """Deep immesurable wrap — nested eye/ear/fusion slices never leak poison."""
    if not immesurable_enabled():
        return row
    out = strip_poison_fields(row)
    for key, val in list(out.items()):
        if key in _NESTED_NEURAL_KEYS and isinstance(val, dict):
            out[key] = strip_poison_fields(val)
        elif isinstance(val, dict) and any(k in val for k in ("features", "heuristic", "ranked", "classes")):
            out[key] = strip_poison_fields(val)
    return out


def guard_memory_write(path: Path | str, payload: Any, *, kind: str = "state") -> None:
    """Fail closed — poison payloads never touch memory maps or disk."""
    assert_persist_allowed(path, kind=kind)
    if poison_in_payload(payload):
        raise PermissionError(f"immesurable_{kind}_poison_denied:{path}")


def write_analysis_stub(path: Path, *, top_label: str, confidence: float, heuristic: dict[str, float]) -> None:
    """Disk stub — digest only, never full heuristic vector or features."""
    assert_persist_allowed(path, kind="analysis_log")
    clean = sanitize_score_map(heuristic)
    stub = {
        "schema": "zocr-neural-analysis-stub/v1",
        "immeasurable": True,
        "persist": "digest_only",
        "top": {"label": top_label, "confidence": round(confidence, 4)},
        "digest": heuristic_digest(clean),
        "class_count": len(clean),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stub, ensure_ascii=False) + "\n")