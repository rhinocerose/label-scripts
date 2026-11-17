import unittest

from labelkit.descriptions import describe
from labelkit.model import Part, PartType


class DescriptionTests(unittest.TestCase):
    def test_resistors_and_capacitors_have_no_description(self):
        for ptype in (PartType.RESISTOR, PartType.CAPACITOR):
            part = Part(
                type=ptype,
                attrs={
                    "value": "1k",
                    "rating": "100mW",
                    "tolerance": "1%",
                    "package": "0603",
                },
            )
            self.assertEqual(describe(part), "")

    def test_inductor(self):
        part = Part(
            type=PartType.INDUCTOR,
            attrs={"value": "1uH", "rating": "1.5A", "package": "0603"},
        )
        self.assertEqual(describe(part), "1uH 1.5A 0603 inductor")

    def test_ferrite_bead(self):
        part = Part(
            type=PartType.INDUCTOR,
            attrs={
                "value": "120R",
                "rating": "1A",
                "package": "0603",
                "kind": "Ferrite Bead",
            },
        )
        self.assertEqual(describe(part), "120R 1A 0603 ferrite bead")

    def test_diode(self):
        part = Part(
            type=PartType.DIODE,
            attrs={
                "kind": "Schottky",
                "rating": "40V",
                "current": "1A",
                "package": "SOD-123",
            },
        )
        self.assertEqual(describe(part), "schottky 40V 1A SOD-123 diode")

    def test_led(self):
        part = Part(
            type=PartType.LED,
            attrs={
                "color": "Green",
                "rating": "2.1V",
                "current": "20mA",
                "package": "0603",
            },
        )
        self.assertEqual(describe(part), "green 2.1V 20mA 0603 led")

    def test_transistor(self):
        part = Part(
            type=PartType.TRANSISTOR,
            attrs={
                "polarity": "NPN",
                "rating": "40V",
                "current": "200mA",
                "package": "SOT-23",
            },
        )
        self.assertEqual(describe(part), "npn 40V 200mA SOT-23 transistor")

    def test_crystal(self):
        part = Part(
            type=PartType.CRYSTAL,
            attrs={
                "value": "16MHz",
                "load": "20pF",
                "stability": "30ppm",
                "package": "3225",
            },
        )
        self.assertEqual(describe(part), "16MHz 20pF 30ppm 3225 crystal")

    def test_dac(self):
        part = Part(
            type=PartType.IC,
            attrs={
                "type_word": "dac",
                "channels": "4",
                "resolution": "12",
                "package": "TSSOP-16",
            },
        )
        self.assertEqual(describe(part), "4-ch 12-bit dac")

    def test_adc(self):
        part = Part(
            type=PartType.IC,
            attrs={
                "type_word": "adc",
                "channels": "2",
                "resolution": "16",
                "package": "QFN-32",
            },
        )
        self.assertEqual(describe(part), "2-ch 16-bit adc")

    def test_op_amp(self):
        part = Part(
            type=PartType.IC,
            attrs={
                "type_word": "op-amp",
                "channels": "2",
                "bandwidth": "10MHz",
                "package": "SOIC-8",
            },
        )
        self.assertEqual(describe(part), "2-ch 10MHz op-amp")

    def test_regulator(self):
        part = Part(
            type=PartType.IC,
            attrs={
                "type_word": "regulator",
                "topology": "LDO",
                "supply": "3.3V",
                "current": "1A",
                "package": "SOT-223",
            },
        )
        self.assertEqual(describe(part), "ldo 3.3V 1A SOT-223 regulator")

    def test_mcu(self):
        part = Part(
            type=PartType.IC,
            attrs={
                "type_word": "mcu",
                "core": "ARM Cortex-M3",
                "speed": "72MHz",
                "flash": "64KB",
                "package": "LQFP-48",
            },
        )
        self.assertEqual(
            describe(part), "arm cortex-m3 72MHz 64KB LQFP-48 mcu"
        )

    def test_generic_ic(self):
        part = Part(
            type=PartType.IC,
            attrs={"type_word": "eeprom", "package": "SOIC-8"},
        )
        self.assertEqual(describe(part), "eeprom SOIC-8")

    def test_unknown(self):
        self.assertEqual(describe(Part(type=PartType.UNKNOWN)), "")


if __name__ == "__main__":
    unittest.main()
