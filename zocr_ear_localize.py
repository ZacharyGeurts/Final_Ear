"""Audio localization — bearing, distance, arrangement, existence binding."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bearing_from_itd(itd_us: float, head_width_m: float = 0.18, c: float = 343.0) -> float:
    """Interaural time difference → azimuth degrees (simplified)."""
    max_delay = head_width_m / c
    itd_s = itd_us / 1e6
    x = max(-1.0, min(1.0, itd_s / max_delay))
    return math.degrees(math.asin(x))


def _distance_from_level(level_db: float, ref_db: float = 94.0, rolloff: float = 6.0) -> float:
    """Level-based distance estimate (inverse square approx)."""
    delta = ref_db - level_db
    if delta <= 0:
        return 0.5
    return round(10 ** (delta / (2 * rolloff)), 2)


def localize_sources(
    *,
    channels: list[dict[str, Any]] | None = None,
    itd_us: float | None = None,
    level_db: float | None = None,
    arrangement_hint: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ch = channels or []
    sources: list[dict[str, Any]] = []

    if itd_us is not None and level_db is not None:
        bearing = _bearing_from_itd(itd_us)
        dist = _distance_from_level(level_db)
        sources.append({
            "id": "primary",
            "bearing_deg": round(bearing, 1),
            "elevation_deg": 0.0,
            "distance_m": dist,
            "level_db": level_db,
            "itd_us": itd_us,
        })

    for i, row in enumerate(arrangement_hint or ch):
        sources.append({
            "id": row.get("id", f"src_{i}"),
            "bearing_deg": row.get("bearing_deg"),
            "elevation_deg": row.get("elevation_deg", 0.0),
            "distance_m": row.get("distance_m"),
            "level_db": row.get("level_db"),
            "label": row.get("label"),
        })

    if not sources and ch:
        for i, row in enumerate(ch):
            sources.append({"id": f"ch_{i}", **row})

    bearings = [s["bearing_deg"] for s in sources if s.get("bearing_deg") is not None]
    arrangement = {
        "count": len(sources),
        "spread_deg": round(max(bearings) - min(bearings), 1) if len(bearings) >= 2 else 0.0,
        "geometry": "arc" if len(sources) > 2 else ("pair" if len(sources) == 2 else "point"),
    }

    return {
        "ok": True,
        "schema": "zocr-ear-localize/v1",
        "updated": _ts(),
        "sources": sources,
        "point": sources[0] if sources else None,
        "arrangement": arrangement,
        "doctrine": "Identify point, distance, arrangement — correlate with existence before trust",
    }


def correlate_existence(
    localization: dict[str, Any],
    *,
    sdf_entities: list[dict[str, Any]] | None = None,
    vision_bearings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entities = sdf_entities or []
    vision = vision_bearings or []
    sources = localization.get("sources") or []
    matches: list[dict[str, Any]] = []

    for src in sources:
        sb = src.get("bearing_deg")
        best = None
        best_delta = 999.0
        for ent in entities:
            eb = ent.get("bearing_deg")
            if sb is None or eb is None:
                continue
            delta = abs(sb - eb)
            if delta < best_delta:
                best_delta = delta
                best = ent
        for vb in vision:
            eb = vb.get("bearing_deg")
            if sb is None or eb is None:
                continue
            delta = abs(sb - eb)
            if delta < best_delta:
                best_delta = delta
                best = vb
        corr = max(0.0, 1.0 - best_delta / 45.0) if best else 0.4
        matches.append({
            "source_id": src.get("id"),
            "entity": best,
            "bearing_delta_deg": round(best_delta, 1) if best else None,
            "correlation": round(corr, 3),
        })

    avg = sum(m["correlation"] for m in matches) / len(matches) if matches else 0.5
    return {
        "ok": avg >= 0.65,
        "schema": "zocr-ear-existence-correlate/v1",
        "updated": _ts(),
        "matches": matches,
        "correlation": round(avg, 3),
        "rule": "Audio must correlate with witnessed existence — not ventriloquist tricks",
    }