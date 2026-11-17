import csv
import tempfile
import unittest
from pathlib import Path

from labelkit.model import Part, PartType, ProviderResult, Status
from labelkit.pipeline import run_pipeline
from labelkit.sources import load_input, read_mpn_lines
from labelkit.values import parse_quantity

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResolver:
    available = True
    reason_unavailable = ""

    def __init__(self, providers):
        self.providers = {key.upper(): value for key, value in providers.items()}
        self.last_candidates: list[str] = []

    def lookup(self, mpn):
        return self.providers.get(mpn.upper())


class FakeLcsc:
    available = True
    reason_unavailable = ""

    def __init__(self, by_pn=None, by_mpn=None):
        self.by_pn = {key.upper(): value for key, value in (by_pn or {}).items()}
        self.by_mpn = {key.upper(): value for key, value in (by_mpn or {}).items()}
        self.last_candidates: list[str] = []

    def lookup_by_pn(self, pn):
        return self.by_pn.get(pn.upper())

    def lookup_by_mpn(self, mpn):
        return self.by_mpn.get(mpn.upper())


def _resistor_provider(provider: str, value: str = "1k") -> ProviderResult:
    return ProviderResult(
        provider=provider,
        mpn="RC0603FR-071K",
        supplier_pn="C22548" if provider == "LCSC" else "",
        type=PartType.RESISTOR,
        attrs={
            "value": value,
            "rating": "100mW",
            "tolerance": "1%",
            "package": "0603",
        },
        values={
            "value": parse_quantity(value, default_unit="ohm"),
            "rating": parse_quantity("100mW"),
            "tolerance": parse_quantity("1%"),
        },
    )


def _provider_for(part) -> ProviderResult:
    return ProviderResult(
        provider="DigiKey",
        mpn=part.mpn,
        type=part.type,
        attrs=dict(part.attrs),
        values=dict(part.values),
        manufacturer="Test",
        datasheet="",
    )


def _providers(parts) -> dict[str, ProviderResult]:
    providers = {}
    for part in parts:
        if part.mpn and part.type is not PartType.UNKNOWN:
            providers.setdefault(part.mpn, _provider_for(part))
    return providers


