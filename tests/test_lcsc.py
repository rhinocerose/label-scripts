import json
import tempfile
import unittest
from pathlib import Path

from labelkit.cache import Cache
from labelkit.descriptions import describe
from labelkit.lcsc import LcscResolver
from labelkit.model import Part, PartType


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, payload=None, page_html=""):
        self.payload = payload or {}
        self.page_html = page_html
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "wmsc.lcsc.com" in url:
            return FakeResponse(200, json.dumps(self.payload))
        return FakeResponse(200, self.page_html)

    def close(self):
        pass


def _resistor_product():
    return {
        "productCode": "C22548",
        "productModel": "RC0603FR-071K",
        "brandNameEn": "YAGEO",
        "productIntroEn": "Thick Film Resistors 1k",
        "parentCatalogName": "Resistors",
        "catalogName": "Chip Resistor - Surface Mount",
        "pdfUrl": "https://example/ds.pdf",
        "paramVOList": [
            {"paramNameEn": "Resistance", "paramValueEn": "1kΩ"},
            {"paramNameEn": "Tolerance", "paramValueEn": "±1%"},
            {"paramNameEn": "Power", "paramValueEn": "100mW"},
            {"paramNameEn": "Package", "paramValueEn": "0603"},
        ],
    }


def _resistor_payload():
    return {"result": {"productList": [_resistor_product()]}}


def _capacitor_payload():
    return {
        "result": {
            "productList": [
                {
                    "productCode": "C100042",
                    "productModel": "CC0603KRX7R9BB103",
                    "brandNameEn": "YAGEO",
                    "productIntroEn": "Ceramic Capacitor 10nF 50V X7R 0603",
                    "parentCatalogName": "Capacitors",
                    "catalogName": "Ceramic Capacitors",
                    "paramVOList": [
                        {"paramNameEn": "Capacitance", "paramValueEn": "10nF"},
                        {"paramNameEn": "Voltage Rated", "paramValueEn": "50V"},
                        {"paramNameEn": "Tolerance", "paramValueEn": "±10%"},
                        {"paramNameEn": "Dielectric", "paramValueEn": "X7R"},
                        {"paramNameEn": "Package", "paramValueEn": "0603"},
                    ],
                }
            ]
        }
    }


def _dac_payload():
    return {
        "result": {
            "productList": [
                {
                    "productCode": "C1234",
                    "productModel": "DAC8564",
                    "brandNameEn": "Texas Instruments",
                    "productIntroEn": "4-channel 12-bit DAC",
                    "parentCatalogName": "Integrated Circuits (ICs)",
                    "catalogName": "Digital to Analog Converters (DAC)",
                    "paramVOList": [
                        {
                            "paramNameEn": "Number of D/A Converters",
                            "paramValueEn": "4",
                        },
                        {"paramNameEn": "Number of Bits", "paramValueEn": "12"},
                        {
                            "paramNameEn": "Package / Case",
                            "paramValueEn": "TSSOP-16",
                        },
                    ],
                }
            ]
        }
    }


class LcscResolverTests(unittest.TestCase):
    def _resolver(self, session, cache=None):
        return LcscResolver(session=session, cache=cache, min_interval=0)

    def test_lookup_by_pn(self):
        provider = self._resolver(FakeSession(_resistor_payload())).lookup_by_pn(
            "C22548"
        )
        self.assertIsNotNone(provider)
        self.assertEqual(provider.provider, "LCSC")
        self.assertEqual(provider.supplier_pn, "C22548")
        self.assertEqual(provider.mpn, "RC0603FR-071K")
        self.assertEqual(provider.manufacturer, "YAGEO")
        self.assertEqual(provider.type, PartType.RESISTOR)
        self.assertEqual(provider.attrs["value"], "1k")
        self.assertEqual(provider.attrs["rating"], "100mW")
        self.assertEqual(provider.attrs["tolerance"], "1%")
        self.assertEqual(provider.attrs["package"], "0603")
        self.assertEqual(provider.datasheet, "https://example/ds.pdf")

    def test_lookup_by_mpn_fills_supplier_pn(self):
        provider = self._resolver(FakeSession(_resistor_payload())).lookup_by_mpn(
            "RC0603FR-071K"
        )
        self.assertIsNotNone(provider)
        self.assertEqual(provider.supplier_pn, "C22548")

    def test_cache_avoids_second_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(Path(tmp) / "cache.db")
            session = FakeSession(_resistor_payload())
            resolver = self._resolver(session, cache=cache)

            resolver.lookup_by_pn("C22548")
            first = sum(1 for url, _ in session.calls if "wmsc.lcsc.com" in url)
            resolver.lookup_by_pn("C22548")
            second = sum(1 for url, _ in session.calls if "wmsc.lcsc.com" in url)

            self.assertEqual(first, 1)
            self.assertEqual(second, 1)
            cache.close()

    def test_capacitor_mapping(self):
        provider = self._resolver(FakeSession(_capacitor_payload())).lookup_by_pn(
            "C100042"
        )
        self.assertEqual(provider.type, PartType.CAPACITOR)
        self.assertEqual(provider.attrs["value"], "10nF")
        self.assertEqual(provider.attrs["rating"], "50V")
        self.assertEqual(provider.attrs["tolerance"], "10%")
        self.assertEqual(provider.attrs["dielectric"], "X7R")
        self.assertEqual(provider.attrs["package"], "0603")

    def test_dac_description(self):
        provider = self._resolver(FakeSession(_dac_payload())).lookup_by_pn("C1234")
        self.assertEqual(provider.type, PartType.IC)
        self.assertEqual(provider.attrs["type_word"], "dac")
        self.assertEqual(provider.attrs["channels"], "4")
        self.assertEqual(provider.attrs["resolution"], "12")

        part = Part(mpn=provider.mpn, type=provider.type, attrs=provider.attrs)
        self.assertEqual(describe(part), "4-ch 12-bit dac")

    def test_no_match_returns_none(self):
        provider = self._resolver(FakeSession({}, page_html="")).lookup_by_pn(
            "C999999"
        )
        self.assertIsNone(provider)

    def test_product_page_fallback(self):
        payload = {
            "props": {
                "pageProps": {
                    "product": _resistor_product(),
                }
            }
        }
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>"
        )
        session = FakeSession({}, page_html=html)
        provider = self._resolver(session).lookup_by_pn("C22548")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.mpn, "RC0603FR-071K")
        self.assertEqual(provider.attrs["value"], "1k")


if __name__ == "__main__":
    unittest.main()
