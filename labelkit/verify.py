"""Compare an LCSC description claim with the web provider's data.

Rules:

* the provider's category is authoritative for the part type;
* overlapping fields must agree (within 1 ppm for numeric values);
* missing provider fields are filled from the description and recorded as
  unconfirmed, but do not block on their own;
* any disagreement is a hard mismatch -- the row is blocked and surfaced
  in ``review.csv`` (or resolved by a human when interactive).
"""

from __future__ import annotations

from .model import Part, PartType, ProviderResult, Status
from .values import (
    dielectric_key,
    normalize_package,
    parse_quantity,
)

CHECK_FIELDS = (
    "value",
    "rating",
    "tolerance",
    "dielectric",
    "package",
    "current",
    "load",
    "stability",
)
NUMERIC_FIELDS = {"value", "rating", "tolerance", "current", "load"}

# Descriptive fields used by the generated description, not verification.
EXTRA_FIELDS = (
    "kind",
    "color",
    "polarity",
    "type_word",
    "channels",
    "resolution",
    "bandwidth",
    "supply",
    "topology",
    "core",
    "speed",
    "flash",
)

REQUIRED_FIELDS: dict[PartType, tuple[str, ...]] = {
    PartType.RESISTOR: ("value",),
    PartType.CAPACITOR: ("value",),
    PartType.INDUCTOR: ("value",),
    PartType.CRYSTAL: ("value",),
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).upper()


def _numeric_equal(a, b) -> bool | None:
    if a is None or b is None:
        return None
    if a.unit != b.unit:
        return False
    denom = max(abs(a.value), abs(b.value), 1e-18)
    return abs(a.value - b.value) / denom <= 1e-6


def _text_quantity(text: str, field: str, part_type: PartType):
    default = {
        "value": {
            PartType.RESISTOR: "ohm",
            PartType.CAPACITOR: "F",
            PartType.INDUCTOR: "H",
            PartType.CRYSTAL: "Hz",
        }.get(part_type),
        "rating": {
            PartType.RESISTOR: "W",
            PartType.CAPACITOR: "V",
            PartType.INDUCTOR: "A",
            PartType.DIODE: "V",
            PartType.LED: "V",
            PartType.TRANSISTOR: "V",
        }.get(part_type),
        "tolerance": "%",
        "current": "A",
        "load": "F",
    }.get(field)
    return parse_quantity(text, default_unit=default)


def _fields_equal(part: Part, provider: ProviderResult, field: str) -> bool:
    d_text = part.get(field)
    w_text = provider.get(field)

    if field in NUMERIC_FIELDS:
        result = _numeric_equal(part.values.get(field), provider.values.get(field))
        if result is not None:
            return result
        dq = _text_quantity(d_text, field, part.type)
        wq = _text_quantity(w_text, field, part.type)
        if dq is not None and wq is not None:
            result = _numeric_equal(dq, wq)
            if result is not None:
                return result

    if field == "dielectric":
        return dielectric_key(d_text) == dielectric_key(w_text)
    if field == "package":
        return normalize_package(d_text, part_type=part.type) == normalize_package(
            w_text, part_type=part.type
        )

    return _norm(d_text) == _norm(w_text)


