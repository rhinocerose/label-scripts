"""The single ingest -> verify -> render pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .descriptions import describe
from .model import Part, PartType, Status
from .render import (
    safe_filename,
    write_parts_csv,
    write_parts_json,
    write_review_csv,
    write_template_csv,
)
from .review import review_parts
from .templates import Template, load_templates
from .verify import merge, supplement


@dataclass
class RunResult:
    parts: list[Part]
    printable: list[Part]
    blocked: list[Part]
    outputs: dict[str, Path]
    stats: dict[str, int]
    templates: dict[PartType, Template] = field(default_factory=dict)


def resolve_part(
    part: Part,
    resolver,
    allow_unverified: bool,
    lcsc_resolver=None,
    strict: bool = False,
) -> None:
    """Resolve via LCSC and/or DigiKey, with DigiKey as the primary."""
    errors: list[str] = []
    lcsc_result = None

    # 1. LCSC part number -> MPN (and LCSC attributes)
    if part.supplier_pn and lcsc_resolver is not None:
        try:
            lcsc_result = lcsc_resolver.lookup_by_pn(part.supplier_pn)
        except Exception as exc:  # noqa: BLE001 - surfaced into review.csv
            errors.append(f"LCSC lookup failed: {exc}")
        if lcsc_result is not None:
            part.extra["lcsc_result"] = lcsc_result
            if not part.mpn:
                part.mpn = lcsc_result.mpn
            if not part.manufacturer:
                part.manufacturer = lcsc_result.manufacturer
            if not part.datasheet:
                part.datasheet = lcsc_result.datasheet

    if not part.mpn:
        part.block("no MPN and LCSC could not resolve one")
        return

    if resolver is not None and not resolver.available and resolver.reason_unavailable:
        errors.append(resolver.reason_unavailable)

    # 2. DigiKey by MPN
    digikey_result = None
    if resolver is not None and resolver.available:
        try:
            digikey_result = resolver.lookup(part.mpn)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DigiKey lookup failed: {exc}")

    # 3. LCSC by MPN if we did not already have it
    if lcsc_result is None and lcsc_resolver is not None:
        try:
            lcsc_result = lcsc_resolver.lookup_by_mpn(part.mpn)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"LCSC lookup failed: {exc}")
        if lcsc_result is not None:
            part.extra["lcsc_result"] = lcsc_result

    # 4. Merge, DigiKey primary
    if digikey_result is not None:
        merge(part, digikey_result)
        if lcsc_result is not None:
            supplement(part, lcsc_result, strict=strict)
            if part.status is Status.VERIFIED:
                part.verified_by = "DigiKey+LCSC"
    elif lcsc_result is not None:
        merge(part, lcsc_result)
        if part.status is Status.VERIFIED:
            part.verified_by = "LCSC"
        if not part.supplier_pn and lcsc_result.supplier_pn:
            part.supplier_pn = lcsc_result.supplier_pn
    else:
        reason = "; ".join(errors) or "no web source resolved this part"
        candidates = (
            getattr(resolver, "last_candidates", []) if resolver is not None else []
        )
        detail = f" (DigiKey candidates: {', '.join(candidates)})" if candidates else ""
        if allow_unverified and part.source_description and part.attrs:
            part.issues.append(f"not verified: {reason}{detail}")
        else:
            part.block(f"not verified: {reason}{detail}")


def _merge_duplicate(keep: Part, other: Part) -> None:
    keep.qty += other.qty
    if other.status is Status.VERIFIED and keep.status is not Status.VERIFIED:
        keep.attrs.update(other.attrs)
        keep.values.update(other.values)
        keep.status = other.status
        keep.verified_by = other.verified_by
    elif other.status is Status.VERIFIED and keep.status is Status.VERIFIED:
        if other.attrs != keep.attrs:
            keep.issues.append("duplicate row has differing attributes; kept the first")

    for issue in other.issues:
        if issue not in keep.issues:
            keep.issues.append(issue)

    for name in other.extra.get("unconfirmed_fields", []):
        fields = keep.extra.setdefault("unconfirmed_fields", [])
        if name not in fields:
            fields.append(name)

    if other.project and other.project not in keep.project.split("; "):
        keep.project = "; ".join(x for x in (keep.project, other.project) if x)

    keep.raw.setdefault("duplicates", []).append(other.raw)


def dedupe(parts: list[Part]) -> tuple[list[Part], int]:
    merged: dict[tuple[str, str], Part] = {}
    order: list[tuple[str, str]] = []
    duplicates = 0
    for part in parts:
        key = part.dedupe_key
        if key not in merged:
            merged[key] = part
            order.append(key)
        else:
            duplicates += 1
            _merge_duplicate(merged[key], part)
    return [merged[key] for key in order], duplicates


def run_pipeline(
    parts: list[Part],
    *,
    out_dir: str | Path = "out",
    templates_dir: str | Path | None = None,
    resolver=None,
    lcsc_resolver=None,
    allow_unverified: bool = False,
    interactive: bool = True,
    sort: str = "value",
    strict: bool = False,
) -> RunResult:
    templates = load_templates(templates_dir)

    for part in parts:
        resolve_part(part, resolver, allow_unverified, lcsc_resolver, strict)

    for part in parts:
        if part.attrs:
            part.description = describe(part)

    if interactive:
        review_parts([p for p in parts if p.status is Status.MISMATCH])

    parts, duplicates = dedupe(parts)

    printable: list[Part] = []
    blocked: list[Part] = []
    by_type: dict[PartType, list[Part]] = {}

    for part in parts:
        if part.status is Status.VERIFIED:
            pass
        elif part.status is Status.UNVERIFIED and allow_unverified:
            pass
        else:
            blocked.append(part)
            continue

        template = templates.get(part.type)
        if template is None:
            part.block(f"no template for part type {part.type.value}")
            blocked.append(part)
            continue

        printable.append(part)
        by_type.setdefault(part.type, []).append(part)

    out = Path(out_dir)
    outputs: dict[str, Path] = {}
    for ptype, group in by_type.items():
        template = templates[ptype]
        path = out / f"{safe_filename(template.name)}.csv"
        outputs[template.name] = write_template_csv(path, template, group, sort=sort)

    outputs["parts"] = write_parts_csv(out / "parts.csv", parts)
    outputs["review"] = write_review_csv(out / "review.csv", parts)
    outputs["json"] = write_parts_json(out / "parts.json", parts)

    stats = {
        "total": len(parts),
        "verified": sum(1 for p in parts if p.status is Status.VERIFIED),
        "unverified": sum(1 for p in parts if p.status is Status.UNVERIFIED),
        "mismatch": sum(1 for p in parts if p.status is Status.MISMATCH),
        "blocked": sum(1 for p in parts if p.status is Status.BLOCKED),
        "printable": len(printable),
        "duplicates_merged": duplicates,
        "conflicts": sum(1 for p in parts if p.extra.get("conflicts")),
    }
    return RunResult(
        parts=parts,
        printable=printable,
        blocked=blocked,
        outputs=outputs,
        stats=stats,
        templates=templates,
    )
