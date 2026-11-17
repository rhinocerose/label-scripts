"""Configuration loading (TOML)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def _default_cache_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser()
    return root / "labelkit" / "cache.db"


@dataclass
class Config:
    site: str = "US"
    language: str = "en"
    currency: str = "USD"
    min_interval: float = 1.0
    lcsc_min_interval: float = 1.0
    cache_ttl: int = 7 * 86400
    cache_path: Path = field(default_factory=_default_cache_path)
    output_dir: Path = Path("out")
    templates_dir: Path | None = None
    tape_mm: int = 12
    ptouch_printer_name: str = ""
    ptouch_printer_id: int | None = None
    ptouch_format: int | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        config = cls()
        if tomllib is None:  # pragma: no cover
            return config

        candidates: list[Path]
        if path is not None:
            candidates = [Path(path).expanduser()]
        else:
            candidates = [
                Path("labelkit.toml"),
                Path("~/.config/labelkit/config.toml").expanduser(),
            ]

        for candidate in candidates:
            if not candidate.is_file():
                if path is not None:
                    raise FileNotFoundError(f"config file not found: {candidate}")
                continue
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            digikey = data.get("digikey") or {}
            lcsc = data.get("lcsc") or {}
            cache = data.get("cache") or {}
            output = data.get("output") or {}
            labels = data.get("labels") or {}
            ptouch = data.get("ptouch") or {}

            config.site = str(digikey.get("site") or config.site)
            config.language = str(digikey.get("language") or config.language)
            config.currency = str(digikey.get("currency") or config.currency)
            config.min_interval = float(
                digikey.get("min_interval_s", config.min_interval)
            )
            config.lcsc_min_interval = float(
                lcsc.get("min_interval_s", config.lcsc_min_interval)
            )
            if "cache_ttl_days" in digikey:
                config.cache_ttl = int(float(digikey["cache_ttl_days"]) * 86400)

            if cache.get("path"):
                config.cache_path = Path(str(cache["path"])).expanduser()
            if output.get("dir"):
                config.output_dir = Path(str(output["dir"])).expanduser()
            if labels.get("templates_dir"):
                config.templates_dir = Path(str(labels["templates_dir"])).expanduser()
            if labels.get("tape_mm"):
                config.tape_mm = int(labels["tape_mm"])
            if ptouch.get("printer_name"):
                config.ptouch_printer_name = str(ptouch["printer_name"])
            if ptouch.get("printer_id") not in (None, ""):
                config.ptouch_printer_id = int(ptouch["printer_id"])
            if ptouch.get("format") not in (None, ""):
                config.ptouch_format = int(ptouch["format"])
            break

        return config