def merge(part: Part, provider: ProviderResult) -> Part:
    """Fill/verify ``part`` against ``provider`` in place."""
    part.extra["provider"] = provider
    mismatches: list[tuple[str, str, str]] = []

    # ---- type --------------------------------------------------------
    if part.type is PartType.UNKNOWN:
        part.type = provider.type
        part.confidence = max(part.confidence, 0.8)
    elif provider.type is not PartType.UNKNOWN and part.type is not provider.type:
        mismatches.append(("type", part.type.value, provider.type.value))

    # ---- overlapping fields -----------------------------------------
    for field in CHECK_FIELDS:
        w_text = provider.get(field)
        if not w_text:
            continue
        d_text = part.get(field)
        if not d_text:
            part.set_attr(field, w_text, provider.provider)
            if field in provider.values:
                part.values[field] = provider.values[field]
            else:
                quantity = _text_quantity(w_text, field, part.type)
                if quantity is not None:
                    part.values[field] = quantity
            continue
        if not _fields_equal(part, provider, field):
            mismatches.append((field, d_text, w_text))

    for field in EXTRA_FIELDS:
        web_value = provider.get(field)
        if web_value and not part.get(field):
            part.set_attr(field, web_value, provider.provider)

    # ---- identity ----------------------------------------------------
    if not part.manufacturer and provider.manufacturer:
        part.manufacturer = provider.manufacturer
    if not part.datasheet and provider.datasheet:
        part.datasheet = provider.datasheet

    # ---- unconfirmed (provider had nothing to say) -------------------
    unconfirmed = sorted(
        f
        for f in part.attrs
        if f in {"value", "rating", "tolerance", "dielectric", "package", "current", "load", "stability"}
        and not provider.get(f)
    )
    if unconfirmed:
        part.extra["unconfirmed_fields"] = unconfirmed

    if mismatches:
        part.extra["mismatches"] = mismatches
        for field, d_text, w_text in mismatches:
            part.issues.append(f"{field}: LCSC {d_text} vs {provider.provider} {w_text}")
        part.status = Status.MISMATCH
        return part

    part.status = Status.VERIFIED
    part.verified_by = provider.provider
    part.issues = [
        issue
        for issue in part.issues
        if not issue.startswith("could not determine part type")
    ]

    if part.type is PartType.UNKNOWN:
        part.status = Status.BLOCKED
        part.issues.append("could not determine part type after verification")
        return part

    missing = [f for f in REQUIRED_FIELDS.get(part.type, ()) if not part.get(f)]
    if missing:
        part.status = Status.BLOCKED
        part.issues.append(f"missing {', '.join(missing)} after verification")

    return part


def supplement(part: Part, provider: ProviderResult, *, strict: bool = False) -> Part:
    """Let a secondary source fill gaps without overriding the primary.

    Used for LCSC behind DigiKey: DigiKey values win, LCSC fills missing
    fields and supplies the LCSC part number.  Disagreements are recorded
    in ``part.extra["conflicts"]`` and surfaced in review.csv.  With
    ``strict=True`` a disagreement blocks the row instead.
    """
    conflicts: list[tuple[str, str, str]] = []

    for field in CHECK_FIELDS:
        web_value = provider.get(field)
        if not web_value:
            continue
        current = part.get(field)
        if not current:
            part.set_attr(field, web_value, provider.provider)
            if field in provider.values:
                part.values[field] = provider.values[field]
            else:
                quantity = _text_quantity(web_value, field, part.type)
                if quantity is not None:
                    part.values[field] = quantity
            continue
        if not _fields_equal(part, provider, field):
            conflicts.append((field, current, web_value))

    for field in EXTRA_FIELDS:
        web_value = provider.get(field)
        if web_value and not part.get(field):
            part.set_attr(field, web_value, provider.provider)

    if part.type is PartType.UNKNOWN and provider.type is not PartType.UNKNOWN:
        part.type = provider.type
    if not part.manufacturer and provider.manufacturer:
        part.manufacturer = provider.manufacturer
    if not part.datasheet and provider.datasheet:
        part.datasheet = provider.datasheet
    if not part.supplier_pn and provider.supplier_pn:
        part.supplier_pn = provider.supplier_pn

    if conflicts:
        part.extra["conflicts"] = conflicts
        for field, current, web_value in conflicts:
            note = (
                f"{provider.provider} {field} {web_value} "
                f"differs from DigiKey {current}"
            )
            if note not in part.issues:
                part.issues.append(note)
        if strict:
            part.status = Status.MISMATCH
        return part

    # If the primary source blocked only because a required field was
    # missing, the secondary source may have supplied it.
    if part.status is Status.BLOCKED:
        missing = [
            name
            for name in REQUIRED_FIELDS.get(part.type, ())
            if not part.get(name)
        ]
        if not missing and part.type is not PartType.UNKNOWN:
            part.status = Status.VERIFIED
            part.issues = [
                issue
                for issue in part.issues
                if not issue.startswith("missing ")
                and not issue.startswith("could not determine part type")
            ]

    return part