def _read_csv(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


class PipelineTests(unittest.TestCase):
    def _parts(self):
        return load_input(
            FIXTURES / "caps_sample.csv", trust_description=True
        ) + load_input(
            FIXTURES / "resistors_sample.csv", trust_description=True
        )

    def test_lcsc_invoice_mpn_only_is_filled_from_provider(self):
        part = next(
            p
            for p in load_input(FIXTURES / "caps_sample.csv")
            if p.supplier_pn == "C100042"
        )
        self.assertEqual(part.attrs, {})  # description was not parsed

        provider = ProviderResult(
            provider="DigiKey",
            mpn=part.mpn,
            type=PartType.CAPACITOR,
            attrs={
                "value": "10nF",
                "rating": "50V",
                "tolerance": "10%",
                "dielectric": "X7R",
                "package": "0603",
            },
            values={
                "value": parse_quantity("10nF"),
                "rating": parse_quantity("50V"),
                "tolerance": parse_quantity("10%"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_pipeline(
                [part],
                out_dir=tmp,
                resolver=FakeResolver({part.mpn: provider}),
                interactive=False,
            )
            rows = _read_csv(Path(tmp) / "capacitor.csv")
            self.assertEqual(
                rows[1],
                ["C100042", "CC0603KRX7R9BB103", "10nF", "50V", "10%", "X7R", "0603"],
            )

    def test_mpn_only_without_provider_blocks_even_if_allowed(self):
        parts = load_input(FIXTURES / "caps_sample.csv")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=None,
                allow_unverified=True,
                interactive=False,
            )
            self.assertEqual(result.stats["printable"], 0)
            self.assertEqual(result.stats["blocked"], 4)
            self.assertFalse((Path(tmp) / "capacitor.csv").exists())
            self.assertTrue(
                any("not verified" in issue for issue in result.parts[0].issues)
            )

    def test_verified_run(self):
        parts = self._parts()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=FakeResolver(_providers(parts)),
                interactive=False,
            )

            self.assertEqual(result.stats["total"], 19)
            self.assertEqual(result.stats["verified"], 19)
            self.assertEqual(result.stats["printable"], 19)
            self.assertEqual(result.stats["duplicates_merged"], 1)
            self.assertEqual(result.stats["blocked"], 0)

            self.assertEqual(len(_read_csv(Path(tmp) / "capacitor.csv")), 5)
            self.assertEqual(len(_read_csv(Path(tmp) / "resistor.csv")), 16)
            self.assertEqual(len(_read_csv(Path(tmp) / "review.csv")), 1)

            with open(Path(tmp) / "parts.csv", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            duplicate = [row for row in rows if row["supplier_pn"] == "C519500"]
            self.assertEqual(len(duplicate), 1)
            self.assertEqual(int(duplicate[0]["qty"]), 100)

    def test_mismatch_blocks_and_is_excluded(self):
        parts = self._parts()
        providers = _providers(parts)
        target = next(part for part in parts if part.supplier_pn == "C22548")
        providers[target.mpn] = ProviderResult(
            provider="DigiKey",
            mpn=target.mpn,
            type=target.type,
            attrs={**target.attrs, "value": "2k"},
            values={
                **target.values,
                "value": parse_quantity("2k", default_unit="ohm"),
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=FakeResolver(providers),
                interactive=False,
            )
            self.assertEqual(result.stats["mismatch"], 1)
            self.assertEqual(result.stats["printable"], 18)

            resistor_rows = _read_csv(Path(tmp) / "resistor.csv")
            self.assertEqual(len(resistor_rows), 15)  # 14 + header
            self.assertNotIn("C22548", {row[0] for row in resistor_rows[1:]})

            review = _read_csv(Path(tmp) / "review.csv")
            self.assertEqual(len(review), 2)
            self.assertEqual(review[1][0], "mismatch")
            self.assertEqual(review[1][2], "C22548")
            self.assertEqual(review[1][3], "RC0603FR-071K")

    def test_offline_allow_unverified_prints_with_warning(self):
        parts = self._parts()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=None,
                allow_unverified=True,
                interactive=False,
            )
            self.assertEqual(result.stats["printable"], 19)
            self.assertEqual(result.stats["unverified"], 19)
            self.assertTrue(
                all(part.status is Status.UNVERIFIED for part in result.printable)
            )
            self.assertEqual(len(_read_csv(Path(tmp) / "capacitor.csv")), 5)
            self.assertEqual(len(_read_csv(Path(tmp) / "resistor.csv")), 16)
            self.assertEqual(len(_read_csv(Path(tmp) / "review.csv")), 20)

    def test_offline_blocks_by_default(self):
        parts = self._parts()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=None,
                allow_unverified=False,
                interactive=False,
            )
            self.assertEqual(result.stats["printable"], 0)
            self.assertEqual(result.stats["blocked"], 19)
            self.assertFalse((Path(tmp) / "capacitor.csv").exists())
            self.assertFalse((Path(tmp) / "resistor.csv").exists())
            self.assertEqual(len(_read_csv(Path(tmp) / "review.csv")), 20)

    def test_manual_mpn_is_filled_from_provider(self):
        parts = read_mpn_lines(["RC0603FR-0710KL"], source="test")
        provider = ProviderResult(
            provider="DigiKey",
            mpn=parts[0].mpn,
            type=PartType.RESISTOR,
            attrs={
                "value": "10k",
                "rating": "100mW",
                "tolerance": "1%",
                "package": "0603",
            },
            values={
                "value": parse_quantity("10k", default_unit="ohm"),
                "rating": parse_quantity("100mW"),
                "tolerance": parse_quantity("1%"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_pipeline(
                parts,
                out_dir=tmp,
                resolver=FakeResolver({parts[0].mpn: provider}),
                interactive=False,
            )
            rows = _read_csv(Path(tmp) / "resistor.csv")
            self.assertEqual(
                rows[1],
                ["", "RC0603FR-0710KL", "10k", "100mW", "1%", "0603"],
            )

    def test_manual_mpn_without_value_is_blocked(self):
        parts = read_mpn_lines(["RC0603FR-0710KL"], source="test")
        provider = ProviderResult(
            provider="DigiKey",
            mpn=parts[0].mpn,
            type=PartType.RESISTOR,
            attrs={"package": "0603"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                parts,
                out_dir=tmp,
                resolver=FakeResolver({parts[0].mpn: provider}),
                interactive=False,
            )
            self.assertEqual(result.stats["blocked"], 1)
            self.assertIn("missing value", " ".join(result.parts[0].issues))
            self.assertFalse((Path(tmp) / "resistor.csv").exists())

    def test_lcsc_pn_only_resolves_mpn_and_digikey(self):
        part = Part(source="lcsc", supplier_pn="C22548", qty=1)
        lcsc = FakeLcsc(by_pn={"C22548": _resistor_provider("LCSC")})
        digikey = FakeResolver(
            {"RC0603FR-071K": _resistor_provider("DigiKey")}
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                [part],
                out_dir=tmp,
                resolver=digikey,
                lcsc_resolver=lcsc,
                interactive=False,
            )
            self.assertEqual(part.mpn, "RC0603FR-071K")
            self.assertEqual(part.supplier_pn, "C22548")
            self.assertEqual(part.status, Status.VERIFIED)
            self.assertEqual(part.verified_by, "DigiKey+LCSC")
            self.assertEqual(result.stats["printable"], 1)
            rows = _read_csv(Path(tmp) / "resistor.csv")
            self.assertEqual(
                rows[1],
                ["C22548", "RC0603FR-071K", "1k", "100mW", "1%", "0603"],
            )

    def test_lcsc_alone_resolves_mpn_only_part(self):
        part = Part(source="manual", mpn="RC0603FR-071K", qty=5)
        lcsc = FakeLcsc(by_mpn={"RC0603FR-071K": _resistor_provider("LCSC")})
        with tempfile.TemporaryDirectory() as tmp:
            run_pipeline(
                [part],
                out_dir=tmp,
                resolver=None,
                lcsc_resolver=lcsc,
                interactive=False,
            )
            self.assertEqual(part.status, Status.VERIFIED)
            self.assertEqual(part.verified_by, "LCSC")
            self.assertEqual(part.supplier_pn, "C22548")
            rows = _read_csv(Path(tmp) / "resistor.csv")
            self.assertEqual(rows[1][0], "C22548")

    def test_conflict_flags_but_still_prints(self):
        part = Part(source="manual", mpn="RC0603FR-071K", qty=1)
        lcsc = FakeLcsc(
            by_mpn={"RC0603FR-071K": _resistor_provider("LCSC", value="1k")}
        )
        digikey = FakeResolver(
            {"RC0603FR-071K": _resistor_provider("DigiKey", value="2k")}
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                [part],
                out_dir=tmp,
                resolver=digikey,
                lcsc_resolver=lcsc,
                interactive=False,
            )
            self.assertEqual(part.status, Status.VERIFIED)
            self.assertEqual(result.stats["conflicts"], 1)
            rows = _read_csv(Path(tmp) / "resistor.csv")
            self.assertEqual(rows[1][2], "2k")  # DigiKey wins
            review = _read_csv(Path(tmp) / "review.csv")
            self.assertEqual(len(review), 2)
            self.assertIn("value", review[1][6])

    def test_strict_conflict_blocks(self):
        part = Part(source="manual", mpn="RC0603FR-071K", qty=1)
        lcsc = FakeLcsc(
            by_mpn={"RC0603FR-071K": _resistor_provider("LCSC", value="1k")}
        )
        digikey = FakeResolver(
            {"RC0603FR-071K": _resistor_provider("DigiKey", value="2k")}
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                [part],
                out_dir=tmp,
                resolver=digikey,
                lcsc_resolver=lcsc,
                interactive=False,
                strict=True,
            )
            self.assertEqual(part.status, Status.MISMATCH)
            self.assertEqual(result.stats["printable"], 0)
            self.assertFalse((Path(tmp) / "resistor.csv").exists())

    def test_lcsc_pn_only_without_lcsc_blocks(self):
        part = Part(source="lcsc", supplier_pn="C22548", qty=1)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                [part],
                out_dir=tmp,
                resolver=None,
                lcsc_resolver=None,
                interactive=False,
            )
            self.assertEqual(result.stats["blocked"], 1)
            self.assertIn("no MPN", " ".join(result.parts[0].issues))

    def test_description_column_is_written_for_diode(self):
        part = Part(source="manual", mpn="1N4148W", type=PartType.DIODE)
        provider = ProviderResult(
            provider="DigiKey",
            mpn="1N4148W",
            type=PartType.DIODE,
            attrs={
                "kind": "Schottky",
                "rating": "40V",
                "current": "1A",
                "package": "SOD-123",
            },
            values={
                "rating": parse_quantity("40V"),
                "current": parse_quantity("1A"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_pipeline(
                [part],
                out_dir=tmp,
                resolver=FakeResolver({"1N4148W": provider}),
                interactive=False,
            )
            rows = _read_csv(Path(tmp) / "diode.csv")
            self.assertEqual(rows[0][-1], "Description")
            self.assertEqual(
                rows[1],
                [
                    "",
                    "1N4148W",
                    "40V",
                    "1A",
                    "SOD-123",
                    "schottky 40V 1A SOD-123 diode",
                ],
            )


if __name__ == "__main__":
    unittest.main()
