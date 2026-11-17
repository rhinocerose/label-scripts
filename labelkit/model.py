"""Canonical part model shared by every input and output path."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .values import Quantity


class PartType(str, Enum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    DIODE = "diode"
    LED = "led"
    TRANSISTOR = "transistor"
    IC = "ic"
    CRYSTAL = "crystal"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: object) -> "PartType":
        if isinstance(value, cls):
            return value
        s = str(value or "").strip().lower()
        for item in cls:
            if item.value == s:
                return item
        return cls.UNKNOWN

    @property
    def label(self) -> str:
        return {
            "resistor": "Resistor",
            "capacitor": "Capacitor",
            "inductor": "Inductor",
            "diode": "Diode",
            "led": "LED",
            "transistor": "Transistor",
            "ic": "IC",
            "crystal": "Crystal",
            "unknown": "Unknown",
        }[self.value]


class Status(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    BLOCKED = "blocked"


@dataclass
class Part:
    """One physical part, independent of where it came from."""

    source: str = ""  # lcsc | manual
    supplier_pn: str = ""  # LCSC part number, when known
    mpn: str = ""
    manufacturer: str = ""
    type: PartType = PartType.UNKNOWN
    qty: int = 0
    description: str = ""  # canonical, generated from attrs
    source_description: str = ""  # original supplier text, audit only
    datasheet: str = ""
    project: str = ""
    price: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    values: dict[str, Quantity] = field(default_factory=dict)
    status: Status = Status.UNVERIFIED
    verified_by: str = ""
    issues: list[str] = field(default_factory=list)
    field_sources: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    source_line: int = 0
    confidence: float = 0.0

    # -- attribute helpers -------------------------------------------------

    def get(self, key: str, default: str = "") -> str:
        return self.attrs.get(key, default)

    def set_attr(self, key: str, value: object, source: str = "") -> None:
        text = "" if value is None else str(value)
        if not text:
            return
        self.attrs[key] = text
        if source:
            self.field_sources[key] = source

    def set_value(self, key: str, quantity: Quantity | None, source: str = "") -> None:
        if quantity is None:
            return
        self.values[key] = quantity
        self.attrs[key] = quantity.text()
        if source:
            self.field_sources[key] = source

    def block(self, reason: str) -> None:
        self.status = Status.BLOCKED
        if reason not in self.issues:
            self.issues.append(reason)

    # -- identity ----------------------------------------------------------

    @property
    def dedupe_key(self) -> tuple[str, str]:
        if self.supplier_pn:
            return (self.source or "supplier", self.supplier_pn.upper())
        return ("mpn", self.mpn.upper())

    @property
    def is_verified(self) -> bool:
        return self.status is Status.VERIFIED

    def is_printable(self, allow_unverified: bool = False) -> bool:
        if self.status is Status.VERIFIED:
            return True
        if allow_unverified and self.status is Status.UNVERIFIED:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "type": self.type.value,
            "source": self.source,
            "supplier_pn": self.supplier_pn,
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "qty": self.qty,
            "description": self.description,
            "source_description": self.source_description,
            "datasheet": self.datasheet,
            "attrs": dict(self.attrs),
            "values": {k: v.text() for k, v in self.values.items()},
            "issues": list(self.issues),
            "field_sources": dict(self.field_sources),
            "verified_by": self.verified_by,
        }


@dataclass
class ProviderResult:
    """A part as returned by a web provider (currently DigiKey)."""

    provider: str
    mpn: str
    manufacturer: str = ""
    description: str = ""
    category: str = ""
    datasheet: str = ""
    supplier_pn: str = ""
    type: PartType = PartType.UNKNOWN
    attrs: dict[str, str] = field(default_factory=dict)
    values: dict[str, Quantity] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.attrs.get(key, default)
