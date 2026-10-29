"""Capability normalisation and print-settings validation.

Capabilities are read from the printer's IPP attributes as reported by CUPS.
Settings are validated strictly: an unsupported value is an error, never
silently replaced by something else.
"""
from __future__ import annotations

import re
from typing import Any

UI_MAX_COPIES = 999

SIDES_LABELS = {
    "one-sided": "Single-sided",
    "two-sided-long-edge": "Double-sided, flip on long edge",
    "two-sided-short-edge": "Double-sided, flip on short edge",
}
COLOR_LABELS = {"color": "Color", "monochrome": "Black & white", "auto": "Automatic", "bi-level": "Black & white (no gray)", "process-monochrome": "Black & white (process)"}
QUALITY_ENUM = {3: "draft", 4: "normal", 5: "high"}
QUALITY_LABELS = {"draft": "Draft", "normal": "Normal", "high": "High"}
SCALING_LABELS = {
    "fit": "Fit to page",
    "none": "Actual size",
    "fill": "Fill page (may crop)",
    "auto": "Automatic",
    "auto-fit": "Shrink only if needed",
}
ORIENTATION_ENUM = {3: "portrait", 4: "landscape"}
FINISHINGS = {
    4: "Staple", 5: "Punch holes", 6: "Cover", 7: "Bind", 8: "Saddle stitch", 9: "Edge stitch", 10: "Fold",
    20: "Staple top left", 21: "Staple bottom left", 22: "Staple top right", 23: "Staple bottom right",
    28: "Dual staple left", 29: "Dual staple top", 30: "Dual staple right", 31: "Dual staple bottom",
    50: "Bind left", 51: "Bind top", 52: "Bind right", 53: "Bind bottom",
    70: "Punch top left", 74: "Dual punch left", 75: "Dual punch top", 78: "Triple punch left", 79: "Triple punch top",
    90: "Z-fold", 93: "Half fold", 94: "Letter fold", 100: "Trim",
}
MEDIA_NAMES = {
    "na_letter": "Letter", "na_legal": "Legal", "na_ledger": "Tabloid", "na_executive": "Executive",
    "na_invoice": "Statement", "na_govt-letter": "Government letter", "na_govt-legal": "Government legal",
    "na_foolscap": "Foolscap", "na_oficio": "Oficio", "na_index-3x5": "Index card 3×5", "na_index-4x6": "Photo 4×6",
    "na_5x7": "Photo 5×7", "na_number-10": "Envelope #10", "na_monarch": "Envelope Monarch",
    "iso_a3": "A3", "iso_a4": "A4", "iso_a5": "A5", "iso_a6": "A6", "iso_c5": "Envelope C5", "iso_dl": "Envelope DL",
    "jis_b5": "B5 (JIS)", "iso_b5": "B5",
}
SOURCE_LABELS = {
    "auto": "Automatic", "main": "Main tray", "manual": "Manual feed", "by-pass-tray": "Bypass tray",
    "envelope": "Envelope feeder", "photo": "Photo tray", "large-capacity": "Large capacity tray",
}
TYPE_LABELS = {
    "auto": "Automatic", "stationery": "Plain paper", "stationery-lightweight": "Lightweight paper",
    "stationery-heavyweight": "Heavyweight paper", "stationery-prepunched": "Pre-punched paper",
    "stationery-letterhead": "Letterhead", "envelope": "Envelope", "labels": "Labels", "transparency": "Transparency",
    "photographic": "Photo paper", "photographic-glossy": "Glossy photo paper", "photographic-matte": "Matte photo paper",
    "cardstock": "Cardstock",
}
FORMAT_KEYS = {"application/pdf": "pdf", "image/jpeg": "jpeg", "image/png": "png", "image/pwg-raster": "pwg"}

_MEDIA_RE = re.compile(r"^(?P<cls>[a-z0-9]+)_(?P<name>[a-z0-9.\-]+)_(?P<w>[\d.]+)x(?P<h>[\d.]+)(?P<unit>mm|in)$")


def parse_media(key: str) -> dict[str, Any] | None:
    m = _MEDIA_RE.match(key)
    if not m:
        return None
    w, h = float(m["w"]), float(m["h"])
    if m["unit"] == "in":
        w, h = w * 25.4, h * 25.4
    return {"width_mm": round(w, 1), "height_mm": round(h, 1)}


def media_label(key: str) -> str:
    m = _MEDIA_RE.match(key)
    if not m:
        return key
    base = f"{m['cls']}_{m['name']}"
    if base in MEDIA_NAMES:
        return MEDIA_NAMES[base]
    dims = f"{m['w']}×{m['h']} {m['unit']}"
    return f"{m['name'].replace('-', ' ').title()} ({dims})"


def _keyword_label(value: str, table: dict[str, str]) -> str:
    if value in table:
        return table[value]
    if value.startswith("tray-"):
        return "Tray " + value[5:]
    return value.replace("-", " ").capitalize()


def _first(attrs: dict[str, list[Any]], name: str, default: Any = None) -> Any:
    values = attrs.get(name) or []
    return values[0] if values and values[0] is not None else default


