"""Sound tracker — GPS heading, motion prediction, chase/avoid pursuit policies."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
DOCTRINE_PATH = _ROOT / "data" / "sound-tracker-doctrine.json"
STATE_PATH = _ROOT / "data" / "sound-tracker-state.json"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _save_state(st: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = _ts()
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")


def load_doctrine() -> dict[str, Any]:
    return _read(DOCTRINE_PATH, {"schema": "zocr-sound-tracker-doctrine/v1"})


def _load_state() -> dict[str, Any]:
    doc = _read(STATE_PATH)
    if doc.get("schema"):
        return doc
    return {"schema": "zocr-sound-tracker-state/v1", "tracks": {}, "operator_gps": {}}


def operator_gps() -> dict[str, Any]:
    """Current operator GPS + heading — local paths only, never fails."""
    doc = load_doctrine()
    gps_cfg = doc.get("gps") or {}
    paths = list(gps_cfg.get("operator_paths") or [])
    nexus = Path(os.environ.get("NEXUS_STATE_DIR", _ROOT / ".nexus-state"))
    paths.extend([str(nexus / "operator-location.json"), str(nexus.parent / "operator-location.json")])

    for rel in paths:
        p = Path(rel)
        if not p.is_absolute():
            p = _ROOT.parent / rel if (_ROOT.parent / rel).is_file() else nexus.parent / rel
        if not p.is_file():
            p2 = Path("/var/lib/nexus-shield") / "operator-location.json"
            if p2.is_file():
                p = p2
        if p.is_file():
            op = _read(p, {})
            lat, lon = op.get("lat"), op.get("lon")
            if lat is not None and lon is not None:
                return {
                    "ok": True,
                    "lat": float(lat),
                    "lon": float(lon),
                    "heading_deg": float(op.get("heading_deg") or op.get("bearing_deg") or 0.0),
                    "source": op.get("source") or str(p),
                }

    return {
        "ok": True,
        "lat": float(gps_cfg.get("fallback_lat", 42.3314)),
        "lon": float(gps_cfg.get("fallback_lon", -83.0458)),
        "heading_deg": 0.0,
        "source": gps_cfg.get("fallback_source", "field_centroid"),
        "fallback": True,
    }


def bearing_to_gps(
    *,
    lat: float,
    lon: float,
    bearing_deg: float,
    distance_m: float,
) -> dict[str, float]:
    """Offset GPS from operator position along bearing."""
    r = 6371000.0
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance_m / r)
        + math.cos(lat1) * math.sin(distance_m / r) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(distance_m / r) * math.cos(lat1),
        math.cos(distance_m / r) - math.sin(lat1) * math.sin(lat2),
    )
    return {"lat": round(math.degrees(lat2), 6), "lon": round(math.degrees(lon2), 6)}


def _distance_from_level(level_db: float) -> float:
    ref = -18.0
    delta = ref - level_db
    if delta <= 0:
        return 1.5
    return round(min(80.0, 10 ** (delta / 12.0)), 2)


def _normalize_bearing(deg: float) -> float:
    return (deg % 360.0 + 360.0) % 360.0


def _bearing_delta(a: float, b: float) -> float:
    d = abs(_normalize_bearing(a) - _normalize_bearing(b))
    return min(d, 360.0 - d)


def predict_motion(history: list[dict[str, Any]], *, cfg: dict[str, Any]) -> dict[str, Any]:
    """Simple velocity + bearing trend from history ticks."""
    motion_cfg = cfg.get("motion") or {}
    if len(history) < 2:
        return {
            "is_moving": False,
            "direction_deg": history[-1].get("bearing_deg", 0.0) if history else 0.0,
            "speed_mps": 0.0,
            "confidence": 0.35,
            "horizon_s": motion_cfg.get("predict_horizon_s", 3.0),
        }

    recent = history[-min(len(history), int(motion_cfg.get("history_ticks", 12))):]
    bearings = [float(h.get("bearing_deg") or 0) for h in recent]
    dists = [float(h.get("distance_m") or 1.5) for h in recent]
    b_delta = _bearing_delta(bearings[-1], bearings[0])
    d_delta = dists[-1] - dists[0]
    dt = max(0.5, len(recent) * 0.5)
    speed = math.sqrt((d_delta / dt) ** 2 + (b_delta * 0.02) ** 2)
    threshold = float(motion_cfg.get("moving_speed_mps", 0.35))
    jitter = float(motion_cfg.get("bearing_jitter_deg", 4.0))
    moving = speed >= threshold or b_delta >= jitter

    direction = bearings[-1]
    if moving and len(bearings) >= 2:
        direction = _normalize_bearing(bearings[-1] + (bearings[-1] - bearings[-2]) * 0.5)

    conf = min(0.95, 0.4 + len(recent) * 0.04 + (0.2 if moving else 0.0))
    return {
        "is_moving": moving,
        "direction_deg": round(direction, 1),
        "speed_mps": round(speed, 3),
        "confidence": round(conf, 3),
        "horizon_s": motion_cfg.get("predict_horizon_s", 3.0),
        "bearing_delta_deg": round(b_delta, 2),
        "distance_delta_m": round(d_delta, 2),
    }


def apply_pursuit_policy(
    track: dict[str, Any],
    *,
    policy: str | None = None,
    doctrine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute pursuit vector — chase, avoid, hold, orbit, shadow."""
    doc = doctrine or load_doctrine()
    policies = doc.get("pursuit_policies") or {}
    pol_id = policy or track.get("policy") or doc.get("default_policy", "hold")
    pol = policies.get(pol_id) or policies.get("hold") or {}
    bearing = float(track.get("bearing_deg") or 0)
    motion = track.get("motion") or {}
    predict = track.get("predict") or motion
    dist = float(track.get("distance_m") or 2.0)
    lead = float(pol.get("lead_factor") or 1.0)
    horizon = float(predict.get("horizon_s") or 3.0)
    speed = float(predict.get("speed_mps") or 0.0)

    if pol_id == "avoid":
        target_bearing = _normalize_bearing(bearing + float(pol.get("bearing_delta_deg", 180)))
        action = "steer_away"
    elif pol_id == "chase":
        lead_m = speed * horizon * lead
        target_bearing = float(predict.get("direction_deg") or bearing)
        action = "pursue"
        dist = max(0.5, dist - lead_m * 0.1)
    elif pol_id == "orbit":
        target_bearing = _normalize_bearing(bearing + float(pol.get("orbit_deg", 90)))
        action = "orbit"
    elif pol_id == "shadow":
        target_bearing = _normalize_bearing(bearing + float(pol.get("offset_bearing_deg", 30)))
        action = "shadow"
    else:
        target_bearing = bearing
        action = "hold_lock"

    spawn_ve = bool(pol.get("spawn_virtual_ear", False))
    return {
        "policy": pol_id,
        "policy_label": pol.get("label", pol_id),
        "action": action,
        "target_bearing_deg": round(target_bearing, 1),
        "target_distance_m": round(dist, 2),
        "spawn_virtual_ear": spawn_ve,
        "mechanism": "kinetic_eardrum" if spawn_ve else None,
    }


