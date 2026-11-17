"""Parse an LCSC description into canonical attributes.

The description is trusted *as a claim* for an LCSC invoice, but every
field it produces is marked ``field_sources[field] == "description"`` and
must later be confirmed by the web provider.  A mismatch blocks the row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import PartType
from .values import (
    Quantity,
    dielectric_key,
    is_dielectric,
    looks_like_package,
    normalize_package,
    parse_quantity,
)

_COLOR_WORDS = {
    "red": "Red",
    "green": "Green",
    "blue": "Blue",
    "white": "White",
    "amber": "Amber",
    "yellow": "Yellow",
    "orange": "Orange",
    "rgb": "RGB",
    "ir": "IR",
    "uv": "UV",
}

_POLARITY = {
    "NPN": "NPN",
    "PNP": "PNP",
    "N-CHANNEL": "N-Channel",
    "P-CHANNEL": "P-Channel",
    "N-CH": "N-Channel",
    "P-CH": "P-Channel",
    "NMOS": "N-Channel",
    "PMOS": "P-Channel",
    "N-MOS": "N-Channel",
    "P-MOS": "P-Channel",
}

_DIODE_KINDS = {
    "SCHOTTKY": "Schottky",
    "ZENER": "Zener",
    "TVS": "TVS",
    "RECTIFIER": "Rectifier",
    "AVALANCHE": "Avalanche",
    "VARACTOR": "Varactor",
}


@dataclass
class ParsedDescription:
    attrs: dict[str, str] = field(default_factory=dict)
    values: dict[str, Quantity] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    if not text:
        return []
    raw = re.split(r"[\s,;]+", text.strip())
    out = []
    for tok in raw:
        tok = tok.strip("()[]{}<>\"'")
        if tok:
            out.append(tok)
    return out


def _word_set(tokens: list[str]) -> set[str]:
    return {t.upper() for t in tokens}


def parse_description(
    description: str,
    *,
    part_type: PartType,
    package_hint: str = "",
    mpn: str = "",
) -> ParsedDescription:
    tokens = _tokens(description)
    result = ParsedDescription()

    package = normalize_package(package_hint, part_type=part_type)
    dielectric = ""
    tolerance: Quantity | None = None
    voltage: Quantity | None = None
    power: Quantity | None = None
    current: Quantity | None = None
    frequency: Quantity | None = None
    capacitance: Quantity | None = None
    inductance: Quantity | None = None
    resistance: Quantity | None = None
    stability = ""
    words: list[str] = []

    for tok in tokens:
        upper = tok.upper()

        if is_dielectric(upper):
            dielectric = dielectric_key(upper)
            continue

        if looks_like_package(tok):
            package = normalize_package(tok, part_type=part_type)
            continue

        m = re.fullmatch(r"(\d+(?:\.\d+)?)PPM(?:/.*)?", upper)
        if m:
            stability = f"{m.group(1)}ppm"
            continue

        quantity = parse_quantity(tok, default_unit="ohm")
        if quantity is not None:
            if quantity.unit == "%":
                tolerance = quantity
            elif quantity.unit == "ppm":
                stability = quantity.text()
            elif quantity.unit == "V":
                voltage = quantity
            elif quantity.unit == "W":
                power = quantity
            elif quantity.unit == "A":
                current = quantity
            elif quantity.unit == "Hz":
                frequency = quantity
            elif quantity.unit == "F":
                capacitance = quantity
            elif quantity.unit == "H":
                inductance = quantity
            elif quantity.unit == "ohm":
                resistance = quantity
            continue

        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            if resistance is None:
                resistance = Quantity(float(tok), "ohm")
            continue

        words.append(tok)

    word_set = _word_set(words)

    # ---- type-specific value / rating -------------------------------
    if part_type is PartType.RESISTOR:
        if resistance is not None:
            result.values["value"] = resistance
            result.attrs["value"] = resistance.text()
        if power is not None:
            result.values["rating"] = power
            result.attrs["rating"] = power.text()
        if voltage is not None:
            result.attrs["voltage_max"] = voltage.text()

    elif part_type is PartType.CAPACITOR:
        if capacitance is not None:
            result.values["value"] = capacitance
            result.attrs["value"] = capacitance.text()
        if voltage is not None:
            result.values["rating"] = voltage
            result.attrs["rating"] = voltage.text()

    elif part_type is PartType.INDUCTOR:
        # Ferrite beads have no inductance parameter; their headline value
        # is the impedance at 100 MHz, so use that rather than dropping it.
        if inductance is not None:
            result.values["value"] = inductance
            result.attrs["value"] = inductance.text()
        elif resistance is not None:
            result.values["value"] = resistance
            result.attrs["value"] = resistance.text()
        if current is not None:
            result.values["rating"] = current
            result.attrs["rating"] = current.text()
        if voltage is not None:
            result.attrs["voltage_max"] = voltage.text()
        if "FERRITE" in word_set or "BEAD" in word_set:
            result.attrs["kind"] = "Ferrite Bead"

    elif part_type is PartType.CRYSTAL:
        if frequency is not None:
            result.values["value"] = frequency
            result.attrs["value"] = frequency.text()
        if capacitance is not None:
            result.values["load"] = capacitance
            result.attrs["load"] = capacitance.text()
        if stability:
            result.attrs["stability"] = stability

    elif part_type in (PartType.DIODE, PartType.LED, PartType.TRANSISTOR):
        if voltage is not None:
            result.values["rating"] = voltage
            result.attrs["rating"] = voltage.text()
        if current is not None:
            result.values["current"] = current
            result.attrs["current"] = current.text()

    # ---- shared fields ----------------------------------------------
    if tolerance is not None:
        result.values["tolerance"] = tolerance
        result.attrs["tolerance"] = tolerance.text()
    if dielectric:
        result.attrs["dielectric"] = dielectric
    if package:
        result.attrs["package"] = package

    # ---- type-specific extras ---------------------------------------
    if part_type is PartType.LED:
        color = ""
        if "WARM" in word_set and "WHITE" in word_set:
            color = "Warm White"
        elif "COOL" in word_set and "WHITE" in word_set:
            color = "Cool White"
        else:
            for word in words:
                if word.lower() in _COLOR_WORDS:
                    color = _COLOR_WORDS[word.lower()]
                    break
        if color:
            result.attrs["color"] = color

    elif part_type is PartType.TRANSISTOR:
        for word in word_set:
            if word in _POLARITY:
                result.attrs["polarity"] = _POLARITY[word]
                break

    elif part_type is PartType.DIODE:
        for word in word_set:
            if word in _DIODE_KINDS:
                result.attrs["kind"] = _DIODE_KINDS[word]
                break

    if part_type is not PartType.UNKNOWN:
        result.values = {k: v for k, v in result.values.items() if v is not None}
    else:
        result.issues.append("unknown part type; description not interpreted")

    return result