def normalize_ipp(attrs: dict[str, list[Any]]) -> dict[str, Any]:
    """Turn raw IPP printer attributes into the hub's capability description."""
    caps: dict[str, Any] = {"source": "ipp"}

    copies = _first(attrs, "copies-supported")
    is_range = isinstance(copies, (tuple, list)) and len(copies) == 2
    caps["copies"] = {"min": 1, "max": min(int(copies[1]), UI_MAX_COPIES)} if is_range else None

    caps["color_modes"] = [
        {"key": v, "label": _keyword_label(v, COLOR_LABELS)}
        for v in attrs.get("print-color-mode-supported", [])
        if v in ("color", "monochrome")
    ]
    caps["sides"] = [
        {"key": v, "label": SIDES_LABELS[v]} for v in attrs.get("sides-supported", []) if v in SIDES_LABELS
    ]

    media = []
    seen = set()
    for key in attrs.get("media-supported", []):
        if not isinstance(key, str) or key.startswith("custom_") or "fullbleed" in key:
            continue
        dims = parse_media(key)
        if not dims or key in seen:
            continue
        seen.add(key)
        media.append({"key": key, "label": media_label(key), **dims})
    caps["media"] = media

    orientations = [ORIENTATION_ENUM[v] for v in attrs.get("orientation-requested-supported", []) if v in ORIENTATION_ENUM]
    caps["orientations"] = [{"key": o, "label": o.capitalize()} for o in orientations]
    caps["page_ranges"] = bool(_first(attrs, "page-ranges-supported", False))
    caps["scaling"] = [
        {"key": v, "label": SCALING_LABELS[v]} for v in attrs.get("print-scaling-supported", []) if v in ("fit", "none", "fill")
    ]
    caps["media_sources"] = [
        {"key": v, "label": _keyword_label(v, SOURCE_LABELS)} for v in attrs.get("media-source-supported", []) if isinstance(v, str)
    ]
    caps["media_types"] = [
        {"key": v, "label": _keyword_label(v, TYPE_LABELS)} for v in attrs.get("media-type-supported", []) if isinstance(v, str)
    ]
    caps["qualities"] = [
        {"key": QUALITY_ENUM[v], "label": QUALITY_LABELS[QUALITY_ENUM[v]]}
        for v in attrs.get("print-quality-supported", [])
        if v in QUALITY_ENUM
    ]
    handling = attrs.get("multiple-document-handling-supported", [])
    caps["collate"] = "separate-documents-collated-copies" in handling and "separate-documents-uncollated-copies" in handling
    caps["finishings"] = [
        {"key": str(v), "label": FINISHINGS[v]} for v in attrs.get("finishings-supported", []) if v in FINISHINGS
    ]
    formats = set(attrs.get("document-format-supported", []))
    caps["formats"] = {key: (mime in formats) for mime, key in FORMAT_KEYS.items() if key != "pwg"}
    if "application/octet-stream" in formats and not any(caps["formats"].values()):
        caps["formats"] = {"pdf": True, "jpeg": True, "png": True}

    quality_default = _first(attrs, "print-quality-default")
    orientation_default = _first(attrs, "orientation-requested-default")
    caps["defaults"] = {
        k: v
        for k, v in {
            "color_mode": _first(attrs, "print-color-mode-default"),
            "sides": _first(attrs, "sides-default"),
            "media": _first(attrs, "media-default"),
            "media_source": _first(attrs, "media-source-default"),
            "media_type": _first(attrs, "media-type-default"),
            "quality": QUALITY_ENUM.get(quality_default) if quality_default else None,
            "orientation": ORIENTATION_ENUM.get(orientation_default) if orientation_default else None,
            "scaling": _first(attrs, "print-scaling-default"),
        }.items()
        if v is not None
    }
    return caps


SETTING_KEYS = (
    "copies", "color_mode", "sides", "media", "orientation", "scaling",
    "media_source", "media_type", "quality", "collate", "finishings",
)
SETTING_LABELS = {
    "copies": "Copies", "color_mode": "Color", "sides": "Sides", "media": "Paper size", "orientation": "Orientation",
    "scaling": "Scaling", "media_source": "Paper tray", "media_type": "Paper type", "quality": "Quality",
    "collate": "Collation", "finishings": "Finishing", "page_ranges": "Page range",
}
_CHOICE_KEYS = {
    "color_mode": "color_modes", "sides": "sides", "media": "media", "orientation": "orientations",
    "scaling": "scaling", "media_source": "media_sources", "media_type": "media_types", "quality": "qualities",
}


