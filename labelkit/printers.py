"""Printer backend interface.

v1 only ships the ``csv`` backend: the merge CSVs are the artifact you
feed to P-touch Editor today.  The b-PAC (.lbx) and ptouch-print (raster)
backends implement the same interface and are deliberately explicit
about not being wired up yet, instead of pretending to print.
"""

from __future__ import annotations

import platform
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class PrinterError(RuntimeError):
    pass


@dataclass
class LabelJob:
    name: str
    csv_path: Path
    rows: int = 0


class Printer(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def print(self, jobs: list[LabelJob]) -> list[str]:
        raise NotImplementedError


class CsvPrinter(Printer):
    """No-op backend: the CSVs already exist and are the deliverable."""

    name = "csv"

    def available(self) -> bool:
        return True

    def print(self, jobs: list[LabelJob]) -> list[str]:
        return [
            f"{job.name}: {job.csv_path} ({job.rows} label rows)" for job in jobs
        ]


class BpacPrinter(Printer):
    """Brother b-PAC (Windows COM), filling fields in a .lbx template."""

    name = "bpac"

    def available(self) -> bool:
        return platform.system() == "Windows"

    def print(self, jobs: list[LabelJob]) -> list[str]:
        raise PrinterError(
            "The b-PAC backend is not implemented yet. It needs Windows, "
            "P-touch Editor with the b-PAC SDK, and one .lbx template per "
            "part type. The per-template CSVs in "
            f"{jobs[0].csv_path.parent if jobs else 'out/'} already match the "
            "YAML field order, so P-touch Editor's database merge works today."
        )


class PtouchPrintPrinter(Printer):
    """Linux-native printing via ptouch-print + rendered label images."""

    name = "ptouch-print"

    def available(self) -> bool:
        return shutil.which("ptouch-print") is not None

    def print(self, jobs: list[LabelJob]) -> list[str]:
        raise PrinterError(
            "The ptouch-print backend is not implemented yet. It needs the "
            "printer passed into WSL (usbipd) and a raster renderer driven by "
            "the YAML layout. For now use the csv backend."
        )


_PRINTERS: dict[str, type[Printer]] = {
    "csv": CsvPrinter,
    "bpac": BpacPrinter,
    "ptouch-print": PtouchPrintPrinter,
}


def get_printer(name: str) -> Printer:
    try:
        printer_class = _PRINTERS[name]
    except KeyError as exc:
        raise PrinterError(
            f"unknown printer backend {name!r}; choose one of {', '.join(_PRINTERS)}"
        ) from exc
    return printer_class()