def tick_source(obs: dict[str, Any], *, learn: bool = True) -> dict[str, Any]:
    """Full tick: registry → GPS heading → motion → pursuit."""
    from zocr_sound_registry import register_sound
    from zocr_ear_localize import localize_sources

    doc = load_doctrine()
    op = operator_gps()
    reg = register_sound(obs, neural_label=obs.get("neural_label"))
    sound_id = reg["sound_id"]

    bearing = float(obs.get("bearing_deg") or 0.0)
    level_db = float(obs.get("level_db") or -24.0)
    itd = obs.get("itd_us")
    if itd is not None:
        loc = localize_sources(itd_us=float(itd), level_db=level_db)
        pt = loc.get("point") or {}
        bearing = float(pt.get("bearing_deg") or bearing)
    distance_m = float(obs.get("distance_m") or _distance_from_level(level_db))
    source_gps = bearing_to_gps(lat=op["lat"], lon=op["lon"], bearing_deg=bearing, distance_m=distance_m)

    st = _load_state()
    tracks: dict[str, Any] = dict(st.get("tracks") or {})
    prev = tracks.get(sound_id) or {"history": [], "policy": doc.get("default_policy", "hold")}
    history = list(prev.get("history") or [])
    tick_row = {
        "ts": _ts(),
        "bearing_deg": bearing,
        "distance_m": distance_m,
        "level_db": level_db,
        "ingress_lane": obs.get("ingress_lane"),
    }
    history.append(tick_row)
    max_hist = int((doc.get("motion") or {}).get("history_ticks", 12))
    history = history[-max_hist:]

    motion = predict_motion(history, cfg=doc)
    predict = {
        **motion,
        "predicted_lat": source_gps["lat"],
        "predicted_lon": source_gps["lon"],
        "predicted_bearing_deg": motion["direction_deg"],
    }
    if motion.get("is_moving") and motion.get("speed_mps"):
        lead = motion["speed_mps"] * float(motion.get("horizon_s", 3.0))
        pred_gps = bearing_to_gps(
            lat=op["lat"],
            lon=op["lon"],
            bearing_deg=motion["direction_deg"],
            distance_m=distance_m + lead,
        )
        predict["predicted_lat"] = pred_gps["lat"]
        predict["predicted_lon"] = pred_gps["lon"]

    track = {
        "sound_id": sound_id,
        "label": obs.get("label") or reg["entry"].get("label"),
        "ingress_lane": obs.get("ingress_lane"),
        "source_key": obs.get("source_key"),
        "bearing_deg": round(bearing, 1),
        "heading_deg": round(bearing, 1),
        "distance_m": distance_m,
        "level_db": level_db,
        "operator_gps": op,
        "source_gps": source_gps,
        "gps_heading": {
            "lat": source_gps["lat"],
            "lon": source_gps["lon"],
            "bearing_from_operator_deg": round(bearing, 1),
            "operator_heading_deg": op.get("heading_deg", 0.0),
        },
        "motion": motion,
        "predict": predict,
        "policy": prev.get("policy", doc.get("default_policy", "hold")),
        "history_len": len(history),
        "history": history[-4:],
        "neural_network_id": reg["entry"].get("neural_network_id"),
        "permanent": True,
        "updated": _ts(),
    }
    track["pursuit"] = apply_pursuit_policy(track, doctrine=doc)
    tracks[sound_id] = {**track, "history": history}
    st["tracks"] = tracks
    st["operator_gps"] = op
    _save_state(st)

    learn_out = {}
    if learn:
        try:
            from zocr_sound_learn import learn_from_observation
            learn_out = learn_from_observation(track)
        except ImportError:
            learn_out = {"ok": False, "skipped": "learn_module"}
        except Exception as exc:
            learn_out = {"ok": True, "degraded": True, "detail": str(exc)[:80]}

    return {
        "ok": True,
        "schema": "zocr-sound-tick/v1",
        "sound_id": sound_id,
        "track": track,
        "registry": reg,
        "learn": learn_out,
        "never_fail": True,
    }


