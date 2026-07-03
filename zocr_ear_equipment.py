"""Audio equipment catalog — consumer to obscure field mics."""
from __future__ import annotations

from typing import Any

from zocr_ear import list_profiles, load_doctrine, active_profile


def equipment_catalog(*, obscure_only: bool = False) -> dict[str, Any]:
    profiles = list_profiles()
    if obscure_only:
        profiles = [p for p in profiles if p.get("class") == "obscure"]
    doc = load_doctrine()
    return {
        "schema": "zocr-ear-equipment/v1",
        "active_profile": active_profile(),
        "total": len(profiles),
        "obscure_count": sum(1 for p in profiles if p.get("class") == "obscure"),
        "profiles": profiles,
        "doctrine": doc.get("doctrine"),
        "support": "All equipment paths — consumer, studio, array, obscure heritage and field sensors",
    }


def equipment_resolve(profile_id: str) -> dict[str, Any]:
    doc = load_doctrine()
    p = (doc.get("profiles") or {}).get(profile_id)
    if not p:
        return {"ok": False, "error": "unknown_profile", "profile_id": profile_id}
    return {"ok": True, "id": profile_id, **p}