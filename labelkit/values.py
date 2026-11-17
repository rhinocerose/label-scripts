"""Engineering quantity parsing and formatting.

The two sources we have to cope with are terse LCSC descriptions::

    50V 10nF X7R 10% 0603
    100mW 1k 75V 1% 0603

and DigiKey parameter strings::

    10 kOhms
    ±1%
    0603 (1608 Metric)
    100 nF

Both are normalised to a :class:`Quantity` carrying a base-SI value plus a
canonical unit, and rendered the way the existing label CSVs do it
(``4.7k``, ``100nF``, ``590R``, ``1.69M``, ``100mW``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# --------------------------------------------------------------------------
# Quantity
# --------------------------------------------------------------------------

_SI_EXP = {
    "p": -12,
    "n": -9,
    "u": -6,
    "m": -3,
    "k": 3,
    "K": 3,
    "M": 6,
    "G": 9,
    "meg": 6,
}

_UNIT_CANON = {
    "f": "F",
    "farad": "F",
    "farads": "F",
    "h": "H",
    "henry": "H",
    "henries": "H",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "ampere": "A",
    "amperes": "A",
    "hz": "Hz",
    "%": "%",
    "ppm": "ppm",
    "ohm": "ohm",
    "ohms": "ohm",
    "r": "ohm",
}

_PREFIX_TABLE = (
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "u"),
    (1e-9, "n"),
    (1e-12, "p"),
)

# --------------------------------------------------------------------------
# Editable output formats
# --------------------------------------------------------------------------

_FORMATS_PATH = Path(__file__).with_name("formats.yaml")

_DEFAULT_CHIP_IMPERIAL = {
    "01005",
    "0201",
    "0402",
    "0603",
    "0805",
    "1206",
    "1210",
    "1218",
    "2010",
    "2512",
    "0612",
    "0816",
    "1020",
    "1812",
    "2220",
    "2225",
    "3640",
}
_DEFAULT_METRIC_TO_IMPERIAL = {
    "0402": "01005",
    "0603": "0201",
    "1005": "0402",
    "1608": "0603",
    "2012": "0805",
    "3216": "1206",
    "3225": "1210",
    "3246": "1218",
    "5025": "2010",
    "6332": "2512",
    "1632": "0612",
    "2032": "0816",
    "2550": "1020",
    "4532": "1812",
    "5650": "2220",
    "5763": "2225",
    "9110": "3640",
}
_DEFAULT_CRYSTAL_SIZES = {"1612", "2016", "2520", "3225", "5032", "7050", "8038"}


def _load_formats() -> dict:
    if not _FORMATS_PATH.is_file():
        return {}
    try:
        data = yaml.safe_load(_FORMATS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


_FORMATS = _load_formats()
_CHIP_IMPERIAL = {
    str(x).strip()
    for x in (_FORMATS.get("chip_imperial") or _DEFAULT_CHIP_IMPERIAL)
}
_METRIC_TO_IMPERIAL = {
    str(k).strip(): str(v).strip()
    for k, v in (
        _FORMATS.get("metric_to_imperial") or _DEFAULT_METRIC_TO_IMPERIAL
    ).items()
}
_CRYSTAL_SIZES = {
    str(x).strip()
    for x in (_FORMATS.get("crystal_sizes") or _DEFAULT_CRYSTAL_SIZES)
}
_CRYSTAL_ALIASES = {
    str(k).strip().lower(): str(v).strip()
    for k, v in (_FORMATS.get("crystal_aliases") or {}).items()
}
_IC_ALIASES = {
    str(k).strip().upper(): str(v).strip()
    for k, v in (_FORMATS.get("ic_aliases") or {}).items()
}
_IC_FAMILY_ALIASES = {
    str(k).strip().upper(): str(v).strip().upper()
    for k, v in (_FORMATS.get("ic_family_aliases") or {}).items()
}
_IC_ALIASES_NO_DASH = {
    key.replace("-", ""): value for key, value in _IC_ALIASES.items()
}
_RESISTANCE_STYLE = str(_FORMATS.get("resistance") or "rkm").strip().lower()
_DIELECTRIC_STYLE = str(_FORMATS.get("dielectric") or "C0G").strip().upper()


@dataclass(frozen=True)
class Quantity:
    """A physical value in base SI units (ohm, F, H, V, W, A, Hz, %)."""

    value: float
    unit: str

    def text(self) -> str:
        return format_quantity(self.value, self.unit)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.text()


def _num(x: float) -> str:
    if abs(x) < 1e-12:
        return "0"
    return f"{round(x, 6):g}"


def _rkm_string(value: float, scale: float, prefix: str) -> str:
    n = value / scale
    magnitude = abs(n)
    if magnitude >= 100:
        n = round(n)
    elif magnitude >= 10:
        n = round(n, 1)
    else:
        n = round(n, 2)
    text = f"{n:g}"
    if "." in text:
        whole, fraction = text.split(".")
        return f"{whole}{prefix}{fraction}"
    return f"{text}{prefix}"


def format_rkm(value: float) -> str:
    """RKM resistance notation: 4k7, 1M69, 590R, 4R7, 1mR."""
    if value == 0:
        return "0R"
    magnitude = abs(value)
    if magnitude >= 1e9:
        return _rkm_string(value, 1e9, "G")
    if magnitude >= 1e6:
        return _rkm_string(value, 1e6, "M")
    if magnitude >= 1e3:
        return _rkm_string(value, 1e3, "k")
    if magnitude >= 1:
        return _rkm_string(value, 1.0, "R")
    for scale, prefix in ((1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if magnitude >= scale:
            return _rkm_string(value, scale, prefix + "R")
    return _rkm_string(value, 1e-12, "pR")


def _format_decimal_ohm(value: float) -> str:
    magnitude = abs(value)
    for scale, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if magnitude >= scale:
            return f"{_num(value / scale)}{prefix}"
    if magnitude >= 1.0:
        return f"{_num(value)}R"
    for scale, prefix in ((1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if magnitude >= scale:
            return f"{_num(value / scale)}{prefix}R"
    return f"{_num(value)}R"


def format_quantity(value: float, unit: str) -> str:
    """Render a value using the selected canonical style."""
    unit = _UNIT_CANON.get(str(unit).lower(), unit)
    if unit == "%":
        return f"{_num(value)}%"
    if unit == "ppm":
        return f"{_num(value)}ppm"
    if unit == "ohm":
        if _RESISTANCE_STYLE == "decimal":
            return _format_decimal_ohm(value)
        return format_rkm(value)
    if value == 0:
        return f"0{unit}"

    magnitude = abs(value)
    for scale, prefix in _PREFIX_TABLE:
        if magnitude >= scale:
            return f"{_num(value / scale)}{prefix}{unit}"
    return f"{_num(value / 1e-12)}p{unit}"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"
_PREFIX = r"(?:meg|[pnu]|m|[kKMG])"

_QTY_RE = re.compile(
    rf"^(?P<num>{_NUM})(?P<prefix>{_PREFIX})?"
    r"(?i:(?P<unit>ohms?|r|farads?|f|henries|henry|h|volts?|v|watts?|w|"
    r"amps?|amperes?|a|hz|%|ppm))$"
)
_BARE_RE = re.compile(rf"^(?P<num>{_NUM})(?P<prefix>{_PREFIX})?$")
_RKM_RE = re.compile(
    rf"^(?P<a>{_NUM})(?P<mult>[RKM])(?P<b>\d+)$", re.IGNORECASE
)
_FRACTION_WATT_RE = re.compile(r"^(?P<num>\d+)/(?P<den>\d+)W$", re.IGNORECASE)
_PPM_RE = re.compile(rf"^(?P<num>{_NUM})ppm$", re.IGNORECASE)


def _clean(text: str) -> str:
    s = str(text).strip()
    for ch in ("±", "≈", "~", "<", ">", "="):
        s = s.replace(ch, "")
    s = s.replace("µ", "u").replace("μ", "u")
    s = s.replace("Ω", "ohm").replace("ω", "ohm")
    s = re.sub(r"\s+", "", s)
    return s.strip(" ,;")


def parse_quantity(text: object, *, default_unit: Optional[str] = None) -> Optional[Quantity]:
    """Parse ``10nF``, ``4.7k``, ``100 mW``, ``±1%``, ``10 kOhms`` ...

    ``default_unit`` supplies the unit for bare numbers (``590`` -> 590 ohm
    when ``default_unit="ohm"``).  Returns ``None`` if the token is not a
    quantity.
    """
    if text is None:
        return None
    s = _clean(text)
    if not s:
        return None

    m = _FRACTION_WATT_RE.fullmatch(s)
    if m and m["den"]:
        return Quantity(float(m["num"]) / float(m["den"]), "W")

    m = _PPM_RE.fullmatch(s)
    if m:
        return Quantity(float(m["num"]), "ppm")

    # 4R7 / 1K3 / 2M2 notation (only meaningful for resistance)
    m = _RKM_RE.fullmatch(s)
    if m and default_unit in (None, "ohm"):
        scale = {"R": 1.0, "K": 1e3, "M": 1e6}[m["mult"].upper()]
        frac = float("0." + m["b"]) if m["b"] else 0.0
        return Quantity((float(m["a"]) + frac) * scale, "ohm")

    m = _QTY_RE.fullmatch(s)
    if m:
        unit = _UNIT_CANON[m["unit"].lower()]
        prefix = m["prefix"]
        scale = 10.0 ** _SI_EXP[prefix] if prefix else 1.0
        return Quantity(float(m["num"]) * scale, unit)

    m = _BARE_RE.fullmatch(s)
    if m and default_unit:
        prefix = m["prefix"]
        scale = 10.0 ** _SI_EXP[prefix] if prefix else 1.0
        return Quantity(float(m["num"]) * scale, default_unit)

    return None


# --------------------------------------------------------------------------
# Resistor MPN decoding
# --------------------------------------------------------------------------

# Only series whose value code we actually understand.  Everything else is
# deliberately left to the web verifier.
_RESISTOR_SERIES = re.compile(r"^(?:RC|AC|RT|AF|AT|PTFR|CR|RM|RS|WR|RK)\d", re.I)
_VALUE_CODE = re.compile(r"^(?P<a>\d{1,4})(?P<mult>[RKM])?(?P<b>\d{0,2})L?$", re.I)


def parse_resistance_mpn(mpn: str) -> Optional[Quantity]:
    """Decode ``RC0603FR-0710KL`` -> 10k, ``...-072K2L`` -> 2.2k.

    The code after the hyphen is a two digit packaging prefix followed by
    the value code.  We only trust this for known resistor families; it is
    used as a cross-check, never as the sole source for a printed label.
    """
    if not mpn:
        return None
    s = mpn.strip().upper()
    if not _RESISTOR_SERIES.match(s):
        return None
    if "-" not in s:
        return None
    tail = s.rsplit("-", 1)[1]
    if len(tail) < 4:
        return None
    code = tail[2:]
    m = _VALUE_CODE.fullmatch(code)
    if not m:
        return None

    a = float(m["a"])
    mult = m["mult"]
    b = m["b"] or ""
    if mult:
        scale = {"R": 1.0, "K": 1e3, "M": 1e6}[mult]
        value = (a + (float("0." + b) if b else 0.0)) * scale
    else:
        value = a
    if not (0 < value < 1e13):
        return None
    return Quantity(value, "ohm")


# --------------------------------------------------------------------------
# Packages and dielectrics
# --------------------------------------------------------------------------

# Imperial chip sizes plus metric equivalents and crystal metric sizes.
CHIP_PACKAGES = (
    set(_CHIP_IMPERIAL)
    | set(_METRIC_TO_IMPERIAL)
    | set(_CRYSTAL_SIZES)
    | {"3030"}
)

_IC_FAMILY_PATTERN = (
    r"SOT|SOD|SOIC|SOP|SO|TSSOP|MSOP|SSOP|QFN|DFN|QFP|LQFP|TQFP|"
    r"BGA|LGA|WLCSP|DIP|PDIP|TO|SMA|SMB|SMC|DPAK|D2PAK|SIP|MELF|DO"
)

_PKG_IC = re.compile(
    rf"^(?P<base>{_IC_FAMILY_PATTERN})"
    r"(?:-?(?P<num>\d+))?(?:-(?P<sub>\d+))?",
    re.IGNORECASE,
)

# Pin count before a package family: 5-SOT-23, 3-TO-220, 2-SOD-123.
_LEADING_BODY_RE = re.compile(
    r"^(?P<pins>\d{1,3})-?(?P<family>SOT|SOD|DO|TO)-?(?P<body>\d+)$",
    re.IGNORECASE,
)

# Pin count before a family without a body number:
# 14-TSSOP, 14TSSOP, 8-SOIC, 8SO, 100-LQFP, 256-BGA.
_LEADING_PIN_RE = re.compile(
    r"^(?P<pins>\d{1,3})-?"
    r"(?P<family>SOIC|SOP|SO|TSSOP|MSOP|SSOP|QFN|DFN|QFP|LQFP|TQFP|"
    r"BGA|LGA|WLCSP|DIP|PDIP|SIP)$",
    re.IGNORECASE,
)

_IC_CANONICAL = {str(value).upper() for value in _IC_ALIASES.values()}
_CHIP_TOKEN = re.compile(r"^(0?\d{3,4})$")
_BODY_FAMILIES = {"SOT", "SOD", "DO", "TO"}


def _canonical_ic(family: str, number: str | None, sub: str | None) -> str:
    family = _IC_FAMILY_ALIASES.get(family.upper(), family.upper())
    if family in _BODY_FAMILIES:
        if not number:
            return family
        base = f"{family}-{number}"
        # TO-252/TO-263 and SOT-23-3 collapse to their conventional names.
        if sub in (None, "3"):
            alias = _IC_ALIASES.get(base)
            if alias:
                return alias
        # SOT-23-3 is normally just SOT-23; larger pin counts stay explicit.
        if family == "SOT" and sub and sub != "3":
            return f"{base}-{sub}"
        return base

    out = family
    if number:
        out += f"-{number}"
    if sub:
        out += f"-{sub}"
    return out


def _is_crystal(part_type: object) -> bool:
    if part_type is None:
        return False
    value = getattr(part_type, "value", part_type)
    return str(value).strip().lower() == "crystal"


def normalize_package(value: object, part_type=None) -> str:
    """Canonicalise package variants.

    Passives use imperial chip codes (``0603``); crystals keep their metric
    size (``3225``); IC/discrete packages are ``FAMILY-PINS`` (``SOIC-8``).
    The tables live in ``formats.yaml``.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    compact = re.sub(r"[\s_]+", "", s).upper()
    crystal = _is_crystal(part_type)

    if compact in _IC_ALIASES:
        return _IC_ALIASES[compact]
    no_dash = compact.replace("-", "")
    if no_dash in _IC_ALIASES_NO_DASH:
        return _IC_ALIASES_NO_DASH[no_dash]

    # 0603 (1608 Metric)
    m = re.fullmatch(r"(\d{3,4})\((\d{3,4})METRIC\)", compact)
    if m:
        first, second = m.group(1).zfill(4), m.group(2)
        if crystal:
            return second
        if first in _CHIP_IMPERIAL:
            return first
        if second in _METRIC_TO_IMPERIAL:
            return _METRIC_TO_IMPERIAL[second]
        return first

    # 1608 Metric
    m = re.fullmatch(r"(\d{3,4})METRIC", compact)
    if m:
        code = m.group(1).zfill(4)
        if crystal and code in _CRYSTAL_SIZES:
            return code
        return _METRIC_TO_IMPERIAL.get(code, code)

    # Crystal body sizes: 3.2x2.5 -> 3225
    alias_key = re.sub(r"\s+", "", s.lower())
    if alias_key in _CRYSTAL_ALIASES:
        return _CRYSTAL_ALIASES[alias_key]

    # Bare numeric chip size
    m = re.fullmatch(r"0?(\d{3,4})", s)
    if m:
        code = m.group(1)
        if len(code) == 3:
            code = "0" + code
        if crystal and code in _CRYSTAL_SIZES:
            return code
        if code in _CRYSTAL_SIZES and not crystal:
            return _METRIC_TO_IMPERIAL.get(code, code)
        if code in _CHIP_IMPERIAL:
            return code
        if code in _METRIC_TO_IMPERIAL:
            return _METRIC_TO_IMPERIAL[code]
        return code

    # IC / discrete package, family-first: TSSOP14, SOIC-8, SOT-23-5.
    m = _PKG_IC.fullmatch(compact)
    if m:
        return _canonical_ic(m.group("base"), m.group("num"), m.group("sub"))

    # Pin count first, body family: 5-SOT-23, 3-TO-220, 2-SOD-123.
    m = _LEADING_BODY_RE.fullmatch(compact)
    if m:
        return _canonical_ic(m.group("family"), m.group("body"), m.group("pins"))

    # Pin count first, no body number: 14-TSSOP, 8-SOIC, 256-BGA.
    m = _LEADING_PIN_RE.fullmatch(compact)
    if m:
        return _canonical_ic(m.group("family"), m.group("pins"), None)

    return s