def ingest_observations(observations: list[dict[str, Any]], *, learn: bool = True) -> dict[str, Any]:
    ticks = [tick_source(obs, learn=learn) for obs in observations]
    return {
        "ok": True,
        "schema": "zocr-sound-ingest/v1",
        "updated": _ts(),
        "count": len(ticks),
        "tracks": [t["track"] for t in ticks],
        "sound_ids": [t["sound_id"] for t in ticks],
        "never_fail": True,
    }


def set_pursuit_policy(sound_id: str, policy: str) -> dict[str, Any]:
    doc = load_doctrine()
    policies = doc.get("pursuit_policies") or {}
    if policy not in policies:
        return {"ok": False, "error": "unknown_policy", "available": list(policies.keys())}
    st = _load_state()
    tracks = dict(st.get("tracks") or {})
    if sound_id not in tracks:
        return {"ok": False, "error": "unknown_sound_id", "sound_id": sound_id}
    tracks[sound_id]["policy"] = policy
    tracks[sound_id]["pursuit"] = apply_pursuit_policy(tracks[sound_id], policy=policy, doctrine=doc)
    tracks[sound_id]["updated"] = _ts()
    st["tracks"] = tracks
    _save_state(st)
    return {"ok": True, "sound_id": sound_id, "policy": policy, "pursuit": tracks[sound_id]["pursuit"]}


