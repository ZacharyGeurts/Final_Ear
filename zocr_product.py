"""Final_Ear product metadata — sovereign robotics hearing release."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_VERSION_FILE = _ROOT / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "1.0.0"


PRODUCT_ID = "Final_Ear"
PRODUCT_NAME = "The Final Ear"
VERSION = _read_version()
SCHEMA = "final-ear-product/v1"
CODENAME = "ear-stoard"
LICENSE = "proprietary"
REPO = "https://github.com/ZacharyGeurts/Final_Ear"


def product_info() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "product": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "version": VERSION,
        "codename": CODENAME,
        "license": LICENSE,
        "repo": REPO,
        "format": "ZOCRAM1",
        "codec": "GAC1",
        "rule": "We never presume hearing loss. Confidence always in Hearing.",
        "twins": {"living": "Auditus", "truth": "Veritas"},
        "textbook": "docs/index.html",
        "field_manual": "data/field-manual-index.json",
    }