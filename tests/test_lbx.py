import io
import unittest
import zipfile
from dataclasses import replace
from xml.etree import ElementTree as ET

from labelkit.lbx import (
    PT_NS,
    STYLE_NS,
    TEXT_NS,
    LbxError,
    build_lbx,
)
from labelkit.model import PartType
from labelkit.templates import Template, load_templates

NS = {"pt": PT_NS, "style": STYLE_NS, "text": TEXT_NS}
MM_TO_PT = 72.0 / 25.4


def _pt(value: str) -> float:
    return float(value.removesuffix("pt"))


def _unzip(data: bytes) -> tuple[ET.Element, ET.Element]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        label = ET.fromstring(archive.read("label.xml"))
        prop = ET.fromstring(archive.read("prop.xml"))
    return label, prop


class LbxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = load_templates()
        cls.resistor = cls.templates[PartType.RESISTOR]

    def test_is_a_zip_with_the_two_expected_files(self):
        data = build_lbx(self.resistor)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.namelist(), ["label.xml", "prop.xml"])

    def test_paper_is_12mm_by_the_layout_length(self):
        label, _ = _unzip(build_lbx(self.resistor))
        paper = label.find(".//style:paper", NS)
        self.assertIsNotNone(paper)
        self.assertAlmostEqual(_pt(paper.get("width")), 12 * MM_TO_PT, places=2)
        self.assertAlmostEqual(_pt(paper.get("height")), 22 * MM_TO_PT, places=2)
        self.assertAlmostEqual(
            _pt(paper.get("marginLeft")), 1.0 * MM_TO_PT, places=2
        )
        self.assertEqual(paper.get("orientation"), "portrait")
        self.assertEqual(paper.get("autoLength"), "false")

    def test_background_is_printable_area(self):
        label, _ = _unzip(build_lbx(self.resistor))
        background = label.find(".//style:backGround", NS)
        self.assertIsNotNone(background)
        self.assertAlmostEqual(
            _pt(background.get("width")), 10 * MM_TO_PT, places=2
        )
        self.assertAlmostEqual(
            _pt(background.get("height")), 20 * MM_TO_PT, places=2
        )

    def test_text_objects_have_named_fields(self):
        label, _ = _unzip(build_lbx(self.resistor))
        objects = label.findall(".//pt:objects/text:text", NS)
        names = [
            obj.find("pt:objectStyle/pt:expanded", NS).get("objectName")
            for obj in objects
        ]
        self.assertEqual(
            names, ["value", "tolerance", "package", "mpn", "supplier_pn"]
        )
        data = [obj.find("pt:data", NS).text for obj in objects]
        self.assertEqual(
            data, ["{value}", "{tolerance}", "{package}", "{mpn}", "{supplier_pn}"]
        )
        for obj, payload in zip(objects, data):
            string_item = obj.find("text:stringItem", NS)
            self.assertEqual(string_item.get("charLen"), str(len(payload)))

    def test_font_sizes_and_bold(self):
        label, _ = _unzip(build_lbx(self.resistor))
        objects = label.findall(".//pt:objects/text:text", NS)
        value_font = objects[0].find("text:ptFontInfo", NS)
        log_font = value_font.find("text:logFont", NS)
        font_ext = value_font.find("text:fontExt", NS)
        self.assertEqual(log_font.get("name"), "Arial")
        self.assertEqual(log_font.get("weight"), "700")
        self.assertEqual(font_ext.get("size"), "11pt")

        tolerance_font = objects[1].find("text:ptFontInfo", NS)
        self.assertEqual(
            tolerance_font.find("text:logFont", NS).get("weight"), "400"
        )
        self.assertEqual(
            tolerance_font.find("text:fontExt", NS).get("size"), "7.5pt"
        )

    def test_prop_xml_has_metadata(self):
        _, prop = _unzip(build_lbx(self.resistor))
        title = prop.find("{http://purl.org/dc/elements/1.1/}title")
        creator = prop.find("{http://purl.org/dc/elements/1.1/}creator")
        self.assertEqual(title.text, "resistor (12 mm)")
        self.assertEqual(creator.text, "labelkit")

    def test_auto_length_mode(self):
        layout = self.resistor.layout
        template = replace(
            self.resistor, layout=replace(layout, auto_length=True)
        )
        label, _ = _unzip(build_lbx(template))
        paper = label.find(".//style:paper", NS)
        self.assertEqual(paper.get("autoLength"), "true")
        self.assertAlmostEqual(_pt(paper.get("height")), 2834.6, places=1)

    def test_layout_is_required(self):
        template = Template(
            name="empty",
            part_type=PartType.RESISTOR,
            tape_mm=12,
            fields=(),
            layout=None,
        )
        with self.assertRaises(LbxError):
            build_lbx(template)


if __name__ == "__main__":
    unittest.main()
