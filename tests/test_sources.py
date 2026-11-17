import unittest
from pathlib import Path

from labelkit.model import PartType, Status
from labelkit.sources import load_input, read_mpn_lines

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class LcscSourceTests(unittest.TestCase):
    def test_capacitor_rows(self):
        parts = load_input(FIXTURES / "caps_sample.csv", trust_description=True)
        self.assertEqual(len(parts), 5)
        by_pn = {part.supplier_pn: part for part in parts}

        self.assertEqual(by_pn["C602037"].qty, 30)
        self.assertEqual(by_pn["C602037"].price, "0.0431")
        self.assertEqual(by_pn["C602037"].type, PartType.CAPACITOR)
        self.assertEqual(by_pn["C602037"].attrs["value"], "22uF")

        self.assertEqual(by_pn["C14665"].project, "Stock")
        self.assertEqual(by_pn["C100042"].project, "")
        self.assertEqual(by_pn["C519500"].attrs["value"], "220pF")
        self.assertEqual(
            sum(1 for part in parts if part.supplier_pn == "C519500"), 2
        )

    def test_resistor_rows(self):
        parts = load_input(
            FIXTURES / "resistors_sample.csv", trust_description=True
        )
        self.assertEqual(len(parts), 15)
        self.assertTrue(all(part.type is PartType.RESISTOR for part in parts))
        by_pn = {part.supplier_pn: part for part in parts}

        self.assertEqual(by_pn["C273786"].attrs["value"], "590R")
        self.assertEqual(by_pn["C137215"].attrs["value"], "1R")
        self.assertEqual(by_pn["C137215"].attrs["rating"], "500mW")
        self.assertEqual(by_pn["C227650"].attrs["value"], "1k33")
        self.assertEqual(by_pn["C42404610"].attrs["rating"], "100mW")
        self.assertEqual(by_pn["C42404610"].qty, 5)
        self.assertEqual(by_pn["C42404610"].project, "Cap Tester")
        self.assertEqual(by_pn["C22548"].field_sources["value"], "description")

    def test_header_mapped_csv(self):
        parts = load_input(FIXTURES / "lcsc_header.csv", trust_description=True)
        self.assertEqual(len(parts), 2)
        by_pn = {part.supplier_pn: part for part in parts}
        self.assertEqual(by_pn["C100042"].qty, 25)
        self.assertEqual(by_pn["C100042"].attrs["value"], "10nF")
        self.assertEqual(by_pn["C22548"].attrs["value"], "1k")


    def test_default_is_mpn_only(self):
        parts = load_input(FIXTURES / "caps_sample.csv")
        self.assertEqual(len(parts), 5)
        part = next(p for p in parts if p.supplier_pn == "C100042")
        self.assertEqual(part.type, PartType.CAPACITOR)  # from the MPN prefix
        self.assertEqual(part.attrs, {})  # description not parsed
        self.assertEqual(part.source_description, "50V 10nF X7R 10% 0603")
        self.assertEqual(part.status, Status.UNVERIFIED)


    def test_part_number_csv(self):
        parts = load_input(FIXTURES / "part_numbers.csv")
        self.assertEqual(len(parts), 2)

        self.assertEqual(parts[0].source, "lcsc")
        self.assertEqual(parts[0].supplier_pn, "C22548")
        self.assertEqual(parts[0].mpn, "")
        self.assertEqual(parts[0].qty, 100)
        self.assertEqual(parts[0].type, PartType.UNKNOWN)

        self.assertEqual(parts[1].source, "manual")
        self.assertEqual(parts[1].mpn, "RC0603FR-071K")
        self.assertEqual(parts[1].type, PartType.RESISTOR)
        self.assertEqual(parts[1].qty, 50)

    def test_lcsc_mpn_pairs_csv(self):
        parts = load_input(FIXTURES / "lcsc_mpn_pairs.csv")
        self.assertEqual(len(parts), 3)

        self.assertEqual(parts[0].supplier_pn, "C22548")
        self.assertEqual(parts[0].mpn, "RC0603FR-071K")
        self.assertEqual(parts[0].qty, 100)

        self.assertEqual(parts[1].supplier_pn, "C100042")
        self.assertEqual(parts[1].mpn, "")
        self.assertEqual(parts[1].type, PartType.UNKNOWN)

        self.assertEqual(parts[2].supplier_pn, "")
        self.assertEqual(parts[2].mpn, "GRM1555C1H471JA01D")
        self.assertEqual(parts[2].type, PartType.CAPACITOR)
        self.assertEqual(parts[2].qty, 50)


class ManualSourceTests(unittest.TestCase):
    def test_mpn_lines(self):
        parts = read_mpn_lines(
            [
                "# comment",
                "",
                "RC0603FR-0710KL",
                "GRM1555C1H471JA01D",
                "C12345",
                "2N3904 100",
            ]
        )
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0].source, "manual")
        self.assertEqual(parts[0].type, PartType.RESISTOR)
        self.assertEqual(parts[0].attrs, {})
        self.assertEqual(parts[1].type, PartType.CAPACITOR)
        self.assertEqual(parts[2].source, "lcsc")
        self.assertEqual(parts[2].status, Status.UNVERIFIED)
        self.assertEqual(parts[3].type, PartType.TRANSISTOR)
        self.assertEqual(parts[3].qty, 100)

    def test_generic_mpn_csv(self):
        parts = load_input(FIXTURES / "generic_mpns.csv")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].source, "manual")
        self.assertEqual(parts[0].mpn, "RC0603FR-0710KL")
        self.assertEqual(parts[0].qty, 10)
        self.assertEqual(parts[1].type, PartType.CAPACITOR)
        self.assertEqual(parts[1].qty, 25)

    def test_mpn_text_file(self):
        parts = load_input(FIXTURES / "mpns.txt")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].type, PartType.RESISTOR)
        self.assertEqual(parts[1].type, PartType.CAPACITOR)


if __name__ == "__main__":
    unittest.main()
