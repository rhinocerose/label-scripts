import unittest

from labelkit.description import parse_description
from labelkit.model import PartType


class DescriptionTests(unittest.TestCase):
    def test_capacitor(self):
        parsed = parse_description(
            "50V 10nF X7R 10% 0603", part_type=PartType.CAPACITOR
        )
        self.assertEqual(parsed.attrs["value"], "10nF")
        self.assertEqual(parsed.attrs["rating"], "50V")
        self.assertEqual(parsed.attrs["tolerance"], "10%")
        self.assertEqual(parsed.attrs["dielectric"], "X7R")
        self.assertEqual(parsed.attrs["package"], "0603")
        self.assertEqual(parsed.values["value"].text(), "10nF")

    def test_resistor(self):
        parsed = parse_description(
            "100mW 1k 75V 1% 0603", part_type=PartType.RESISTOR
        )
        self.assertEqual(parsed.attrs["value"], "1k")
        self.assertEqual(parsed.attrs["rating"], "100mW")
        self.assertEqual(parsed.attrs["voltage_max"], "75V")
        self.assertEqual(parsed.attrs["tolerance"], "1%")
        self.assertEqual(parsed.attrs["package"], "0603")

    def test_unitless_resistance(self):
        parsed = parse_description(
            "100mW 590 75V 1% 0603", part_type=PartType.RESISTOR
        )
        self.assertEqual(parsed.attrs["value"], "590R")

        parsed = parse_description(
            "500mW 1 200V 1% 1206", part_type=PartType.RESISTOR
        )
        self.assertEqual(parsed.attrs["value"], "1R")

    def test_fractional_watt(self):
        parsed = parse_description("1/10W 10k 1% 0603", part_type=PartType.RESISTOR)
        self.assertEqual(parsed.attrs["rating"], "100mW")

    def test_crystal(self):
        parsed = parse_description(
            "16MHz 20pF 30ppm 3225", part_type=PartType.CRYSTAL
        )
        self.assertEqual(parsed.attrs["value"], "16MHz")
        self.assertEqual(parsed.attrs["load"], "20pF")
        self.assertEqual(parsed.attrs["stability"], "30ppm")
        self.assertEqual(parsed.attrs["package"], "3225")

    def test_ferrite_bead_uses_impedance(self):
        parsed = parse_description(
            "Ferrite Bead 120 Ohm 1A 0603", part_type=PartType.INDUCTOR
        )
        self.assertEqual(parsed.attrs["value"], "120R")
        self.assertEqual(parsed.attrs["rating"], "1A")
        self.assertEqual(parsed.attrs["package"], "0603")

    def test_led(self):
        parsed = parse_description(
            "Green 2.1V 20mA 0603", part_type=PartType.LED
        )
        self.assertEqual(parsed.attrs["color"], "Green")
        self.assertEqual(parsed.attrs["rating"], "2.1V")
        self.assertEqual(parsed.attrs["current"], "20mA")

    def test_transistor(self):
        parsed = parse_description(
            "NPN 40V 200mA SOT-23", part_type=PartType.TRANSISTOR
        )
        self.assertEqual(parsed.attrs["polarity"], "NPN")
        self.assertEqual(parsed.attrs["rating"], "40V")
        self.assertEqual(parsed.attrs["current"], "200mA")

    def test_crystal_size_hint_stays_metric(self):
        parsed = parse_description(
            "16MHz 20pF 30ppm", part_type=PartType.CRYSTAL, package_hint="3225"
        )
        self.assertEqual(parsed.attrs["package"], "3225")

    def test_leading_pin_package(self):
        parsed = parse_description("14-TSSOP", part_type=PartType.IC)
        self.assertEqual(parsed.attrs["package"], "TSSOP-14")

    def test_unknown_type_is_not_interpreted(self):
        parsed = parse_description("something", part_type=PartType.UNKNOWN)
        self.assertEqual(parsed.attrs, {})
        self.assertTrue(parsed.issues)


if __name__ == "__main__":
    unittest.main()
