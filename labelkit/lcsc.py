"""Best-effort LCSC product lookup.

LCSC has no public product API without partner credentials.  This client
tries the site's search JSON endpoint first and falls back to the product
page's embedded JSON.  It is deliberately tolerant: anything it cannot
parse returns ``None`` and the pipeline falls back to DigiKey.

The HTTP session is injectable so the mapping can be tested offline.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests

from .classify import classify_category
from .digikey import map_parameters
from .model import ProviderResult

SEARCH_URL = "https://wmsc.lcsc.com/wmsc/search/global"
PRODUCT_URL = "https://www.lcsc.com/product-detail/{pn}.html"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.lcsc.com/",
    "Origin": "https://www.lcsc.com",
}


class LcscError(RuntimeError):
    pass


def _parse_json_or_jsonp(text: str) -> dict[str, Any]:
    body = text.strip()
    if not body:
        raise LcscError("LCSC returned an empty response")
    if body.startswith("{"):
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise LcscError("LCSC returned invalid JSON") from exc
        return data if isinstance(data, dict) else {}
    match = re.match(r"^[^(]*\((.*)\)\s*;?\s*$", body, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
        except ValueError as exc:
            raise LcscError("LCSC returned invalid JSONP") from exc
        return data if isinstance(data, dict) else {}
    raise LcscError("LCSC response was not JSON (possibly an anti-bot page)")


def _normalise_params(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("paramNameEn")
            or item.get("paramName")
            or item.get("name")
            or item.get("Parameter")
            or ""
        )
        value = (
            item.get("paramValueEn")
            or item.get("paramValue")
            or item.get("value")
            or item.get("Value")
            or ""
        )
        if name and value:
            out.append({"Parameter": str(name), "Value": str(value)})
    return out


def _category_of(product: dict[str, Any]) -> str:
    direct = product.get("categoryName") or product.get("category")
    if direct:
        return str(direct)
    parent = str(product.get("parentCatalogName") or "").strip()
    leaf = str(product.get("catalogName") or "").strip()
    if parent and leaf and parent.lower() not in leaf.lower():
        return f"{parent} {leaf}"
    return parent or leaf


class LcscResolver:
    provider = "LCSC"

    def __init__(
        self,
        *,
        cache=None,
        session=None,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        cache_ttl: float = 7 * 86400,
        retries: int = 3,
    ):
        self.cache = cache
        self.session = session or requests.Session()
        self.timeout = timeout
        self.min_interval = max(0.0, float(min_interval))
        self.cache_ttl = cache_ttl
        self.retries = max(1, int(retries))
        self._last_request = 0.0
        self.last_candidates: list[str] = []

    @property
    def available(self) -> bool:
        return True

    @property
    def reason_unavailable(self) -> str:
        return ""

    # -- public API --------------------------------------------------------

    def lookup_by_pn(self, pn: str) -> ProviderResult | None:
        pn = str(pn or "").strip()
        if not pn:
            return None
        key = f"lcsc:pn:v1:{pn.upper()}"
        if self.cache is not None:
            cached = self.cache.get(key, ttl=self.cache_ttl)
            if cached:
                return self._to_provider(cached)

        product = None
        try:
            product = self._find_product(self._search(pn), pn)
        except LcscError:
            product = None
        if product is None:
            try:
                product = self._fetch_page(pn)
            except LcscError:
                product = None
        if product is None:
            return None

        if self.cache is not None:
            self.cache.set(key, product)
        return self._to_provider(product)

    def lookup_by_mpn(self, mpn: str) -> ProviderResult | None:
        mpn = str(mpn or "").strip()
        if not mpn:
            return None
        key = f"lcsc:mpn:v1:{mpn.upper()}"
        if self.cache is not None:
            cached = self.cache.get(key, ttl=self.cache_ttl)
            if cached:
                return self._to_provider(cached)

        payload = self._search(mpn)
        product = self._find_product(payload, mpn, exact_model=True)
        self.last_candidates = self._candidate_models(payload)[:5]
        if product is None:
            return None

        if self.cache is not None:
            self.cache.set(key, product)
        return self._to_provider(product)

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    # -- HTTP --------------------------------------------------------------

    def _throttle(self) -> None:
        if self.min_interval <= 0 or self._last_request <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        for attempt in range(self.retries):
            self._throttle()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers or _HEADERS,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise LcscError(f"LCSC request failed: {exc}") from exc
            self._last_request = time.monotonic()

            if response.status_code == 429:
                retry_after = (response.headers or {}).get("Retry-After")
                time.sleep(float(retry_after) if retry_after else 2 ** attempt)
                continue
            if response.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise LcscError(
                    f"LCSC HTTP {response.status_code} for {url}"
                )
            return response
        raise LcscError("LCSC request failed after retries")

    def _search(self, keyword: str) -> dict[str, Any]:
        response = self._get(SEARCH_URL, params={"keyword": keyword})
        return _parse_json_or_jsonp(response.text)

    def _fetch_page(self, pn: str) -> dict[str, Any] | None:
        url = PRODUCT_URL.format(pn=quote(pn))
        response = self._get(
            url, headers={**_HEADERS, "Accept": "text/html,application/xhtml+xml"}
        )
        html = response.text

        patterns = (
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r"<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>",
        )
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if not match:
                continue
            try:
                payload = json.loads(match.group(1))
            except ValueError:
                continue
            product = self._find_product(payload, pn)
            if product is None:
                product = self._richest_product(payload)
            if product is not None:
                return product
        return None

    # -- payload walking ---------------------------------------------------

    def _walk_products(self, node: Any, depth: int = 0) -> list[dict[str, Any]]:
        if depth > 14:
            return []
        found: list[dict[str, Any]] = []
        if isinstance(node, dict):
            if "productCode" in node or "productModel" in node:
                found.append(node)
            for value in node.values():
                found.extend(self._walk_products(value, depth + 1))
        elif isinstance(node, list):
            for value in node:
                found.extend(self._walk_products(value, depth + 1))
        return found

    def _richest_product(self, payload: Any) -> dict[str, Any] | None:
        products = self._walk_products(payload)
        if not products:
            return None
        return max(products, key=len)

    def _candidate_models(self, payload: Any) -> list[str]:
        return [
            str(product.get("productModel") or "")
            for product in self._walk_products(payload)
            if product.get("productModel")
        ]

    def _find_product(
        self, payload: Any, code: str, exact_model: bool = False
    ) -> dict[str, Any] | None:
        products = self._walk_products(payload)
        if not products:
            return None

        target = code.strip().upper()
        if exact_model:
            matches = [
                p
                for p in products
                if str(p.get("productModel") or "").strip().upper() == target
            ]
        else:
            matches = [
                p
                for p in products
                if str(p.get("productCode") or "").strip().upper() == target
            ]
        if not matches:
            return None
        return max(matches, key=len)

    # -- mapping -----------------------------------------------------------

    def _to_provider(self, product: dict[str, Any]) -> ProviderResult:
        supplier_pn = str(
            product.get("productCode")
            or product.get("lcscPartNumber")
            or product.get("lcscPartNo")
            or ""
        ).strip()
        mpn = str(
            product.get("productModel") or product.get("mpn") or ""
        ).strip()
        manufacturer = str(
            product.get("brandNameEn")
            or product.get("brandName")
            or product.get("manufacturer")
            or ""
        ).strip()
        description = str(
            product.get("productIntroEn")
            or product.get("productIntro")
            or product.get("description")
            or ""
        ).strip()
        category = _category_of(product)
        datasheet = str(
            product.get("pdfUrl")
            or product.get("datasheetUrl")
            or product.get("datasheet")
            or ""
        ).strip()

        raw_params = (
            product.get("paramVOList")
            or product.get("paramList")
            or product.get("attributes")
            or product.get("parameters")
            or []
        )
        params = _normalise_params(raw_params)
        names = tuple(param["Parameter"] for param in params)
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
            supplier_pn=supplier_pn,
            type=ptype,
            attrs=attrs,
            values=values,
            raw=product,
        )
