import tempfile
import unittest
from pathlib import Path

from labelkit.cache import Cache
from labelkit.digikey import DigiKeyResolver
from labelkit.model import PartType


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None, text=""):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeSession:
    def __init__(self, search_data):
        self.search_data = search_data
        self.posts: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if "oauth2" in url:
            return FakeResponse(200, {"access_token": "tok", "expires_in": 600})
        return FakeResponse(200, self.search_data)

    def close(self):
        pass


def _resistor_payload(mpn="RC0603FR-0710KL"):
    return {
        "Parts": [
            {
                "ManufacturerPartNumber": mpn,
                "DigiKeyPartNumber": "311-10KHRCT-ND",
                "Manufacturer": {"Value": "YAGEO"},
                "ProductDescription": "RES 10K OHM 1% 1/10W 0603",
                "Category": {
                    "CategoryName": "Resistors/Chip Resistor - Surface Mount"
                },
                "PrimaryDatasheet": "https://example/ds.pdf",
                "Parameters": [
                    {"Parameter": "Resistance", "Value": "10 kOhms"},
                    {"Parameter": "Power (Watts)", "Value": "0.1W"},
                    {"Parameter": "Tolerance", "Value": "±1%"},
                    {"Parameter": "Package / Case", "Value": "0603 (1608 Metric)"},
                    {"Parameter": "Voltage - Rated", "Value": "75 V"},
                ],
            }
        ]
    }


class DigiKeyResolverTests(unittest.TestCase):
    def _resolver(self, session, cache=None):
        return DigiKeyResolver(
            "id",
            "secret",
            session=session,
            cache=cache,
            min_interval=0,
        )

    def test_maps_parameters_and_sends_required_headers(self):
        session = FakeSession(_resistor_payload())
        provider = self._resolver(session).lookup("RC0603FR-0710KL")

        self.assertIsNotNone(provider)
        self.assertEqual(provider.type, PartType.RESISTOR)
        self.assertEqual(provider.attrs["value"], "10k")
        self.assertEqual(provider.attrs["rating"], "100mW")
        self.assertEqual(provider.attrs["tolerance"], "1%")
        self.assertEqual(provider.attrs["package"], "0603")
        self.assertEqual(provider.attrs["voltage_max"], "75V")
        self.assertEqual(provider.manufacturer, "YAGEO")
        self.assertEqual(provider.supplier_pn, "311-10KHRCT-ND")
        self.assertEqual(provider.datasheet, "https://example/ds.pdf")

        search = next(
            kwargs for url, kwargs in session.posts if "partsearch" in url
        )
        self.assertEqual(search["headers"]["X-DIGIKEY-Client-Id"], "id")
        self.assertEqual(search["headers"]["X-DIGIKEY-Locale-Site"], "US")
        self.assertEqual(search["json"]["Keywords"], "RC0603FR-0710KL")

        token = next(kwargs for url, kwargs in session.posts if "oauth2" in url)
        self.assertIn("auth", token)
        self.assertEqual(token["data"], {"grant_type": "client_credentials"})

    def test_cache_avoids_second_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(Path(tmp) / "cache.db")
            session = FakeSession(_resistor_payload())
            resolver = self._resolver(session, cache=cache)

            resolver.lookup("RC0603FR-0710KL")
            first = sum(1 for url, _ in session.posts if "partsearch" in url)
            resolver.lookup("RC0603FR-0710KL")
            second = sum(1 for url, _ in session.posts if "partsearch" in url)

            self.assertEqual(first, 1)
            self.assertEqual(second, 1)
            cache.close()

    def test_no_exact_match_returns_none(self):
        session = FakeSession(
            {"Parts": [{"ManufacturerPartNumber": "SOMETHING-ELSE"}]}
        )
        resolver = self._resolver(session)
        self.assertIsNone(resolver.lookup("RC0603FR-0710KL"))
        self.assertEqual(resolver.last_candidates, ["SOMETHING-ELSE"])

    def test_capacitor_mapping(self):
        payload = {
            "Parts": [
                {
                    "ManufacturerPartNumber": "GRM1555C1H471JA01D",
                    "Category": {"CategoryName": "Capacitors/Ceramic Capacitors"},
                    "ProductDescription": "CAP CER 470PF 50V C0G 0402",
                    "Parameters": [
                        {"Parameter": "Capacitance", "Value": "470 pF"},
                        {"Parameter": "Voltage - Rated", "Value": "50 V"},
                        {"Parameter": "Tolerance", "Value": "±5%"},
                        {"Parameter": "Dielectric Material", "Value": "C0G"},
                        {"Parameter": "Package / Case", "Value": "0402"},
                    ],
                }
            ]
        }
        provider = self._resolver(FakeSession(payload)).lookup(
            "GRM1555C1H471JA01D"
        )
        self.assertEqual(provider.type, PartType.CAPACITOR)
        self.assertEqual(provider.attrs["value"], "470pF")
        self.assertEqual(provider.attrs["rating"], "50V")
        self.assertEqual(provider.attrs["tolerance"], "5%")
        self.assertEqual(provider.attrs["dielectric"], "C0G")
        self.assertEqual(provider.attrs["package"], "0402")

    def test_led_mapping(self):
        payload = {
            "Parts": [
                {
                    "ManufacturerPartNumber": "LTST-C190KGKT",
                    "Category": {"CategoryName": "Optoelectronics/LED Indication"},
                    "ProductDescription": "LED GREEN CLEAR 0603 SMD",
                    "Parameters": [
                        {
                            "Parameter": "Voltage - Forward (Vf) (Typ)",
                            "Value": "2.1 V",
                        },
                        {"Parameter": "Current - Test", "Value": "20 mA"},
                        {"Parameter": "Color", "Value": "Green"},
                        {"Parameter": "Package / Case", "Value": "0603"},
                    ],
                }
            ]
        }
        provider = self._resolver(FakeSession(payload)).lookup("LTST-C190KGKT")
        self.assertEqual(provider.type, PartType.LED)
        self.assertEqual(provider.attrs["rating"], "2.1V")
        self.assertEqual(provider.attrs["current"], "20mA")
        self.assertEqual(provider.attrs["color"], "Green")
        self.assertEqual(provider.attrs["package"], "0603")


if __name__ == "__main__":
    unittest.main()