def _harvest_antenna_lane() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    state_dirs = [
        Path(os.environ.get("NEXUS_STATE_DIR", _ROOT / ".nexus-state")),
        Path("/var/lib/nexus-shield"),
        _ROOT.parent / ".nexus-state",
    ]
    for base in state_dirs:
        panel = base / "field-antenna-panel.json"
        if not panel.is_file():
            continue
        ant = _read(panel, {})
        for pt in (ant.get("points") or ant.get("sources") or [])[:12]:
            rows.append({
                "ingress_lane": "antenna",
                "source_key": f"antenna:{pt.get('id', pt.get('band', 'ota'))}",
                "label": pt.get("label") or pt.get("band") or "antenna OTA",
                "kind": "rf_audio",
                "bearing_deg": float(pt.get("bearing_deg") or pt.get("azimuth_deg") or 0),
                "level_db": float(pt.get("level_db") or -28.0),
                "distance_m": float(pt.get("distance_m") or 50.0),
            })
        if rows:
            break
    return rows


def _harvest_virtual_ear_lane() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from zocr_virtual_ear import virtual_ear_status
        virtual = virtual_ear_status()
        for ear in (virtual.get("virtual_ears") or []):
            if not ear.get("enabled", True):
                continue
            pt = ear.get("point") or {}
            rows.append({
                "ingress_lane": "virtual_ear",
                "source_key": f"ve:{ear.get('id')}",
                "label": ear.get("label") or ear.get("mechanism"),
                "kind": "virtual",
                "bearing_deg": float(pt.get("bearing_deg") or 0),
                "distance_m": float(pt.get("distance_m") or 2.0),
                "level_db": -22.0,
            })
    except ImportError:
        pass
    return rows


def sense_all(*, learn: bool = True, include_desktop: bool = True) -> dict[str, Any]:
    """All hearing methods — desktop, antenna, virtual ear; never fails."""
    observations: list[dict[str, Any]] = []
    lanes: dict[str, int] = {}

    if include_desktop:
        try:
            from zocr_desktop_audio import harvest_desktop_sources
            obs = harvest_desktop_sources()
            observations.extend(obs)
            lanes["desktop"] = len(obs)
        except Exception:
            lanes["desktop"] = 0

    ant = _harvest_antenna_lane()
    observations.extend(ant)
    lanes["antenna"] = len(ant)

    ve = _harvest_virtual_ear_lane()
    observations.extend(ve)
    lanes["virtual_ear"] = len(ve)

    if not observations:
        observations.append({
            "ingress_lane": "mic",
            "source_key": "mic:default",
            "label": "Ambient field",
            "kind": "ambient",
            "bearing_deg": 0.0,
            "level_db": -30.0,
        })
        lanes["mic"] = 1

    result = ingest_observations(observations, learn=learn)
    result["lanes"] = lanes
    result["operator_gps"] = operator_gps()
    result["ingress_total"] = len(observations)
    return result


def tracker_status() -> dict[str, Any]:
    doc = load_doctrine()
    st = _load_state()
    tracks = list((st.get("tracks") or {}).values())
    tracks.sort(key=lambda t: t.get("updated") or "", reverse=True)
    try:
        from zocr_sound_registry import registry_status
        registry = registry_status()
    except ImportError:
        registry = {}
    return {
        "ok": True,
        "schema": "zocr-sound-tracker-status/v1",
        "updated": st.get("updated") or _ts(),
        "doctrine": doc.get("rule"),
        "posture": doc.get("posture"),
        "operator_gps": st.get("operator_gps") or operator_gps(),
        "track_count": len(tracks),
        "tracks": [
            {
                "sound_id": t.get("sound_id"),
                "label": t.get("label"),
                "ingress_lane": t.get("ingress_lane"),
                "heading_deg": t.get("heading_deg"),
                "gps_heading": t.get("gps_heading"),
                "motion": t.get("motion"),
                "predict": t.get("predict"),
                "policy": t.get("policy"),
                "pursuit": t.get("pursuit"),
                "permanent": t.get("permanent"),
            }
            for t in tracks[:24]
        ],
        "policies": list((doc.get("pursuit_policies") or {}).keys()),
        "ingress_lanes": doc.get("ingress_lanes"),
        "registry": registry.get("stats"),
        "never_fail": True,
        "zero_cost": True,
    }