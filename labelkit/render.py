"""CSV and JSON writers.

The per-template CSV is the artifact handed to the printer (today: a
P-touch Editor database merge; later: the b-PAC/ptouch-print backends).
``parts.csv`` and ``review.csv`` are for humans and for auditing what was
blocked and why.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .model import Part, PartType, Status
from .templates import Template

TYPE_ORDER = {
    PartType.RESISTOR: 0,
    PartType.CAPACITOR: 1,
    PartType.INDUCTOR: 2,
    PartType.DIODE: 3,
    PartType.LED: 4,
    PartType.TRANSISTOR: 5,
    PartType.CRYSTAL: 6,
    PartType.IC: 7,
    PartType.UNKNOWN: 8,
}


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._")
    return cleaned or "labels"


def value_sort_key(part: Part):
    quantity = part.values.get("value")
    numeric = quantity.value if quantity is not None else float("inf")
    return (numeric, part.attrs.get("package", ""), part.mpn.upper())


def text_sort_key(part: Part):
    return (part.attrs.get("value", ""), part.attrs.get("package", ""), part.mpn.upper())


def sort_parts(parts: list[Part], mode: str = "value") -> list[Part]:
    if mode == "none":
        return list(parts)
    if mode == "text":
        return sorted(parts, key=text_sort_key)
    return sorted(parts, key=value_sort_key)


def write_template_csv(
    path: str | Path,
    template: Template,
    parts: list[Part],
    sort: str = "value",
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ordered = sort_parts(parts, sort)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(template.headers)
        for part in ordered:
            writer.writerow(template.row(part))
    return out


def write_parts_csv(path: str | Path, parts: list[Part]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "status",
        "type",
        "source",
        "supplier_pn",
        "mpn",
        "manufacturer",
        "qty",
        "description",
        "source_description",
        "value",
        "rating",
        "tolerance",
        "dielectric",
        "package",
        "current",
        "load",
        "stability",
        "color",
        "polarity",
        "datasheet",
        "unconfirmed_fields",
        "conflicts",
        "issues",
    ]
    ordered = sorted(
        parts,
        key=lambda p: (TYPE_ORDER.get(p.type, 9),) + value_sort_key(p),
    )
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for part in ordered:
            writer.writerow(
                [
                    part.status.value,
                    part.type.value,
                    part.source,
                    part.supplier_pn,
                    part.mpn,
                    part.manufacturer,
                    part.qty or "",
                    part.description,
                    part.source_description,
                    part.attrs.get("value", ""),
                    part.attrs.get("rating", ""),
                    part.attrs.get("tolerance", ""),
                    part.attrs.get("dielectric", ""),
                    part.attrs.get("package", ""),
                    part.attrs.get("current", ""),
                    part.attrs.get("load", ""),
                    part.attrs.get("stability", ""),
                    part.attrs.get("color", ""),
                    part.attrs.get("polarity", ""),
                    part.datasheet,
                    " ".join(part.extra.get("unconfirmed_fields", [])),
                    " | ".join(
                        f"{field}: {web_value}"
                        for field, _current, web_value in part.extra.get(
                            "conflicts", []
                        )
                    ),
                    " | ".join(part.issues),
                ]
            )
    return out


def write_review_csv(path: str | Path, parts: list[Part]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "status",
        "type",
        "supplier_pn",
        "mpn",
        "description",
        "source_description",
        "conflicts",
        "issues",
        "datasheet",
    ]
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for part in parts:
            conflicts = part.extra.get("conflicts") or []
            if part.status is Status.VERIFIED and not conflicts:
                continue
            writer.writerow(
                [
                    part.status.value,
                    part.type.value,
                    part.supplier_pn,
                    part.mpn,
                    part.description,
                    part.source_description,
                    " | ".join(
                        f"{field}: {web_value}"
                        for field, _current, web_value in conflicts
                    ),
                    " | ".join(part.issues),
                    part.datasheet,
                ]
            )
    return out


def write_parts_json(path: str | Path, parts: list[Part]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps([part.to_dict() for part in parts], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out
