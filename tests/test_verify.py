import unittest
from pathlib import Path

from labelkit.model import Part, PartType, ProviderResult, Status
from labelkit.sources import load_input
from labelkit.values import parse_quantity
from labelkit.verify import merge

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_UNIT_BY_FIELD = {
    (PartType.RESISTOR, "value"): "ohm",
    (PartType.CAPACITOR, "value"): "F",
    (PartType.INDUCTOR, "value"): "H",
    (PartType.CRYSTAL, "value"): "Hz",
    (PartType.RESISTOR, "rating"): "W",
    (PartType.CAPACITOR, "rating"): "V",
    (PartType.INDUCTOR, "rating"): "A",
    (PartType.DIODE, "rating"): "V",
    (PartType.LED, "rating"): "V",
    (PartType.TRANSISTOR, "rating"): "V",
    (PartType.DIODE, "current"): "A",
    (PartType.LED, "current"): "A",
    (PartType.TRANSISTOR, "current"): "A",
    (PartType.CRYSTAL, "load"): "F",
}


def _provider(part: Part, **overrides) -> ProviderResult:
    attrs = dict(part.attrs)
    attrs.update(overrides)
    values = dict(part.values)
    for field, text in overrides.items():
        unit = _UNIT_BY_FIELD.get((part.type, field))
        if field == "tolerance":
            unit = "%"
        quantity = parse_quantity(text, default_unit=unit)
        if quantity is not None:
            values[field] = quantity
    return ProviderResult(
        provider="DigiKey",
        mpn=part.mpn,
        type=part.type,
        attrs=attrs,
        values=values,
        manufacturer="Test",
        datasheet="https://example/ds.pdf",
    )


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        caps = load_input(FIXTURES / "caps_sample.csv", trust_description=True)
        resistors = load_input(
            FIXTURES / "resistors_sample.csv", trust_description=True
        )
        cls.cap = next(p for p in caps if p.supplier_pn == "C100042")
        cls.np0_cap = next(p for p in caps if p.supplier_pn == "C14665")
        cls.resistor = next(p for p in resistors if p.supplier_pn == "C22548")

    def test_matching_values_verify(self):
        merge(self.cap, _provider(self.cap))
        self.assertEqual(self.cap.status, Status.VERIFIED)
        self.assertEqual(self.cap.verified_by, "DigiKey")
        # The description's manufacturer is kept; the provider only fills gaps.
        self.assertEqual(self.cap.manufacturer, "YAGEO")

    def test_value_mismatch_blocks(self):
        part = load_input(FIXTURES / "caps_sample.csv", trust_description=True)[0]
        merge(part, _provider(part, value="11nF"))
        self.assertEqual(part.status, Status.MISMATCH)
        self.assertTrue(any(issue.startswith("value:") for issue in part.issues))
        self.assertEqual(part.extra["mismatches"][0][0], "value")

    def test_dielectric_aliases_are_equal(self):
        merge(self.np0_cap, _provider(self.np0_cap, dielectric="C0G"))
        self.assertEqual(self.np0_cap.status, Status.VERIFIED)

    def test_metric_package_is_equal(self):
        merge(self.np0_cap, _provider(self.np0_cap, package="0603 (1608 Metric)"))
        self.assertEqual(self.np0_cap.status, Status.VERIFIED)
        self.assertEqual(self.np0_cap.attrs["package"], "0603")

    def test_tolerance_formatting_is_equal(self):
        merge(self.cap, _provider(self.cap, tolerance="±10.0%"))
        self.assertEqual(self.cap.status, Status.VERIFIED)

    def test_provider_fills_missing_fields(self):
        part = Part(source="manual", mpn="RC0603FR-0710KL", type=PartType.RESISTOR)
        provider = ProviderResult(
            provider="DigiKey",
            mpn=part.mpn,
            type=PartType.RESISTOR,
            attrs={
                "value": "10k",
                "rating": "100mW",
                "tolerance": "1%",
                "package": "0603",
            },
            values={"value": parse_quantity("10k", default_unit="ohm")},
        )
        merge(part, provider)
        self.assertEqual(part.status, Status.VERIFIED)
        self.assertEqual(part.attrs["value"], "10k")
        self.assertEqual(part.attrs["package"], "0603")
        self.assertEqual(part.field_sources["value"], "DigiKey")

    def test_missing_required_value_blocks(self):
        part = Part(source="manual", mpn="RC0603FR-0710KL", type=PartType.RESISTOR)
        provider = ProviderResult(
            provider="DigiKey",
            mpn=part.mpn,
            type=PartType.RESISTOR,
            attrs={"package": "0603"},
        )
        merge(part, provider)
        self.assertEqual(part.status, Status.BLOCKED)
        self.assertTrue(any("missing value" in issue for issue in part.issues))

    def test_type_mismatch_blocks(self):
        part = load_input(FIXTURES / "caps_sample.csv", trust_description=True)[0]
        provider = ProviderResult(
            provider="DigiKey",
            mpn=part.mpn,
            type=PartType.RESISTOR,
            attrs={"value": "10k", "package": "0603"},
        )
        merge(part, provider)
        self.assertEqual(part.status, Status.MISMATCH)
        self.assertTrue(any(issue.startswith("type:") for issue in part.issues))

    def test_rating_mismatch_blocks(self):
        part = load_input(
            FIXTURES / "resistors_sample.csv", trust_description=True
        )[0]
        merge(part, _provider(part, rating="250mW"))
        self.assertEqual(part.status, Status.MISMATCH)
        self.assertTrue(any(issue.startswith("rating:") for issue in part.issues))


if __name__ == "__main__":
    unittest.main()
