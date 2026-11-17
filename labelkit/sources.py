"""Input adapters: LCSC invoice/BOM CSVs and plain MPN lists.

LCSC rows keep the supplier part number, MPN, manufacturer, quantity and
the original description.  The description is interpreted into candidate
attributes and later verified by the web provider.

Rows without a description (MPN-only input) carry no candidate
attributes; the provider has to supply everything.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .classify import classify_description, classify_mpn
from .description import parse_description
from .model import Part, PartType
from .values import is_dielectric, looks_like_package

LCSC_RE = re.compile(r"^C\d{3,}$", re.IGNORECASE)
_INT_RE = re.compile(r"^\d+$")
_FLOAT_RE = re.compile(r"^\d+\.\d+$")

_HEADER_CELLS = {
    "lcsc part number",
    "lcsc part",
    "lcsc",
    "lcsc_pn",
    "lcsc pn",
    "mpn",
    "manufacturer part number",
    "mfr part number",
    "mfr. part #",
    "part number",
    "part_number",
    "partno",
    "part no",
    "pn",
    "sku",
    "description",
    "quantity",
    "qty",
    "unit price",
    "package",
}


def _cue_score(cell: str) -> int:
    """Rough 'this looks like an attribute description' score."""
    if not cell:
        return 0
    score = 0
    if re.search(r"\d+(?:\.\d+)?\s*(?:meg|[pnu]|m|[kKMG])?\s*V\b", cell, re.I):
        score += 1
    if re.search(r"\d+(?:\.\d+)?\s*(?:meg|[pnu]|m|[kKMG])?\s*F\b", cell, re.I):
        score += 1
    if re.search(r"\d+(?:\.\d+)?\s*(?:meg|[pnu]|m|[kKMG])?\s*(?:W|A|H|Hz)\b", cell, re.I):
        score += 1
    if "%" in cell:
        score += 1
    if any(is_dielectric(tok) for tok in re.split(r"[\s,;]+", cell) if tok):
        score += 1
    if len(cell) >= 15:
        score += 1
    return score


def _read_csv_rows(path: Path) -> list[list[str]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.reader(handle, delimiter=delimiter)]


def _header_kind(row: list[str]) -> str | None:
    cells = [c.strip().lower() for c in row]
    if not cells:
        return None
    if any("lcsc" in c for c in cells):
        return "lcsc"
    if any("description" in c or c in ("quantity", "qty") for c in cells):
        return "mpn"
    if any(
        "mpn" in c
        or "manufacturer part" in c
        or "mfr part" in c
        or "part number" in c
        or c in {"part_number", "partno", "part no", "pn", "sku"}
        for c in cells
    ):
        return "mpn"
    if all(c in _HEADER_CELLS for c in cells if c):
        return "mpn"
    return None


def _map_header(header: list[str]) -> dict[str, int | None]:
    lower = [c.strip().lower() for c in header]

    def find(*needles: str, exclude: tuple[str, ...] = ()) -> int | None:
        for i, cell in enumerate(lower):
            if any(n in cell for n in needles) and not any(e in cell for e in exclude):
                return i
        return None

    return {
        "lcsc": find("lcsc"),
        "mpn": find(
            "mpn",
            "manufacturer part",
            "mfr part",
            "part number",
            "part_number",
            "partno",
            "part no",
            "sku",
            "pn",
            exclude=("lcsc",),
        ),
        "manufacturer": find("manufacturer", "mfr", "brand", exclude=("part",)),
        "description": find("description", "desc", "comment"),
        "package": find("package", "footprint", "case"),
        "qty": find("quantity", "qty", "order qty"),
        "price": find("unit price", "price"),
        "project": find("project", "designator", "reference"),
    }


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return str(row[index]).strip()


def _to_int(text: str) -> int:
    text = str(text or "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _build_part(
    *,
    source: str,
    supplier_pn: str,
    mpn: str,
    manufacturer: str,
    description: str,
    package: str,
    qty: int,
    price: str,
    project: str,
    line: int,
    raw: dict,
    trust_description: bool = False,
) -> Part:
    part = Part(
        source=source,
        supplier_pn=supplier_pn,
        mpn=mpn,
        manufacturer=manufacturer,
        source_description=description,
        qty=qty,
        price=price,
        project=project,
        source_line=line,
        raw=raw,
    )

    if not mpn and not supplier_pn:
        part.block("no MPN and no LCSC part number")
        return part

    if description and trust_description:
        ptype, confidence, reasons = classify_description(
            description, package=package, mpn=mpn
        )
        if ptype is PartType.UNKNOWN:
            fallback = classify_mpn(mpn)
            if fallback is not None:
                ptype = fallback
                confidence = 0.5
                reasons = [*reasons, f"MPN prefix fallback ({fallback.value})"]
        part.type = ptype
        part.confidence = confidence
        part.extra["type_reasons"] = reasons

        if ptype is PartType.UNKNOWN:
            part.issues.append("could not determine part type from description or MPN")
            return part

        parsed = parse_description(
            description, part_type=ptype, package_hint=package, mpn=mpn
        )
        for key, value in parsed.attrs.items():
            part.attrs[key] = value
            part.field_sources[key] = "description"
        part.values.update(parsed.values)
        part.issues.extend(parsed.issues)
    else:
        # MPN is the sole data source by default; the description is kept
        # for reference/audit only and never parsed.
        ptype = classify_mpn(mpn)
        part.type = ptype or PartType.UNKNOWN
        part.confidence = 0.55 if ptype is not None else 0.0

    return part


def _parse_lcsc_heuristic(
    row: list[str], source: str, line: int, trust_description: bool = False
) -> Part | None:
    cells = [str(c).strip() for c in row]
    lcsc_idx = next((i for i, c in enumerate(cells) if LCSC_RE.fullmatch(c)), None)
    if lcsc_idx is None:
        return None

    mpn = _cell(cells, lcsc_idx + 1)
    manufacturer = _cell(cells, lcsc_idx + 2)

    project = ""
    cand = _cell(cells, lcsc_idx + 3)
    if (
        cand
        and not looks_like_package(cand)
        and not _INT_RE.fullmatch(cand)
        and _cue_score(cand) < 2
    ):
        project = cand

    package = ""
    description = ""
    desc_idx: int | None = None
    best_score = -1
    for i in range(lcsc_idx + 3, len(cells)):
        cell = cells[i]
        if not cell:
            continue
        if not package and looks_like_package(cell) and _cue_score(cell) < 2:
            package = str(cell).strip()
        score = _cue_score(cell)
        if score > best_score and score >= 2:
            best_score = score
            description = cell
            desc_idx = i

    start = (desc_idx + 1) if desc_idx is not None else (lcsc_idx + 4)
    qty = 0
    price = ""
    for i in range(start, len(cells)):
        cell = cells[i]
        if not cell or cell.upper() in {"YES", "NO", "Y", "N", "TRUE", "FALSE"}:
            continue
        if _INT_RE.fullmatch(cell):
            qty = int(cell)
            for j in range(i + 1, len(cells)):
                if _FLOAT_RE.fullmatch(cells[j]):
                    price = cells[j]
                    break
            break

    return _build_part(
        source=source,
        supplier_pn=cells[lcsc_idx],
        mpn=mpn,
        manufacturer=manufacturer,
        description=description,
        package=package,
        qty=qty,
        price=price,
        project=project,
        line=line,
        raw={"row": row},
        trust_description=trust_description,
    )


def _parse_lcsc_mapped(
    row: list[str],
    mapping: dict[str, int | None],
    source: str,
    line: int,
    trust_description: bool = False,
) -> Part | None:
    supplier_pn = _cell(row, mapping.get("lcsc"))
    mpn = _cell(row, mapping.get("mpn"))
    if not supplier_pn and not mpn:
        return None
    return _build_part(
        source="lcsc" if supplier_pn else "manual",
        supplier_pn=supplier_pn,
        mpn=mpn,
        manufacturer=_cell(row, mapping.get("manufacturer")),
        description=_cell(row, mapping.get("description")),
        package=_cell(row, mapping.get("package")),
        qty=_to_int(_cell(row, mapping.get("qty"))),
        price=_cell(row, mapping.get("price")),
        project=_cell(row, mapping.get("project")),
        line=line,
        raw={"row": row},
        trust_description=trust_description,
    )


def _parse_mpn_mapped(
    row: list[str],
    mapping: dict[str, int | None],
    source: str,
    line: int,
    trust_description: bool = False,
) -> Part | None:
    mpn = _cell(row, mapping.get("mpn"))
    supplier_pn = _cell(row, mapping.get("lcsc"))
    if not mpn:
        # Fall back to the first non-empty cell.
        for cell in row:
            if str(cell).strip():
                mpn = str(cell).strip()
                break
    if not mpn:
        return None
    if LCSC_RE.fullmatch(mpn) and not supplier_pn:
        supplier_pn, mpn = mpn, ""
    return _build_part(
        source="lcsc" if supplier_pn else "manual",
        supplier_pn=supplier_pn,
        mpn=mpn,
        manufacturer=_cell(row, mapping.get("manufacturer")),
        description="",
        package="",
        qty=_to_int(_cell(row, mapping.get("qty"))),
        price="",
        project="",
        line=line,
        raw={"row": row},
        trust_description=trust_description,
    )


def _parse_auto_row(
    row: list[str], source: str, line: int, trust_description: bool = False
) -> Part | None:
    cells = [str(c).strip() for c in row]
    if any(LCSC_RE.fullmatch(c) for c in cells):
        return _parse_lcsc_heuristic(row, source, line, trust_description)

    mpn = next((c for c in cells if c), "")
    if not mpn:
        return None
    qty = 0
    for cell in cells[cells.index(mpn) + 1 :]:
        if _INT_RE.fullmatch(cell):
            qty = int(cell)
            break
    if LCSC_RE.fullmatch(mpn):
        return _build_part(
            source="lcsc",
            supplier_pn=mpn,
            mpn="",
            manufacturer="",
            description="",
            package="",
            qty=qty,
            price="",
            project="",
            line=line,
            raw={"row": row},
            trust_description=trust_description,
        )
    return _build_part(
        source="manual",
        supplier_pn="",
        mpn=mpn,
        manufacturer="",
        description="",
        package="",
        qty=qty,
        price="",
        project="",
        line=line,
        raw={"row": row},
        trust_description=trust_description,
    )


def parse_csv_rows(
    rows: list[list[str]],
    source: str = "<csv>",
    trust_description: bool = False,
) -> list[Part]:
    rows = [row for row in rows if any(str(c).strip() for c in row)]
    if not rows:
        return []

    kind = _header_kind(rows[0])
    if kind is not None:
        mapping = _map_header(rows[0])
        parts: list[Part] = []
        for line, row in enumerate(rows[1:], start=2):
            if not any(str(c).strip() for c in row):
                continue
            part: Part | None
            if mapping.get("description") is not None or mapping.get("lcsc") is not None:
                part = _parse_lcsc_mapped(
                    row, mapping, source, line, trust_description
                )
            else:
                part = _parse_mpn_mapped(
                    row, mapping, source, line, trust_description
                )
            if part is not None:
                parts.append(part)
        return parts

    parts = []
    for line, row in enumerate(rows, start=1):
        part = _parse_auto_row(row, source, line, trust_description)
        if part is not None:
            parts.append(part)
    return parts


def read_mpn_lines(lines: list[str], source: str = "<stdin>") -> list[Part]:
    parts: list[Part] = []
    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f.strip() for f in re.split(r"[,\t]", line) if f.strip()]
        if len(fields) == 1:
            fields = line.split()
        if not fields:
            continue
        first = fields[0]
        if first.lower() in {"mpn", "part number", "part #", "lcsc", "lcsc number"}:
            continue

        qty = 0
        if len(fields) > 1 and _INT_RE.fullmatch(fields[1]):
            qty = int(fields[1])

        if LCSC_RE.fullmatch(first):
            parts.append(
                _build_part(
                    source="lcsc",
                    supplier_pn=first,
                    mpn="",
                    manufacturer="",
                    description="",
                    package="",
                    qty=qty,
                    price="",
                    project="",
                    line=line_no,
                    raw={"line": raw_line},
                )
            )
        else:
            parts.append(
                _build_part(
                    source="manual",
                    supplier_pn="",
                    mpn=first,
                    manufacturer="",
                    description="",
                    package="",
                    qty=qty,
                    price="",
                    project="",
                    line=line_no,
                    raw={"line": raw_line},
                )
            )
    return parts


def load_input(path: Path, trust_description: bool = False) -> list[Part]:
    suffix = path.suffix.lower()
    if suffix in (".txt", ".lst", ".list", ".lines"):
        return read_mpn_lines(path.read_text(encoding="utf-8-sig").splitlines(), source=str(path))
    rows = _read_csv_rows(path)
    return parse_csv_rows(rows, source=str(path), trust_description=trust_description)
