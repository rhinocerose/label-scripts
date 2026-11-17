"""DigiKey v4 product-search resolver.

Fixes the problems in the old ``digi-scrape.py``:

* sends the required ``X-DIGIKEY-Client-Id`` / ``X-DIGIKEY-Locale-*``
  headers (the old script omitted them);
* caches exact-match responses in SQLite, keyed by MPN;
* applies a rate limit and retries 429/5xx with backoff;
* never writes debug JSON into the working directory;
* maps DigiKey parameters into the canonical attribute set instead of
  just dumping a description.

The HTTP session is injectable so the mapping can be tested without
credentials.
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .classify import classify_category
from .description import parse_description
from .model import PartType, ProviderResult
from .values import dielectric_key, normalize_package, parse_quantity

API_URL = "https://api.digikey.com/services/partsearch/v4/partsearch"
TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"


class DigiKeyError(RuntimeError):
    pass


def _category_name(part: dict[str, Any]) -> str:
    category = part.get("Category")
    if isinstance(category, dict):
        return str(
            category.get("CategoryName")
            or category.get("Name")
            or category.get("Value")
            or ""
        )
    if isinstance(category, list):
        for item in category:
            if isinstance(item, dict):
                name = item.get("CategoryName") or item.get("Name")
                if name:
                    return str(name)
            elif item:
                return str(item)
    return str(category or "")


def _find(params: list[dict[str, Any]], *needles: str) -> str:
    """First non-empty value for the first matching parameter name."""
    for needle in needles:
        needle = needle.lower()
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("Parameter") or "").strip().lower()
            if needle and needle in name:
                value = str(param.get("Value") or "").strip()
                if value:
                    return value
    return ""


def _q(text: str, unit: str | None):
    if not text:
        return None
    return parse_quantity(text, default_unit=unit)


def _stability(text: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*ppm", text or "", re.IGNORECASE)
    return f"{match.group(1)}ppm" if match else ""


def _ic_type_word(category: str, description: str = "") -> str:
    text = f"{category} {description}".lower()
    rules = [
        (r"adc/dac|dac/adc", "adc/dac"),
        (r"\bdac\b|digital to analog", "dac"),
        (r"\badc\b|analog to digital", "adc"),
        (r"operational amplifier|op[- ]?amp", "op-amp"),
        (r"voltage regulator|linear regulator|\bldo\b", "regulator"),
        (r"microcontroller|\bmcu\b", "mcu"),
        (r"microprocessor|\bmpu\b", "mpu"),
        (r"eeprom", "eeprom"),
        (r"\bflash\b", "flash"),
        (r"multiplexer|\bmux\b", "mux"),
        (r"shift register", "shift register"),
        (r"\blogic\b", "logic"),
        (r"\bgate\b", "gate"),
        (r"\bcounter\b", "counter"),
    ]
    for pattern, word in rules:
        if re.search(pattern, text):
            return word
    leaf = re.split(r"[/>]", category or "")[-1].strip().lower()
    return leaf or "ic"


def _ic_params(params: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}

    channels = _find(
        params,
        "number of d/a converters",
        "number of a/d converters",
        "number of amplifiers",
        "number of elements",
        "number of channels",
    )
    if channels:
        out["channels"] = channels

    resolution = _find(params, "number of bits", "resolution")
    if resolution:
        out["resolution"] = resolution

    bandwidth = _q(_find(params, "gain bandwidth product", "bandwidth"), "Hz")
    if bandwidth is not None:
        out["bandwidth"] = bandwidth.text()

    supply = _find(params, "voltage - output", "voltage - supply")
    if supply:
        out["supply"] = supply

    topology = _find(params, "regulator type", "topology")
    if topology:
        out["topology"] = topology

    current = _q(_find(params, "current - output", "current - supply", "current"), "A")
    if current is not None:
        out["current"] = current.text()

    core = _find(params, "core processor", "core")
    if core:
        out["core"] = core

    speed = _q(_find(params, "speed"), "Hz")
    if speed is not None:
        out["speed"] = speed.text()

    flash = _find(params, "flash size")
    if flash:
        out["flash"] = flash

    return out


def map_parameters(
    params: list[dict[str, Any]],
    ptype: PartType,
    description: str,
    mpn: str,
    category: str = "",
) -> tuple[dict[str, str], dict[str, Any]]:
    attrs: dict[str, str] = {}
    values: dict[str, Any] = {}

    def put(key: str, quantity) -> None:
        if quantity is not None:
            values[key] = quantity
            attrs[key] = quantity.text()

    def put_text(key: str, text: str) -> None:
        if text:
            attrs[key] = text

    if ptype is PartType.RESISTOR:
        put("value", _q(_find(params, "resistance"), "ohm"))
        put(
            "rating",
            _q(_find(params, "power (watts)", "power - max", "power rating", "power"), "W"),
        )
        voltage = _q(
            _find(params, "voltage - rated", "voltage rated", "voltage rating", "voltage - max"),
            "V",
        )
        if voltage is not None:
            attrs["voltage_max"] = voltage.text()

    elif ptype is PartType.CAPACITOR:
        put("value", _q(_find(params, "capacitance"), "F"))
        put(
            "rating",
            _q(
                _find(
                    params,
                    "voltage - rated",
                    "voltage rated",
                    "voltage rating",
                    "voltage - max",
                    "voltage",
                ),
                "V",
            ),
        )

    elif ptype is PartType.INDUCTOR:
        value = _q(_find(params, "inductance"), "H")
        if value is None:
            value = _q(_find(params, "impedance"), "ohm")
        put("value", value)
        put(
            "rating",
            _q(
                _find(
                    params,
                    "current - rated",
                    "current rating",
                    "current - saturation",
                    "current",
                ),
                "A",
            ),
        )

    elif ptype is PartType.CRYSTAL:
        put("value", _q(_find(params, "frequency"), "Hz"))
        put("load", _q(_find(params, "capacitance - load", "load capacitance"), "F"))
        put_text(
            "stability",
            _stability(_find(params, "frequency stability", "stability")),
        )

    elif ptype is PartType.DIODE:
        put(
            "rating",
            _q(
                _find(
                    params,
                    "voltage - dc reverse (vr) (max)",
                    "voltage - dc reverse",
                    "voltage - rated",
                    "voltage - forward",
                ),
                "V",
            ),
        )
        put(
            "current",
            _q(
                _find(
                    params,
                    "current - average rectified (io)",
                    "current - average rectified",
                    "current - rated",
                    "current",
                ),
                "A",
            ),
        )
        put_text("kind", _find(params, "diode type"))

    elif ptype is PartType.LED:
        put(
            "rating",
            _q(
                _find(
                    params,
                    "voltage - forward (vf) (typ)",
                    "voltage - forward",
                    "voltage - rated",
                ),
                "V",
            ),
        )
        put(
            "current",
            _q(_find(params, "current - test", "current - max", "current - rated", "current"), "A"),
        )
        put_text("color", _find(params, "color", "lens color"))

    elif ptype is PartType.TRANSISTOR:
        put(
            "rating",
            _q(
                _find(
                    params,
                    "drain to source voltage (vdss)",
                    "voltage - collector emitter breakdown (vceo) (max)",
                    "voltage - rated",
                ),
                "V",
            ),
        )
        put(
            "current",
            _q(
                _find(
                    params,
                    "current - continuous drain (id)",
                    "current - collector (ic) (max)",
                    "current - rated",
                    "current",
                ),
                "A",
            ),
        )
        put_text("polarity", _find(params, "transistor type", "polarity"))

    put("tolerance", _q(_find(params, "tolerance"), "%"))
    put_text(
        "dielectric",
        dielectric_key(_find(params, "dielectric material", "dielectric")),
    )

    package = _find(params, "package / case", "supplier device package", "package")
    if package:
        attrs["package"] = normalize_package(package, part_type=ptype)

    if ptype is PartType.IC:
        attrs["type_word"] = _ic_type_word(category, description)
        attrs.update(_ic_params(params))
    elif ptype is PartType.INDUCTOR:
        text = f"{category} {description}".lower()
        if "ferrite" in text or "bead" in text:
            attrs["kind"] = "Ferrite Bead"
    elif ptype is PartType.DIODE:
        kind = _find(params, "diode type")
        if kind:
            attrs["kind"] = kind

    # Fill gaps from the provider's own description (still web data, not
    # the LCSC description).
    if description and ptype is not PartType.UNKNOWN:
        parsed = parse_description(
            description, part_type=ptype, package_hint=attrs.get("package", ""), mpn=mpn
        )
        for key, value in parsed.attrs.items():
            attrs.setdefault(key, value)
        for key, value in parsed.values.items():
            values.setdefault(key, value)

    return attrs, values


class DigiKeyResolver:
    provider = "DigiKey"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        *,
        site: str = "US",
        language: str = "en",
        currency: str = "USD",
        cache=None,
        session=None,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        cache_ttl: float = 7 * 86400,
        retries: int = 3,
    ):
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.site = site
        self.language = language
        self.currency = currency
        self.cache = cache
        self.session = session or requests.Session()
        self.timeout = timeout
        self.min_interval = max(0.0, float(min_interval))
        self.cache_ttl = cache_ttl
        self.retries = max(1, int(retries))

        self._token_value = ""
        self._token_expiry = 0.0
        self._last_request = 0.0
        self.last_candidates: list[str] = []

    # -- availability ------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def reason_unavailable(self) -> str:
        return "DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET are not set"

    # -- public API --------------------------------------------------------

    def lookup(self, mpn: str) -> ProviderResult | None:
        if not self.available:
            raise DigiKeyError(self.reason_unavailable)
        mpn = str(mpn or "").strip()
        if not mpn:
            return None

        cache_key = f"digikey:v1:{mpn.upper()}"
        if self.cache is not None:
            cached = self.cache.get(cache_key, ttl=self.cache_ttl)
            if cached:
                return self._to_provider(cached)

        payload = self._search(mpn)
        parts = payload.get("Parts") or payload.get("ExactMatches") or []
        if isinstance(parts, dict):
            parts = [parts]
        parts = [p for p in parts if isinstance(p, dict)]

        self.last_candidates = [
            str(p.get("ManufacturerPartNumber") or "") for p in parts[:8]
        ]
        exact = [
            p
            for p in parts
            if str(p.get("ManufacturerPartNumber") or "").strip().upper()
            == mpn.upper()
        ]
        if not exact:
            return None

        best = max(exact, key=lambda p: len(p.get("Parameters") or []))
        if self.cache is not None:
            self.cache.set(cache_key, best)
        return self._to_provider(best)

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    # -- HTTP --------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": self.site,
            "X-DIGIKEY-Locale-Language": self.language,
            "X-DIGIKEY-Locale-Currency": self.currency,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_token(self) -> str:
        if self._token_value and time.monotonic() < self._token_expiry - 30:
            return self._token_value
        try:
            response = self.session.post(
                TOKEN_URL,
                auth=HTTPBasicAuth(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DigiKeyError(f"DigiKey OAuth request failed: {exc}") from exc
        if response.status_code != 200:
            raise DigiKeyError(
                f"DigiKey OAuth failed: HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        token = str(data.get("access_token") or "")
        if not token:
            raise DigiKeyError("DigiKey OAuth response did not contain access_token")
        self._token_value = token
        self._token_expiry = time.monotonic() + float(data.get("expires_in") or 600)
        return token

    def _throttle(self) -> None:
        if self.min_interval <= 0 or self._last_request <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _search(self, mpn: str) -> dict[str, Any]:
        payload = {
            "Keywords": mpn,
            "SearchOptions": "ManufacturerPart",
            "RecordCount": 10,
            "RecordStartPosition": 0,
            "Sort": {
                "Option": "SortByDigiKeyPartNumber",
                "Direction": "Ascending",
                "SortParameterId": 0,
            },
            "RequestedQuantity": 0,
            "ExcludeMarketPlaceProducts": True,
        }

        for attempt in range(self.retries):
            token = self._get_token()
            headers = self._headers(token)
            self._throttle()
            try:
                response = self.session.post(
                    API_URL, json=payload, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise DigiKeyError(f"DigiKey search request failed: {exc}") from exc
            self._last_request = time.monotonic()

            if response.status_code == 401 and attempt == 0:
                self._token_value = ""
                self._token_expiry = 0.0
                continue
            if response.status_code == 429:
                retry_after = (response.headers or {}).get("Retry-After")
                time.sleep(float(retry_after) if retry_after else 2 ** attempt)
                continue
            if response.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise DigiKeyError(
                    f"DigiKey search failed: HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise DigiKeyError("DigiKey returned invalid JSON") from exc
            return data if isinstance(data, dict) else {}

        raise DigiKeyError("DigiKey search failed after retries")

    # -- mapping -----------------------------------------------------------

    def _to_provider(self, part: dict[str, Any]) -> ProviderResult:
        mpn = str(part.get("ManufacturerPartNumber") or "").strip()
        manufacturer_raw = part.get("Manufacturer")
        if isinstance(manufacturer_raw, dict):
            manufacturer = str(manufacturer_raw.get("Value") or "")
        else:
            manufacturer = str(manufacturer_raw or "")

        description = str(
            part.get("ProductDescription") or part.get("DetailedDescription") or ""
        ).strip()
        datasheet = str(
            part.get("PrimaryDatasheet") or part.get("DatasheetUrl") or ""
        ).strip()
        digikey_pn = str(part.get("DigiKeyPartNumber") or "").strip()
        category = _category_name(part)
        params = part.get("Parameters") or []
        if not isinstance(params, list):
            params = []

        names = tuple(
            str(p.get("Parameter") or "") for p in params if isinstance(p, dict)
        )
        ptype, _confidence, _reasons = classify_category(
            category, description=description, parameter_names=names, mpn=mpn
        )
        attrs, values = map_parameters(
            params, ptype, description, mpn, category
        )

        return ProviderResult(
            provider=self.provider,
            mpn=mpn,
            manufacturer=manufacturer,
            description=description,
            category=category,
            datasheet=datasheet,
            supplier_pn=digikey_pn,
            type=ptype,
            attrs=attrs,
            values=values,
            raw=part,
        )
