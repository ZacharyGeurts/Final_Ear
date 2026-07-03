"""ZOCRAM1 + GAC1 format constants."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = _ROOT / "data" / "gac1-v1.json"

FORMAT_ID = "ZOCRAM1"
CODEC_ID = "GAC1"
MAGIC = b"ZOCR"
FRAME_MAGIC = b"GAC1"

# GAC1 frame kinds
FRAME_KEY = 1          # zlib PCM keyframe
FRAME_PRED = 2         # zlib int16 delta from previous frame
FRAME_SILENCE = 3      # run of zeros — cochlear-rest friendly
FLAG_LOSSLESS = 1
FLAG_BINAURAL = 2
FLAG_COCHLEAR_SAFE = 4
FLAG_SOVEREIGN_SEAL = 8

DEFAULT_FRAME_SAMPLES = 1024
DEFAULT_GOP = 32


def load_spec() -> dict[str, Any]:
    try:
        return json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "format_id": FORMAT_ID,
            "codec_id": CODEC_ID,
            "profiles": {
                "lossless": {"gop": 1, "silence_threshold": 0, "cochlear_limit_db": None},
                "fast": {"gop": 48, "silence_threshold": 8, "cochlear_limit_db": None},
                "binaural_safe": {"gop": 32, "silence_threshold": 4, "cochlear_limit_db": -1.0},
                "cochlear_safe": {"gop": 32, "silence_threshold": 4, "cochlear_limit_db": -3.0},
                "patrol": {"gop": 64, "silence_threshold": 12, "cochlear_limit_db": -6.0},
            },
        }


def profile(name: str) -> dict[str, Any]:
    spec = load_spec()
    profiles = spec.get("profiles") or {}
    return profiles.get(name, profiles.get("binaural_safe", {"gop": 32}))