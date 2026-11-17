"""Interactive resolution of verification mismatches.

The default is *safe*: a mismatch blocks the row.  If the operator is
present, they can choose the LCSC description, the web value, a custom
value, or skip.  Type mismatches are never auto-resolved -- they point at
a wrong MPN or a wrong description and need editing upstream.
"""

from __future__ import annotations

from .model import Part, PartType, Status

_LABEL_FIELDS = ("value", "rating", "tolerance", "dielectric", "package", "current", "load")


def _required_missing(part: Part) -> list[str]:
    required = {
        PartType.RESISTOR: ("value",),
        PartType.CAPACITOR: ("value",),
        PartType.INDUCTOR: ("value",),
        PartType.CRYSTAL: ("value",),
    }.get(part.type, ())
    return [name for name in required if not part.get(name)]


def review_parts(parts: list[Part], *, input_fn=input, output_fn=print) -> None:
    for part in parts:
        if part.status is not Status.MISMATCH:
            continue
        provider = part.extra.get("provider")
        mismatches: list[tuple[str, str, str]] = part.extra.get("mismatches") or []
        if provider is None or not mismatches:
            continue

        if any(field == "type" for field, _, _ in mismatches):
            output_fn(
                f"\n{part.mpn} ({part.supplier_pn}): part-type mismatch "
                f"({mismatches[0][1]} vs {mismatches[0][2]})"
            )
            output_fn("  Not auto-resolved: fix the MPN/description upstream. Row stays blocked.")
            continue

        output_fn(f"\n{part.mpn} ({part.supplier_pn}): verification disagreement")
        for field, description_value, web_value in mismatches:
            output_fn(
                f"  {field}: LCSC={description_value!r}  {provider.provider}={web_value!r}"
            )

        try:
            choice = input_fn(
                "  [m] keep LCSC  [w] use web  [c] custom  [s] skip (default s): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            part.block("review: interrupted")
            continue

        if choice == "m":
            for field, _, _ in mismatches:
                part.field_sources[field] = "description"
        elif choice == "w":
            for field, _, web_value in mismatches:
                part.attrs[field] = web_value
                if field in provider.values:
                    part.values[field] = provider.values[field]
                part.field_sources[field] = provider.provider
        elif choice == "c":
            for field, description_value, web_value in mismatches:
                try:
                    custom = input_fn(
                        f"  {field} [{description_value} / {web_value}]: "
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    custom = ""
                if custom:
                    part.attrs[field] = custom
                    part.field_sources[field] = "manual"
        else:
            part.block("review: unresolved mismatch")
            continue

        provider_name = provider.provider
        part.issues = [
            issue for issue in part.issues if f" vs {provider_name} " not in issue
        ]
        missing = _required_missing(part)
        if missing:
            part.block(f"review: missing {', '.join(missing)}")
            continue
        part.status = Status.VERIFIED
        part.verified_by = "manual review"
        part.extra["reviewed"] = True
        part.issues.append("resolved by manual review")