def validate_settings(settings: dict[str, Any], caps: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (clean settings, errors). Unset/None values mean "printer default"."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in (settings or {}).items():
        if key not in SETTING_KEYS:
            errors[key] = "Unknown setting."
            continue
        if value is None or value == "" or value == []:
            continue
        label = SETTING_LABELS[key]
        if key == "copies":
            limits = caps.get("copies")
            if not limits:
                if value != 1:
                    errors[key] = "This printer does not report support for multiple copies."
                continue
            if not isinstance(value, int) or isinstance(value, bool) or not limits["min"] <= value <= limits["max"]:
                errors[key] = f"Copies must be between {limits['min']} and {limits['max']}."
                continue
            clean[key] = value
        elif key == "collate":
            if not isinstance(value, bool):
                errors[key] = "Collation must be on or off."
            elif not caps.get("collate"):
                errors[key] = "This printer does not report collation control."
            else:
                clean[key] = value
        elif key == "finishings":
            allowed = {f["key"] for f in caps.get("finishings", [])}
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors[key] = "Finishing must be a list."
            elif bad := [v for v in value if v not in allowed]:
                errors[key] = f"This printer does not support finishing option(s): {', '.join(bad)}."
            else:
                clean[key] = sorted(set(value))
        else:
            allowed = {c["key"] for c in caps.get(_CHOICE_KEYS[key], [])}
            if value not in allowed:
                errors[key] = f"{label} “{value}” is not supported by this printer." if allowed else f"This printer does not report {label.lower()} options."
            else:
                clean[key] = value
    return clean, errors


_RANGE_RE = re.compile(r"^\s*\d+\s*(-\s*\d+\s*)?(,\s*\d+\s*(-\s*\d+\s*)?)*$")


def normalize_page_ranges(text: str | None, pages: int | None) -> tuple[str | None, str | None]:
    """Validate a page range like "1-3, 5". Returns (normalized, error)."""
    if text is None or not str(text).strip():
        return None, None
    text = str(text)
    if not _RANGE_RE.match(text):
        return None, "Use page numbers and ranges like 1-3, 5."
    parts = []
    for chunk in text.split(","):
        bits = [int(b) for b in chunk.replace(" ", "").split("-")]
        start, end = bits[0], bits[-1]
        if start < 1 or end < start:
            return None, f"“{chunk.strip()}” is not a valid range."
        if pages and end > pages:
            return None, f"This document has {pages} page{'s' if pages != 1 else ''}; “{chunk.strip()}” is past the end."
        parts.append((start, end))
    parts.sort()
    return ",".join(f"{a}-{b}" if a != b else str(a) for a, b in parts), None


def count_selected_pages(ranges: str | None, pages: int | None) -> int | None:
    if not ranges:
        return pages
    total = 0
    for chunk in ranges.split(","):
        a, _, b = chunk.partition("-")
        total += (int(b) if b else int(a)) - int(a) + 1
    return total


def to_ipp_options(settings: dict[str, Any], page_ranges: str | None) -> tuple[dict[str, str], int]:
    """Map validated hub settings to CUPS job options. Returns (options, copies)."""
    opts: dict[str, str] = {}
    if "color_mode" in settings:
        opts["print-color-mode"] = settings["color_mode"]
    if "sides" in settings:
        opts["sides"] = settings["sides"]
    if "media" in settings:
        opts["media"] = settings["media"]
    if "orientation" in settings:
        opts["orientation-requested"] = {"portrait": "3", "landscape": "4"}[settings["orientation"]]
    if "scaling" in settings:
        opts["print-scaling"] = settings["scaling"]
    if "media_source" in settings:
        opts["media-source"] = settings["media_source"]
    if "media_type" in settings:
        opts["media-type"] = settings["media_type"]
    if "quality" in settings:
        opts["print-quality"] = {"draft": "3", "normal": "4", "high": "5"}[settings["quality"]]
    if "collate" in settings:
        opts["multiple-document-handling"] = (
            "separate-documents-collated-copies" if settings["collate"] else "separate-documents-uncollated-copies"
        )
    if settings.get("finishings"):
        opts["finishings"] = ",".join(settings["finishings"])
    if page_ranges:
        opts["page-ranges"] = page_ranges
    return opts, int(settings.get("copies", 1))


def check_preset(preset: dict[str, Any], caps: dict[str, Any]) -> dict[str, Any]:
    """Split a preset into the settings this printer supports and the ones it does not."""
    applicable, problems = {}, {}
    for key, value in preset.items():
        clean, errors = validate_settings({key: value}, caps)
        if errors:
            problems[key] = errors.get(key, "Not supported.")
        else:
            applicable.update(clean)
    return {"applicable": applicable, "unsupported": problems}


def describe_settings(settings: dict[str, Any], caps: dict[str, Any]) -> list[list[str]]:
    """[[label, value label], ...] using the printer's own names for each option."""
    out = []
    for key in SETTING_KEYS:
        if key not in settings:
            continue
        value = settings[key]
        if key == "copies":
            text = str(value)
        elif key == "collate":
            text = "Collated" if value else "Uncollated"
        elif key == "finishings":
            names = {f["key"]: f["label"] for f in caps.get("finishings", [])}
            text = ", ".join(names.get(v, v) for v in value) or "None"
        else:
            names = {c["key"]: c["label"] for c in caps.get(_CHOICE_KEYS[key], [])}
            text = names.get(value, value)
        out.append([SETTING_LABELS[key], text])
    return out
