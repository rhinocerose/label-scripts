"""YAML label templates.

A template has two parts:

* ``fields`` -- the merge-CSV columns (unchanged behaviour);
* ``layout`` -- optional 12 mm P-touch geometry used by ``export-lbx``.

Layout coordinates are millimetres **relative to the printable area**, not
the paper edge; the exporter adds the margin and converts to points.  Boxes
are validated against the tape width and label length at load time, so a
typo in a YAML file fails before a printer is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import Part, PartType


class TemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateField:
    key: str
    header: str


@dataclass(frozen=True)
class LayoutItem:
    field: str
    text: str
    name: str
    x: float
    y: float
    w: float
    h: float
    size: float
    bold: bool
    align: str
    valign: str
    shrink: bool
    font: str

    @property
    def is_static(self) -> bool:
        return not self.field


@dataclass(frozen=True)
class LabelLayout:
    length_mm: float
    margin_mm: float
    auto_length: bool
    items: tuple[LayoutItem, ...]


@dataclass
class Template:
    name: str
    part_type: PartType
    tape_mm: int
    fields: tuple[TemplateField, ...]
    layout: LabelLayout | None = None
    source: Path | None = None

    @property
    def headers(self) -> list[str]:
        return [field.header for field in self.fields]

    @property
    def field_keys(self) -> set[str]:
        return {field.key for field in self.fields} | set(_SPECIAL_GETTERS)

    def row(self, part: Part) -> list[str]:
        return [get_field(part, field.key) for field in self.fields]


_SPECIAL_GETTERS = {
    "supplier_pn": lambda part: part.supplier_pn,
    "mpn": lambda part: part.mpn,
    "manufacturer": lambda part: part.manufacturer,
    "qty": lambda part: str(part.qty) if part.qty else "",
    "description": lambda part: part.description,
    "source_description": lambda part: part.source_description,
}


def get_field(part: Part, key: str) -> str:
    getter = _SPECIAL_GETTERS.get(key)
    if getter is not None:
        return getter(part)
    return part.attrs.get(key, "")


def default_templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


_ALIGNMENTS = {"left", "center", "right", "justify"}
_VALIGNMENTS = {"top", "middle", "bottom"}


def _parse_layout(
    raw: object,
    path: Path,
    tape_mm: int,
    field_keys: set[str],
) -> LabelLayout:
    if not isinstance(raw, dict):
        raise TemplateError(f"{path}: layout must be a mapping")

    length_mm = float(raw.get("length_mm", 40))
    margin_mm = float(raw.get("margin_mm", 1.0))
    auto_length = bool(raw.get("auto_length", False))
    if margin_mm < 0:
        raise TemplateError(f"{path}: layout.margin_mm must be >= 0")
    printable_w = tape_mm - 2 * margin_mm
    printable_h = length_mm - 2 * margin_mm
    if printable_w <= 0 or printable_h <= 0:
        raise TemplateError(
            f"{path}: margins ({margin_mm}mm) leave no printable area on "
            f"{tape_mm}mm tape x {length_mm}mm"
        )

    raw_items = raw.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise TemplateError(f"{path}: layout.items must be a non-empty list")

    items: list[LayoutItem] = []
    used_names: dict[str, int] = {}

    for index, entry in enumerate(raw_items):
        if not isinstance(entry, dict):
            raise TemplateError(f"{path}: layout item #{index + 1} is not a mapping")

        field = str(entry.get("field") or "").strip()
        text = str(entry.get("text") or "")
        if not field and not text:
            raise TemplateError(
                f"{path}: layout item #{index + 1} needs 'field' or 'text'"
            )
        if field and field not in field_keys:
            raise TemplateError(
                f"{path}: layout item #{index + 1} references unknown field {field!r}; "
                f"known fields: {', '.join(sorted(field_keys))}"
            )

        try:
            x = float(entry.get("x", 0))
            y = float(entry.get("y", 0))
            w = float(entry["w"])
            h = float(entry["h"])
            size = float(entry.get("size", 8))
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateError(
                f"{path}: layout item #{index + 1} needs numeric x/y/w/h/size"
            ) from exc

        if x < 0 or y < 0:
            raise TemplateError(f"{path}: layout item #{index + 1} has negative x/y")
        if w <= 0 or h <= 0:
            raise TemplateError(f"{path}: layout item #{index + 1} has non-positive w/h")
        if x + w > printable_w + 1e-6:
            raise TemplateError(
                f"{path}: layout item #{index + 1} is {x + w:.2f}mm wide; "
                f"printable width is {printable_w:.2f}mm"
            )
        if y + h > printable_h + 1e-6:
            raise TemplateError(
                f"{path}: layout item #{index + 1} ends at {y + h:.2f}mm; "
                f"printable length is {printable_h:.2f}mm"
            )

        align = str(entry.get("align") or "center").lower()
        valign = str(entry.get("valign") or "top").lower()
        if align not in _ALIGNMENTS:
            raise TemplateError(
                f"{path}: layout item #{index + 1} has bad align {align!r}"
            )
        if valign not in _VALIGNMENTS:
            raise TemplateError(
                f"{path}: layout item #{index + 1} has bad valign {valign!r}"
            )

        base_name = str(entry.get("name") or field or f"static_{index + 1}")
        count = used_names.get(base_name, 0) + 1
        used_names[base_name] = count
        name = base_name if count == 1 else f"{base_name}_{count}"

        items.append(
            LayoutItem(
                field=field,
                text=text,
                name=name,
                x=x,
                y=y,
                w=w,
                h=h,
                size=size,
                bold=bool(entry.get("bold", False)),
                align=align,
                valign=valign,
                shrink=bool(entry.get("shrink", True)),
                font=str(entry.get("font") or "Arial"),
            )
        )

    return LabelLayout(
        length_mm=length_mm,
        margin_mm=margin_mm,
        auto_length=auto_length,
        items=tuple(items),
    )


def load_templates(directory: str | Path | None = None) -> dict[PartType, Template]:
    root = Path(directory) if directory else default_templates_dir()
    if not root.is_dir():
        raise TemplateError(f"template directory not found: {root}")

    templates: dict[PartType, Template] = {}
    for path in sorted([*root.glob("*.yaml"), *root.glob("*.yml")]):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ptype = PartType.parse(data.get("part_type"))
        if ptype is PartType.UNKNOWN:
            raise TemplateError(f"{path}: missing or invalid part_type")

        raw_fields = data.get("fields") or []
        fields: list[TemplateField] = []
        for entry in raw_fields:
            if isinstance(entry, str):
                key = entry
                header = entry
            elif isinstance(entry, dict) and entry.get("key"):
                key = str(entry["key"])
                header = str(entry.get("header") or entry.get("label") or key)
            else:
                raise TemplateError(f"{path}: bad field entry: {entry!r}")
            fields.append(TemplateField(key=key, header=header))
        if not fields:
            raise TemplateError(f"{path}: template has no fields")

        name = str(data.get("name") or ptype.value)
        tape_mm = int(data.get("tape_mm") or 12)
        field_keys = {field.key for field in fields} | set(_SPECIAL_GETTERS)
        layout = None
        if data.get("layout") is not None:
            layout = _parse_layout(data["layout"], path, tape_mm, field_keys)

        if ptype in templates:
            raise TemplateError(
                f"duplicate template for {ptype.value}: {templates[ptype].source} and {path}"
            )
        templates[ptype] = Template(
            name=name,
            part_type=ptype,
            tape_mm=tape_mm,
            fields=tuple(fields),
            layout=layout,
            source=path,
        )

    if not templates:
        raise TemplateError(f"no *.yaml templates found in {root}")
    return templates
