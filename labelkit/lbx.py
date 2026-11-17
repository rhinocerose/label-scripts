"""Export a YAML layout to a Brother P-touch ``.lbx`` template.

An ``.lbx`` is a ZIP containing ``label.xml`` and ``prop.xml``.  The
schema used here follows P-touch Editor 5.x files: a ``pt:document`` with a
``style:paper`` (tape width / label length) and one ``text:text`` object
per layout item, each with a ``pt:expanded/@objectName`` so b-PAC can set
it by name (``GetObject("value").Text = ...``).

Coordinates in the YAML are millimetres relative to the printable area;
this module adds the margin and converts to points (1/72 inch).
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__
from .templates import LayoutItem, Template

PT_NS = "http://schemas.brother.info/ptouch/2007/lbx/main"
STYLE_NS = "http://schemas.brother.info/ptouch/2007/lbx/style"
TEXT_NS = "http://schemas.brother.info/ptouch/2007/lbx/text"
DRAW_NS = "http://schemas.brother.info/ptouch/2007/lbx/draw"
IMAGE_NS = "http://schemas.brother.info/ptouch/2007/lbx/image"
BARCODE_NS = "http://schemas.brother.info/ptouch/2007/lbx/barcode"
DATABASE_NS = "http://schemas.brother.info/ptouch/2007/lbx/database"
TABLE_NS = "http://schemas.brother.info/ptouch/2007/lbx/table"
CABLE_NS = "http://schemas.brother.info/ptouch/2007/lbx/cable"
META_NS = "http://schemas.brother.info/ptouch/2007/lbx/meta"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"

MM_TO_PT = 72.0 / 25.4
_LONG_AUTO_HEIGHT_PT = 2834.6  # what P-touch Editor uses for auto-length

for _prefix, _ns in (
    ("pt", PT_NS),
    ("style", STYLE_NS),
    ("text", TEXT_NS),
    ("draw", DRAW_NS),
    ("image", IMAGE_NS),
    ("barcode", BARCODE_NS),
    ("database", DATABASE_NS),
    ("table", TABLE_NS),
    ("cable", CABLE_NS),
    ("meta", META_NS),
    ("dc", DC_NS),
    ("dcterms", DCTERMS_NS),
):
    ET.register_namespace(_prefix, _ns)


class LbxError(RuntimeError):
    pass


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _pt(value: float) -> str:
    text = f"{round(float(value), 4):.4f}".rstrip("0").rstrip(".")
    return f"{text or '0'}pt"


def _align(value: str) -> str:
    return {
        "left": "LEFT",
        "center": "CENTER",
        "right": "RIGHT",
        "justify": "JUSTIFY",
    }[value]


def _valign(value: str) -> str:
    return {"top": "TOP", "middle": "CENTER", "bottom": "BOTTOM"}[value]


def _font_info(parent: ET.Element, item: LayoutItem) -> None:
    info = ET.SubElement(parent, _q(TEXT_NS, "ptFontInfo"))
    ET.SubElement(
        info,
        _q(TEXT_NS, "logFont"),
        {
            "name": item.font,
            "width": "0",
            "italic": "false",
            "weight": "700" if item.bold else "400",
            "charSet": "0",
            "pitchAndFamily": "34",
        },
    )
    ET.SubElement(
        info,
        _q(TEXT_NS, "fontExt"),
        {
            "effect": "NOEFFECT",
            "underline": "0",
            "strikeout": "0",
            "size": _pt(item.size),
            "orgSize": _pt(item.size),
            "textColor": "#000000",
            "textPrintColorNumber": "1",
        },
    )


def _text_object(parent: ET.Element, item: LayoutItem, index: int, margin_mm: float) -> None:
    text = ET.SubElement(parent, _q(TEXT_NS, "text"))

    object_style = ET.SubElement(
        text,
        _q(PT_NS, "objectStyle"),
        {
            "x": _pt((margin_mm + item.x) * MM_TO_PT),
            "y": _pt((margin_mm + item.y) * MM_TO_PT),
            "width": _pt(item.w * MM_TO_PT),
            "height": _pt(item.h * MM_TO_PT),
            "backColor": "#FFFFFF",
            "backPrintColorNumber": "0",
            "ropMode": "COPYPEN",
            "angle": "0",
            "anchor": "TOPLEFT",
            "flip": "NONE",
        },
    )
    ET.SubElement(
        object_style,
        _q(PT_NS, "pen"),
        {
            "style": "NULL",
            "widthX": "0.5pt",
            "widthY": "0.5pt",
            "color": "#000000",
            "printColorNumber": "1",
        },
    )
    ET.SubElement(
        object_style,
        _q(PT_NS, "brush"),
        {
            "style": "NULL",
            "color": "#000000",
            "printColorNumber": "1",
            "id": "0",
        },
    )
    ET.SubElement(
        object_style,
        _q(PT_NS, "expanded"),
        {
            "objectName": item.name,
            "ID": str(index),
            "lock": "0",
            "templateMergeTarget": "LABELLIST",
            "templateMergeType": "NONE",
            "templateMergeID": "0",
            "linkStatus": "NONE",
            "linkID": "0",
        },
    )

    _font_info(text, item)

    ET.SubElement(
        text,
        _q(TEXT_NS, "textControl"),
        {
            "control": "FREE",
            "clipFrame": "false",
            "aspectNormal": "false",
            "shrink": "true" if item.shrink else "false",
            "autoLF": "false",
            "avoidImage": "false",
        },
    )
    ET.SubElement(
        text,
        _q(TEXT_NS, "textAlign"),
        {
            "horizontalAlignment": _align(item.align),
            "verticalAlignment": _valign(item.valign),
            "inLineAlignment": "BASELINE",
        },
    )
    ET.SubElement(
        text,
        _q(TEXT_NS, "textStyle"),
        {
            "vertical": "false",
            "nullBlock": "false",
            "charSpace": "0",
            "lineSpace": "40",
            "orgPoint": _pt(item.size),
            "combinedChars": "false",
        },
    )

    payload = f"{{{item.field}}}" if item.field else item.text
    ET.SubElement(text, _q(PT_NS, "data")).text = payload

    string_item = ET.SubElement(
        text, _q(TEXT_NS, "stringItem"), {"charLen": str(len(payload))}
    )
    _font_info(string_item, item)


def build_lbx(
    template: Template,
    *,
    printer_name: str = "",
    printer_id: int | str | None = None,
    format_id: int | str | None = None,
) -> bytes:
    if template.layout is None:
        raise LbxError(
            f"template {template.name!r} has no layout; add a 'layout:' section "
            "to its YAML before exporting"
        )

    layout = template.layout
    tape_pt = template.tape_mm * MM_TO_PT
    margin_pt = layout.margin_mm * MM_TO_PT
    paper_height_pt = (
        _LONG_AUTO_HEIGHT_PT
        if layout.auto_length
        else layout.length_mm * MM_TO_PT
    )
    orientation = "portrait" if layout.length_mm >= template.tape_mm else "landscape"

    root = ET.Element(
        _q(PT_NS, "document"),
        {"version": "1.7", "generator": f"labelkit {__version__}"},
    )
    # P-touch Editor writes these declarations even when unused; keep them
    # for files that are opened by older Editor versions.
    for prefix, namespace in (
        ("draw", DRAW_NS),
        ("image", IMAGE_NS),
        ("barcode", BARCODE_NS),
        ("database", DATABASE_NS),
        ("table", TABLE_NS),
        ("cable", CABLE_NS),
    ):
        root.set(f"xmlns:{prefix}", namespace)

    body = ET.SubElement(
        root, _q(PT_NS, "body"), {"currentSheet": "Sheet1", "direction": "LTR"}
    )
    sheet = ET.SubElement(body, _q(STYLE_NS, "sheet"), {"name": "Sheet1"})

    paper_attrs = {
        "media": "0",
        "width": _pt(tape_pt),
        "height": _pt(paper_height_pt),
        "marginLeft": _pt(margin_pt),
        "marginTop": _pt(margin_pt),
        "marginRight": _pt(margin_pt),
        "marginBottom": _pt(margin_pt),
        "orientation": orientation,
        "autoLength": "true" if layout.auto_length else "false",
        "monochromeDisplay": "true",
        "printColorDisplay": "false",
        "printColorsID": "0",
        "paperColor": "#FFFFFF",
        "paperInk": "#000000",
        "split": "1",
        "backgroundTheme": "0",
    }
    if printer_name:
        paper_attrs["printerName"] = printer_name
    if printer_id is not None:
        paper_attrs["printerID"] = str(printer_id)
    if format_id is not None:
        paper_attrs["format"] = str(format_id)
    ET.SubElement(sheet, _q(STYLE_NS, "paper"), paper_attrs)

    ET.SubElement(
        sheet, _q(STYLE_NS, "cutLine"), {"regularCut": "0pt", "freeCut": ""}
    )

    ET.SubElement(
        sheet,
        _q(STYLE_NS, "backGround"),
        {
            "x": _pt(margin_pt),
            "y": _pt(margin_pt),
            "width": _pt((template.tape_mm - 2 * layout.margin_mm) * MM_TO_PT),
            "height": _pt((layout.length_mm - 2 * layout.margin_mm) * MM_TO_PT),
            "brushStyle": "NULL",
            "brushId": "0",
            "userPattern": "NONE",
            "userPatternId": "0",
            "color": "#000000",
            "printColorNumber": "1",
            "backColor": "#FFFFFF",
            "backPrintColorNumber": "0",
        },
    )

    objects = ET.SubElement(sheet, _q(PT_NS, "objects"))
    for index, item in enumerate(layout.items):
        _text_object(objects, item, index, layout.margin_mm)

    ET.indent(root, space="  ")
    label_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prop_root = ET.Element(_q(META_NS, "properties"))
    ET.SubElement(prop_root, _q(DC_NS, "title")).text = (
        f"{template.name} ({template.tape_mm} mm)"
    )
    ET.SubElement(prop_root, _q(DC_NS, "creator")).text = "labelkit"
    ET.SubElement(prop_root, _q(DCTERMS_NS, "created")).text = created
    ET.SubElement(prop_root, _q(DCTERMS_NS, "modified")).text = created
    ET.indent(prop_root, space="  ")
    prop_xml = ET.tostring(prop_root, encoding="utf-8", xml_declaration=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label.xml", label_xml)
        archive.writestr("prop.xml", prop_xml)
    return buffer.getvalue()


def export_lbx(
    template: Template,
    path: str | Path,
    *,
    printer_name: str = "",
    printer_id: int | str | None = None,
    format_id: int | str | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        build_lbx(
            template,
            printer_name=printer_name,
            printer_id=printer_id,
            format_id=format_id,
        )
    )
    return target
