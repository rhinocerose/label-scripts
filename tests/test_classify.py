import unittest

from labelkit.classify import classify_category, classify_description, classify_mpn
from labelkit.model import PartType


class ClassifyDescriptionTests(unittest.TestCase):
    def test_representative_descriptions(self):
        cases = {
            "50V 10nF X7R 10% 0603": PartType.CAPACITOR,
            "100mW 1k 1% 0603": PartType.RESISTOR,
            "100mW 1k 75V 1% 0603": PartType.RESISTOR,
            "16MHz 20pF 30ppm 3225": PartType.CRYSTAL,
            "Green 2.1V 20mA 0603": PartType.LED,
            "Schottky 40V 1A SOD-123": PartType.DIODE,
            "NPN 40V 200mA SOT-23": PartType.TRANSISTOR,
            "SOIC-8": PartType.IC,
            "14-TSSOP": PartType.IC,
            "Ferrite Bead 120 Ohm 1A": PartType.INDUCTOR,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                ptype, confidence, reasons = classify_description(text)
                self.assertEqual(ptype, expected)
                self.assertGreater(confidence, 0.0)
                self.assertTrue(reasons)

    def test_unknown(self):
        ptype, confidence, _ = classify_description("mystery component")
        self.assertEqual(ptype, PartType.UNKNOWN)
        self.assertEqual(confidence, 0.0)

    def test_package_hint_with_pins_first(self):
        ptype, _confidence, _reasons = classify_description(
            "", package="14-TSSOP"
        )
        self.assertEqual(ptype, PartType.IC)

    def test_mpn_fallback(self):
        ptype, confidence, _ = classify_description("", mpn="RC0603FR-0710KL")
        self.assertEqual(ptype, PartType.RESISTOR)
        self.assertGreater(confidence, 0.0)


class ClassifyMpnTests(unittest.TestCase):
    def test_prefixes(self):
        cases = {
            "RC0603FR-0710KL": PartType.RESISTOR,
            "AC0603FR-071K3L": PartType.RESISTOR,
            "CC0603KRX7R9BB103": PartType.CAPACITOR,
            "GRM1555C1H471JA01D": PartType.CAPACITOR,
            "CL10B105KA8NNNC": PartType.CAPACITOR,
            "1N4148W": PartType.DIODE,
            "BAT54S": PartType.DIODE,
            "LTST-C190KGKT": PartType.LED,
            "2N3904": PartType.TRANSISTOR,
            "BSS138": PartType.TRANSISTOR,
            "STM32F103C8T6": PartType.IC,
            "NE555P": PartType.IC,
            "ABM8-16.000MHZ-B2-T": PartType.CRYSTAL,
            "BLM18PG121SN1D": PartType.INDUCTOR,
        }
        for mpn, expected in cases.items():
            with self.subTest(mpn=mpn):
                self.assertEqual(classify_mpn(mpn), expected)

    def test_unknown_prefix(self):
        self.assertIsNone(classify_mpn("XYZ123"))


class ClassifyCategoryTests(unittest.TestCase):
    def test_digikey_categories(self):
        cases = {
            "Resistors/Chip Resistor - Surface Mount": PartType.RESISTOR,
            "Capacitors/Ceramic Capacitors": PartType.CAPACITOR,
            "Inductors, Coils, Chokes/Fixed Inductors": PartType.INDUCTOR,
            "Discrete Semiconductor Products/Diodes/Rectifiers - Single": PartType.DIODE,
            "Optoelectronics/LED Indication": PartType.LED,
            "Transistors/Bipolar (BJT)/Single": PartType.TRANSISTOR,
            "Crystals, Oscillators, Resonators/Crystals": PartType.CRYSTAL,
            "Integrated Circuits (ICs)/Microcontrollers": PartType.IC,
        }
        for category, expected in cases.items():
            with self.subTest(category=category):
                ptype, confidence, reasons = classify_category(category)
                self.assertEqual(ptype, expected)
                self.assertGreaterEqual(confidence, 0.9)

    def test_parameter_fallback(self):
        ptype, _, _ = classify_category(
            "", parameter_names=("Resistance", "Tolerance")
        )
        self.assertEqual(ptype, PartType.RESISTOR)

    def test_unknown(self):
        ptype, confidence, _ = classify_category("")
        self.assertEqual(ptype, PartType.UNKNOWN)
        self.assertEqual(confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