def looks_like_package(token: object) -> bool:
    if token is None:
        return False
    s = str(token).strip()
    if not s:
        return False
    normalized = normalize_package(s)
    if normalized in CHIP_PACKAGES:
        return True
    if normalized.upper() in _IC_CANONICAL:
        return True
    compact = re.sub(r"[\s_]+", "", s).upper()
    if _PKG_IC.fullmatch(compact):
        return True
    return bool(
        _LEADING_BODY_RE.fullmatch(compact)
        or _LEADING_PIN_RE.fullmatch(compact)
    )


DIELECTRIC_ALIASES = {
    "NP0": "C0G",
    "NPO": "C0G",
    "C0G": "C0G",
    "X7R": "X7R",
    "X5R": "X5R",
    "X7S": "X7S",
    "X6S": "X6S",
    "X6T": "X6T",
    "Y5V": "Y5V",
    "Z5U": "Z5U",
    "U2J": "U2J",
    "SL": "SL",
    "CH": "CH",
}


def dielectric_key(value: object) -> str:
    s = str(value or "").strip().upper()
    if _DIELECTRIC_STYLE == "PRESERVE":
        return s
    canonical = DIELECTRIC_ALIASES.get(s, s)
    if _DIELECTRIC_STYLE == "NP0" and canonical == "C0G":
        return "NP0"
    return canonical


def is_dielectric(token: object) -> bool:
    return dielectric_key(token) in set(DIELECTRIC_ALIASES.values())
