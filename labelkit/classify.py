"""Part-type classification.

DigiKey's category is authoritative when present.  For LCSC invoices the
description is a good first pass (it is trusted, then verified), and MPN
prefixes are the last resort -- especially for MPN-only input where there
is no description at all.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .model import PartType
from .values import is_dielectric, normalize_package

FARAD_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*f\b", re.IGNORECASE)
HENRY_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*h\b", re.IGNORECASE)
WATT_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*w\b", re.IGNORECASE)
VOLT_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*v\b", re.IGNORECASE)
AMP_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*a\b", re.IGNORECASE)
HZ_RE = re.compile(r"\d\s*(?:meg|[pnu]|m|[kKMG])?\s*hz\b", re.IGNORECASE)
OHM_RE = re.compile(r"(?:\d\s*(?:meg|[kKMG])|\d\s*r\b|\d\s*r\d|\d\s*ohms?\b)", re.IGNORECASE)
PCT_RE = re.compile(r"\d\s*%")
PPM_RE = re.compile(r"\d\s*ppm\b", re.IGNORECASE)
COLOR_RE = re.compile(r"\b(?:red|green|blue|white|amber|yellow|orange|rgb|ir|uv)\b", re.IGNORECASE)

IC_PACKAGE_RE = re.compile(
    r"\b(?:SOIC|SOP|TSSOP|MSOP|SSOP|QFN|DFN|QFP|LQFP|TQFP|BGA|LGA|WLCSP|DIP|PDIP)-?\d*",
    re.IGNORECASE,
)

_IC_PACKAGE_FAMILIES = (
    "SOIC|SOP|TSSOP|MSOP|SSOP|QFN|DFN|QFP|LQFP|TQFP|BGA|LGA|WLCSP|DIP|SIP"
)


def _is_ic_package_value(value: str) -> bool:
    normalized = normalize_package(value)
    return bool(re.match(rf"^(?:{_IC_PACKAGE_FAMILIES})-?\d", normalized, re.I))

_PRIORITY = {
    PartType.CRYSTAL: 8,
    PartType.LED: 7,
    PartType.DIODE: 6,
    PartType.TRANSISTOR: 5,
    PartType.CAPACITOR: 4,
    PartType.INDUCTOR: 3,
    PartType.RESISTOR: 2,
    PartType.IC: 1,
    PartType.UNKNOWN: 0,
}

_MPN_PREFIXES: list[tuple[re.Pattern[str], PartType]] = [
    (re.compile(r"^(?:ABM|ABLS|ABL|ECS|FOX|NX|XRC|CST|DSX|SG\d|ASV|FA-|YSV)"), PartType.CRYSTAL),
    (re.compile(r"^(?:LTST|WP\d|APA|WS\d|SK6|HLMP|SSL|XPE|XPG|LTRB|LTW)"), PartType.LED),
    (re.compile(r"^(?:1N|BAT|BAS|BAV|MBR|SBR|SS\d|ES\d|US\d|SMA[JT]|SMB[JT]|SMC[JT])"), PartType.DIODE),
    (
        re.compile(
            r"^(?:2N|BC\d|BD\d|BSS|BSC|AO\d|IRF|IRL|SI\d|FQP|FDS|MMBT|PBSS|DMG|NTR|"
            r"ZXT|ZXM|DTA|DTC|MMBTA|MMBT3|MMBT4)"
        ),
        PartType.TRANSISTOR,
    ),
    (re.compile(r"^(?:STM|LM\d|TL\d|NE\d|MAX|AD\d|MCP|ATM|PIC|ESP|RP\d|TPS|AMS|SN\d|CD4|74)"), PartType.IC),
    (re.compile(r"^(?:BLM|LQH|SRN|SRR|CDRH|IHL|MLZ|MPZ|DFE|DLW|LQM|LQW)"), PartType.INDUCTOR),
    (re.compile(r"^(?:CC|CL\d|GRM|CGA|UMK|RF18|ECJ|C1[0-9]|C0[G-Z])"), PartType.CAPACITOR),
    (re.compile(r"^(?:RC|AC|RT|AF|AT|PTFR|CR\d|RM\d|RS\d|WR\d|RK\d)"), PartType.RESISTOR),
]


def classify_mpn(mpn: str) -> PartType | None:
    if not mpn:
        return None
    s = mpn.strip().upper()
    for pattern, ptype in _MPN_PREFIXES:
        if pattern.match(s):
            return ptype
    return None


def classify_description(
    description: str,
    *,
    package: str = "",
    mpn: str = "",
) -> tuple[PartType, float, list[str]]:
    """Infer a type from free text, with MPN prefix as a weak fallback."""
    text = (description or "").replace("µ", "u").replace("μ", "u")
    d = " " + text.lower() + " "

    scores: dict[PartType, float] = defaultdict(float)
    reasons: dict[PartType, list[str]] = defaultdict(list)

    def add(ptype: PartType, score: float, reason: str) -> None:
        scores[ptype] += score
        reasons[ptype].append(reason)

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, d))

    has_farad = bool(FARAD_RE.search(text))
    has_henry = bool(HENRY_RE.search(text))
    has_watt = bool(WATT_RE.search(text))
    has_volt = bool(VOLT_RE.search(text))
    has_amp = bool(AMP_RE.search(text))
    has_hz = bool(HZ_RE.search(text))
    has_ohm = bool(OHM_RE.search(text))
    has_ppm = bool(PPM_RE.search(text))
    has_dielectric = any(is_dielectric(tok) for tok in re.split(r"[\s,;]+", text) if tok)
    has_ic_package = bool(IC_PACKAGE_RE.search(text))

    if has(r"\b(?:crystal|oscillator|resonator|xtal)\b"):
        add(PartType.CRYSTAL, 100, "crystal keyword")
    if has_hz and has_ppm:
        add(PartType.CRYSTAL, 100, "frequency + ppm stability")
    if has_hz and has_farad and not has_dielectric:
        add(PartType.CRYSTAL, 65, "frequency + load capacitance")

    if has(r"\b(?:led|light[- ]emitting)\b"):
        add(PartType.LED, 100, "LED keyword")
    if COLOR_RE.search(text) and has_volt and has_amp:
        add(PartType.LED, 50, "colour + forward voltage + current")

    if has(r"\b(?:diode|rectifier|schottky|zener|tvs|avalanche|varactor)\b"):
        add(PartType.DIODE, 90, "diode keyword")

    if has(r"\b(?:transistor|mosfet|npn|pnp|n[- ]channel|p[- ]channel|bjt|igbt|jfet|nmos|pmos)\b"):
        add(PartType.TRANSISTOR, 90, "transistor keyword")

    if has_dielectric:
        add(PartType.CAPACITOR, 80, "dielectric code")
    if has_farad and not has_henry and not has_hz:
        add(PartType.CAPACITOR, 60, "capacitance value")

    if has(r"\b(?:ferrite|bead|inductor|choke|coil)\b"):
        add(PartType.INDUCTOR, 80, "inductor keyword")
    if has_henry:
        add(PartType.INDUCTOR, 60, "inductance value")

    if has(r"\bresistor\b"):
        add(PartType.RESISTOR, 80, "resistor keyword")
    if has_watt and (has_ohm or has_volt):
        add(PartType.RESISTOR, 60, "power rating + resistance/voltage")
    if has_ohm and not has_farad and not has_henry:
        add(PartType.RESISTOR, 30, "resistance value")

    if has(
        r"\b(?:integrated circuit|microcontroller|microprocessor|mcu|op[- ]?amp|"
        r"regulator|eeprom|flash|logic|driver|adc|dac|amplifier|transceiver|"
        r"multiplexer|gate|flip[- ]flop)\b"
    ):
        add(PartType.IC, 70, "IC keyword")
    if has_ic_package:
        add(PartType.IC, 50, "IC package")

    mpn_type = classify_mpn(mpn)
    if mpn_type is not None:
        add(mpn_type, 45, f"MPN prefix ({mpn_type.value})")

    # A package alone is weak; only trust it for unmistakable IC packages.
    # Normalise first so 14-TSSOP and TSSOP14 both count.
    if package and _is_ic_package_value(package):
        add(PartType.IC, 50, "IC package")

    if not scores:
        return PartType.UNKNOWN, 0.0, ["no recognisable part-type cue"]

    best = max(scores, key=lambda p: (scores[p], _PRIORITY.get(p, 0)))
    score = scores[best]
    if score < 45:
        return PartType.UNKNOWN, 0.0, ["part type is ambiguous"]
    confidence = 0.9 if score >= 80 else 0.75 if score >= 60 else 0.6
    return best, confidence, reasons[best]


_CATEGORY_RULES: list[tuple[re.Pattern[str], PartType]] = [
    (re.compile(r"\bled\b|light[- ]emitting", re.I), PartType.LED),
    (re.compile(r"\bcrystal|\boscillator|\bresonator", re.I), PartType.CRYSTAL),
    (re.compile(r"\bdiode|\brectifier", re.I), PartType.DIODE),
    (re.compile(r"\btransistor|\bmosfet|\bbipolar|\bigbt|\bjfet", re.I), PartType.TRANSISTOR),
    (re.compile(r"\bcapacitor", re.I), PartType.CAPACITOR),
    (re.compile(r"\binductor|\bferrite|\bchoke", re.I), PartType.INDUCTOR),
    (re.compile(r"\bresistor", re.I), PartType.RESISTOR),
    (
        re.compile(
            r"integrated circuit|\bmicrocontroller|\bmicroprocessor|\bamplifier|"
            r"\bregulator|\blogic\b|\bmemory\b|\binterface\b|\bdata acquisition|"
            r"\brf\b|\bic\b",
            re.I,
        ),
        PartType.IC,
    ),
]


def classify_category(
    category: str | None,
    *,
    description: str = "",
    parameter_names: tuple[str, ...] | list[str] = (),
    mpn: str = "",
) -> tuple[PartType, float, list[str]]:
    """DigiKey category first, then parameters, description, MPN."""
    cat = str(category or "").strip()
    for pattern, ptype in _CATEGORY_RULES:
        if pattern.search(cat):
            return ptype, 0.98, [f"DigiKey category: {cat}"]

    names = {str(n).strip().lower() for n in parameter_names}
    if "resistance" in names:
        return PartType.RESISTOR, 0.9, ["DigiKey parameter: Resistance"]
    if "capacitance" in names:
        return PartType.CAPACITOR, 0.9, ["DigiKey parameter: Capacitance"]
    if "inductance" in names:
        return PartType.INDUCTOR, 0.9, ["DigiKey parameter: Inductance"]
    if "frequency - self resonant" in names or "frequency" in names:
        if "load capacitance" in names or "frequency tolerance" in names:
            return PartType.CRYSTAL, 0.8, ["DigiKey parameters: frequency + load capacitance"]

    # The description is a stronger signal than a lone forward-voltage
    # parameter (diodes have Vf too, not just LEDs).
    if description:
        ptype, conf, reasons = classify_description(description, mpn=mpn)
        if ptype is not PartType.UNKNOWN:
            return ptype, min(conf, 0.85), reasons

    if "voltage - forward (vf) (typ)" in names and (
        "color" in names or "led" in description.lower()
    ):
        return PartType.LED, 0.7, ["DigiKey parameter: forward voltage"]

    mpn_type = classify_mpn(mpn)
    if mpn_type is not None:
        return mpn_type, 0.6, [f"MPN prefix ({mpn_type.value})"]

    return PartType.UNKNOWN, 0.0, ["DigiKey result has no usable category"]


def is_ic_package(package: str) -> bool:
    return bool(IC_PACKAGE_RE.search(package or ""))


__all__ = [
    "classify_mpn",
    "classify_description",
    "classify_category",
    "is_ic_package",
]
