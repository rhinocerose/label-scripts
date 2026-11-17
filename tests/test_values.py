import unittest

from labelkit.model import PartType
from labelkit.values import (
    dielectric_key,
    format_quantity,
    normalize_package,
    parse_quantity,
    parse_resistance_mpn,
)


class QuantityTests(unittest.TestCase):
    def test_units(self):
        cases = {
            "10nF": "10nF",
            "100 nF": "100nF",
            "2.2 µF": "2.2uF",
            "100 mW": "100mW",
            "0.1W": "100mW",
            "50 V": "50V",
            "±1%": "1%",
            "0.02%": "0.02%",
            "10 kOhms": "10k",
            "16 MHz": "16MHz",
            "1/10W": "100mW",
            "100ppm": "100ppm",
            "4.7 kOhms": "4k7",
            "590 Ohms": "590R",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                quantity = parse_quantity(text)
                self.assertIsNotNone(quantity)
                self.assertEqual(quantity.text(), expected)

    def test_bare_values_need_a_default_unit(self):
        self.assertIsNone(parse_quantity("590"))
        self.assertIsNone(parse_quantity("0603"))
        self.assertEqual(parse_quantity("590", default_unit="ohm").text(), "590R")
        self.assertEqual(parse_quantity("1", default_unit="ohm").text(), "1R")
        self.assertEqual(parse_quantity("1.69M", default_unit="ohm").text(), "1M69")
        self.assertEqual(parse_quantity("4R7", default_unit="ohm").text(), "4R7")
        self.assertEqual(parse_quantity("1K3", default_unit="ohm").text(), "1k3")

    def test_formatting(self):
        self.assertEqual(format_quantity(4700, "ohm"), "4k7")
        self.assertEqual(format_quantity(0.1, "W"), "100mW")
        self.assertEqual(format_quantity(2.2e-6, "F"), "2.2uF")
        self.assertEqual(format_quantity(1e-7, "F"), "100nF")
        self.assertEqual(format_quantity(0.0001, "F"), "100uF")
        self.assertEqual(format_quantity(0.001, "ohm"), "1mR")
        self.assertEqual(format_quantity(0.0, "ohm"), "0R")

    def test_resistor_mpn_decoding(self):
        cases = {
            "RC0603FR-0710KL": "10k",
            "RC0603FR-074KL": "4k",
            "RC0603FR-072K2L": "2k2",
            "RC0603FR-071M69L": "1M69",
            "RC0603FR-0791RL": "91R",
            "RC0603FR-07715RL": "715R",
            "RC1206FR-7W1RL": "1R",
            "AC0603FR-071K3L": "1k3",
            "AF0603FR-0724KL": "24k",
        }
        for mpn, expected in cases.items():
            with self.subTest(mpn=mpn):
                quantity = parse_resistance_mpn(mpn)
                self.assertIsNotNone(quantity)
                self.assertEqual(quantity.text(), expected)

        self.assertIsNone(parse_resistance_mpn("CC0603KRX7R9BB103"))
        self.assertIsNone(parse_resistance_mpn("RT1206BRB07100K"))
        self.assertIsNone(parse_resistance_mpn("STM32F103C8T6"))

    def test_packages(self):
        self.assertEqual(normalize_package("603"), "0603")
        self.assertEqual(normalize_package("0603 (1608 Metric)"), "0603")
        self.assertEqual(normalize_package("SOT23"), "SOT-23")
        self.assertEqual(normalize_package("SOT-23-5"), "SOT-23-5")
        self.assertEqual(normalize_package("SOIC8"), "SOIC-8")
        self.assertEqual(normalize_package("TO-220"), "TO-220")
        self.assertEqual(normalize_package("1608"), "0603")
        self.assertEqual(normalize_package("1005"), "0402")
        self.assertEqual(normalize_package("3225", PartType.CAPACITOR), "1210")
        self.assertEqual(normalize_package("3225", PartType.CRYSTAL), "3225")
        self.assertEqual(normalize_package("DO-214AC"), "SMA")
        self.assertEqual(normalize_package("TO-252"), "DPAK")
        self.assertEqual(normalize_package(""), "")

        for raw in (
            "14-tssop",
            "14tssop",
            "tssop14",
            "TSSOP 14",
            "TSSOP_14",
            "TSSOP-14",
        ):
            self.assertEqual(normalize_package(raw), "TSSOP-14", raw)
        self.assertEqual(normalize_package("8-SOIC"), "SOIC-8")
        self.assertEqual(normalize_package("SOIC8"), "SOIC-8")
        self.assertEqual(normalize_package("SO-8"), "SOIC-8")
        self.assertEqual(normalize_package("8-SO"), "SOIC-8")
        self.assertEqual(normalize_package("5-SOT-23"), "SOT-23-5")
        self.assertEqual(normalize_package("3-SOT-23"), "SOT-23")
        self.assertEqual(normalize_package("2-SOD-123"), "SOD-123")
        self.assertEqual(normalize_package("3-TO-220"), "TO-220")
        self.assertEqual(normalize_package("256-BGA"), "BGA-256")
        self.assertEqual(normalize_package("PDIP-8"), "DIP-8")
        self.assertEqual(normalize_package("14-DIP"), "DIP-14")
        self.assertEqual(normalize_package("100-LQFP"), "LQFP-100")
        self.assertEqual(normalize_package("3-SIP"), "SIP-3")
        self.assertEqual(normalize_package("DO214AC"), "SMA")
        self.assertEqual(normalize_package("DO214AA"), "SMB")
        self.assertEqual(normalize_package("DO214AB"), "SMC")
        self.assertEqual(normalize_package("TO252"), "DPAK")
        self.assertEqual(normalize_package("TO263"), "D2PAK")
        self.assertEqual(normalize_package("SOT233"), "SOT-23")
        self.assertEqual(normalize_package("3-TO-252"), "DPAK")
        self.assertEqual(normalize_package("3-TO-263"), "D2PAK")

    def test_dielectric_aliases(self):
        self.assertEqual(dielectric_key("NP0"), "C0G")
        self.assertEqual(dielectric_key("NPO"), "C0G")
        self.assertEqual(dielectric_key("C0G"), "C0G")
        self.assertEqual(dielectric_key("X7R"), "X7R")


if __name__ == "__main__":
    unittest.main()
