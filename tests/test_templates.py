import tempfile
import unittest
from pathlib import Path

from labelkit.model import Part, PartType
from labelkit.templates import TemplateError, load_templates


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = load_templates()

    def test_all_types_have_a_template(self):
        self.assertEqual(len(self.templates), 8)
        for ptype in (
            PartType.RESISTOR,
            PartType.CAPACITOR,
            PartType.INDUCTOR,
            PartType.DIODE,
            PartType.LED,
            PartType.TRANSISTOR,
            PartType.CRYSTAL,
            PartType.IC,
        ):
            self.assertIn(ptype, self.templates)

    def test_legacy_headers_are_preserved(self):
        self.assertEqual(
            self.templates[PartType.RESISTOR].headers,
            ["LCSC Number", "MPN", "Resistance", "Power", "Tolerance", "Size"],
        )
        self.assertEqual(
            self.templates[PartType.CAPACITOR].headers,
            [
                "LCSC Number",
                "MPN",
                "Capacitance",
                "Voltage",
                "Tolerance",
                "Dielectric",
                "Size",
            ],
        )

    def test_row(self):
        part = Part(
            supplier_pn="C1",
            mpn="M1",
            type=PartType.RESISTOR,
            attrs={
                "value": "10k",
                "rating": "100mW",
                "tolerance": "1%",
                "package": "0603",
            },
        )
        self.assertEqual(
            self.templates[PartType.RESISTOR].row(part),
            ["C1", "M1", "10k", "100mW", "1%", "0603"],
        )

    def test_description_column_only_on_non_passives(self):
        self.assertNotIn("Description", self.templates[PartType.RESISTOR].headers)
        self.assertNotIn("Description", self.templates[PartType.CAPACITOR].headers)
        for ptype in (
            PartType.INDUCTOR,
            PartType.DIODE,
            PartType.LED,
            PartType.TRANSISTOR,
            PartType.CRYSTAL,
            PartType.IC,
        ):
            self.assertIn("Description", self.templates[ptype].headers)

    def test_tape_width(self):
        for template in self.templates.values():
            self.assertEqual(template.tape_mm, 12)

    def test_every_template_has_a_usable_layout(self):
        for ptype, template in self.templates.items():
            self.assertIsNotNone(template.layout, ptype)
            self.assertGreater(len(template.layout.items), 0)
            self.assertGreater(template.layout.length_mm, 0)
            self.assertGreaterEqual(template.layout.margin_mm, 0)

    def test_resistor_layout_fits_printable_area(self):
        layout = self.templates[PartType.RESISTOR].layout
        self.assertEqual(layout.length_mm, 22)
        self.assertEqual(layout.margin_mm, 1.0)
        for item in layout.items:
            self.assertLessEqual(item.x + item.w, 10 + 1e-9)
            self.assertLessEqual(item.y + item.h, 20 + 1e-9)

    def _load_single(self, body: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text(body, encoding="utf-8")
            return load_templates(tmp)

    def test_layout_outside_printable_area_is_rejected(self):
        with self.assertRaises(TemplateError):
            self._load_single(
                """
name: bad
part_type: diode
tape_mm: 12
fields:
  - {key: value, header: Value}
layout:
  length_mm: 20
  margin_mm: 1.0
  items:
    - {field: value, x: 5, y: 0, w: 10, h: 5, size: 8}
"""
            )

    def test_unknown_layout_field_is_rejected(self):
        with self.assertRaises(TemplateError):
            self._load_single(
                """
name: bad
part_type: diode
tape_mm: 12
fields:
  - {key: value, header: Value}
layout:
  length_mm: 20
  margin_mm: 1.0
  items:
    - {field: nope, x: 0, y: 0, w: 10, h: 5, size: 8}
"""
            )


if __name__ == "__main__":
    unittest.main()
