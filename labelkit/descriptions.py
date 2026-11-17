"""Canonical one-line descriptions.

Resistors and capacitors deliberately have no description: their
Resistance/Capacitance/Voltage/Tolerance/... columns already say
everything.  Every other type gets a normalized, generated line built from
the verified attributes, not from the supplier's raw text.

Examples::

    diode      schottky 40V 1A SOD-123 diode
    led        green 2.1V 20mA 0603 led
    crystal    16MHz 20pF 30ppm 3225 crystal
    dac        4-ch 12-bit dac
"""

from __future__ import annotations

import re

from .model import Part, PartType


def _digits(value: object) -> str:
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else ""


def _join(*parts: object) -> str:
    return " ".join(str(p).strip() for p in parts if str(p or "").strip())


def _lower(value: object) -> str:
    return str(value or "").strip().lower()


def _count(value: object) -> str:
    digits = _digits(value)
    return f"{digits}-ch" if digits else ""


def _bits(value: object) -> str:
    digits = _digits(value)
    return f"{digits}-bit" if digits else ""


def describe(part: Part) -> str:
    if part.type in (PartType.RESISTOR, PartType.CAPACITOR):
        return ""
    a = part.attrs

    if part.type is PartType.INDUCTOR:
        kind = _lower(a.get("kind"))
        tail = "ferrite bead" if "ferrite" in kind or "bead" in kind else "inductor"
        return _join(a.get("value"), a.get("rating"), a.get("package"), tail)

    if part.type is PartType.DIODE:
        return _join(
            _lower(a.get("kind")),
            a.get("rating"),
            a.get("current"),
            a.get("package"),
            "diode",
        )

    if part.type is PartType.LED:
        return _join(
            _lower(a.get("color")),
            a.get("rating"),
            a.get("current"),
            a.get("package"),
            "led",
        )

    if part.type is PartType.TRANSISTOR:
        return _join(
            _lower(a.get("polarity")),
            a.get("rating"),
            a.get("current"),
            a.get("package"),
            "transistor",
        )

    if part.type is PartType.CRYSTAL:
        return _join(
            a.get("value"),
            a.get("load"),
            a.get("stability"),
            a.get("package"),
            "crystal",
        )

    if part.type is PartType.IC:
        return _describe_ic(a)

    return ""


def _describe_ic(a: dict[str, str]) -> str:
    type_word = _lower(a.get("type_word") or a.get("category_leaf") or "ic")
    channels = _count(a.get("channels"))
    resolution = _bits(a.get("resolution"))

    if "adc/dac" in type_word:
        return _join(channels, resolution, "adc/dac")
    if "dac" in type_word or "adc" in type_word:
        return _join(channels, resolution, type_word)
    if "op-amp" in type_word or "amplifier" in type_word:
        return _join(channels, a.get("bandwidth"), type_word)
    if "regulator" in type_word:
        return _join(
            _lower(a.get("topology")),
            a.get("supply"),
            a.get("current"),
            a.get("package"),
            type_word,
        )
    if "mcu" in type_word or "microcontroller" in type_word:
        return _join(
            _lower(a.get("core")),
            a.get("speed"),
            a.get("flash"),
            a.get("package"),
            "mcu",
        )
    return _join(type_word, a.get("package"))
