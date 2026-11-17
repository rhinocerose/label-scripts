"""labelkit command line interface."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .cache import Cache
from .config import Config
from .digikey import DigiKeyResolver
from .lbx import LbxError, export_lbx
from .lcsc import LcscResolver
from .model import PartType
from .pipeline import RunResult, run_pipeline
from .printers import LabelJob, PrinterError, get_printer
from .render import safe_filename
from .sources import load_input, read_mpn_lines
from .templates import TemplateError, load_templates


def _credentials() -> tuple[str, str]:
    return (
        os.environ.get("DIGIKEY_CLIENT_ID", "").strip(),
        os.environ.get("DIGIKEY_CLIENT_SECRET", "").strip(),
    )


def _read_parts(
    paths: list[str],
    pns: list[str] | None = None,
    trust_description: bool = False,
):
    parts = []
    if pns:
        parts.extend(read_mpn_lines(pns, source="<command line>"))

    if not paths:
        if pns:
            return parts
        if sys.stdin.isatty():
            print(
                "Enter MPNs or LCSC part numbers, one per line (Ctrl-D to finish).",
                file=sys.stderr,
            )
        parts.extend(read_mpn_lines(sys.stdin.read().splitlines(), source="<stdin>"))
        return parts

    for raw in paths:
        if raw == "-":
            parts.extend(read_mpn_lines(sys.stdin.read().splitlines(), source="<stdin>"))
            continue
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"input not found: {path}")
        parts.extend(load_input(path, trust_description=trust_description))
    return parts


def _make_resolver(args, config: Config):
    if args.offline:
        return None, None, None

    cache = Cache(config.cache_path)
    client_id, client_secret = _credentials()
    digikey = DigiKeyResolver(
        client_id,
        client_secret,
        site=config.site,
        language=config.language,
        currency=config.currency,
        min_interval=config.min_interval,
        cache_ttl=config.cache_ttl,
        cache=cache,
    )
    lcsc = None
    if not getattr(args, "no_lcsc", False):
        lcsc = LcscResolver(
            cache=cache,
            min_interval=config.lcsc_min_interval,
            cache_ttl=config.cache_ttl,
        )
    return digikey, lcsc, cache


def _print_result(result: RunResult) -> None:
    stats = result.stats
    print(f"Loaded {stats['total']} parts")
    print(f"  verified:   {stats['verified']}")
    print(f"  unverified: {stats['unverified']}")
    print(f"  mismatch:   {stats['mismatch']}")
    print(f"  blocked:    {stats['blocked']}")
    print(f"  conflicts:  {stats.get('conflicts', 0)}")
    print(f"  duplicates merged: {stats['duplicates_merged']}")

    template_outputs = {
        key: path
        for key, path in result.outputs.items()
        if key not in {"parts", "review", "json"}
    }
    if template_outputs:
        print("Wrote label CSVs:")
        for key, path in template_outputs.items():
            ptype = PartType.parse(key)
            count = sum(1 for part in result.printable if part.type is ptype)
            print(f"  {path}  ({count} rows)")

    print("Audit files:")
    print(f"  {result.outputs['parts']}")
    print(f"  {result.outputs['review']}")
    print(f"  {result.outputs['json']}")


def cmd_run(args) -> int:
    config = Config.load(args.config)
    if args.allow_unverified and not args.trust_description:
        print(
            "labelkit: --allow-unverified requires --trust-description; "
            "MPN-only rows will still be blocked",
            file=sys.stderr,
        )
    parts = _read_parts(args.inputs, args.pn, args.trust_description)
    if not parts:
        print("labelkit: no parts found in the input", file=sys.stderr)
        return 2

    resolver, lcsc, cache = _make_resolver(args, config)
    try:
        result = run_pipeline(
            parts,
            out_dir=args.out or config.output_dir,
            templates_dir=args.templates or config.templates_dir,
            resolver=resolver,
            lcsc_resolver=lcsc,
            allow_unverified=args.allow_unverified,
            interactive=(not args.no_review and sys.stdin.isatty()),
            sort=args.sort,
            strict=args.strict,
        )
    finally:
        if resolver is not None:
            resolver.close()
        if lcsc is not None:
            lcsc.close()
        if cache is not None:
            cache.close()

    _print_result(result)
    problems = (
        result.stats["mismatch"]
        + result.stats["blocked"]
        + result.stats["unverified"]
        + result.stats.get("conflicts", 0)
    )
    return 0 if problems == 0 else 1


def cmd_inspect(args) -> int:
    parts = _read_parts(args.inputs, args.pn, args.trust_description)
    if not parts:
        print("labelkit: no parts found in the input", file=sys.stderr)
        return 2

    print(f"{'LCSC':<10} {'MPN':<26} {'TYPE':<11} {'VALUE':<9} {'RATING':<8} "
          f"{'TOL':<6} {'PKG':<9} STATUS")
    print("-" * 100)
    for part in parts:
        print(
            f"{part.supplier_pn:<10} {part.mpn:<26} {part.type.value:<11} "
            f"{part.attrs.get('value',''):<9} {part.attrs.get('rating',''):<8} "
            f"{part.attrs.get('tolerance',''):<6} {part.attrs.get('package',''):<9} "
            f"{part.status.value}"
        )
        if part.issues:
            print(f"{'':<10} ! {'; '.join(part.issues)}")

    counts: dict[str, int] = {}
    for part in parts:
        counts[part.type.value] = counts.get(part.type.value, 0) + 1
    print("-" * 100)
    print(f"{len(parts)} parts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


def cmd_templates(args) -> int:
    templates = load_templates(args.templates)
    for ptype, template in templates.items():
        print(f"{template.name}  ({ptype.value}, {template.tape_mm} mm tape)")
        print("  " + ", ".join(template.headers))
        if template.layout:
            print(
                f"  layout: {template.layout.length_mm:g} mm, "
                f"{len(template.layout.items)} objects"
            )
        if template.source:
            print(f"  {template.source}")
    return 0


def cmd_export_lbx(args) -> int:
    config = Config.load(args.config)
    templates = load_templates(args.templates or config.templates_dir)
    selected = [
        template
        for template in templates.values()
        if not args.type or template.part_type.value == args.type
    ]
    if not selected:
        print(f"labelkit: no template for type {args.type}", file=sys.stderr)
        return 2

    out = Path(args.out)
    for template in selected:
        if template.layout is None:
            print(f"labelkit: {template.name} has no layout", file=sys.stderr)
            return 2
        path = out / f"{safe_filename(template.name)}.lbx"
        export_lbx(
            template,
            path,
            printer_name=config.ptouch_printer_name,
            printer_id=config.ptouch_printer_id,
            format_id=config.ptouch_format,
        )
        print(path)
    return 0


def cmd_print(args) -> int:
    directory = Path(args.in_dir)
    if not directory.is_dir():
        print(f"labelkit: output directory not found: {directory}", file=sys.stderr)
        return 2

    csv_paths = [
        path
        for path in sorted(directory.glob("*.csv"))
        if path.name not in {"parts.csv", "review.csv"}
    ]
    if not csv_paths:
        print(f"labelkit: no label CSVs in {directory}", file=sys.stderr)
        return 2

    jobs = []
    for path in csv_paths:
        with open(path, encoding="utf-8") as handle:
            rows = max(0, sum(1 for _ in handle) - 1)
        jobs.append(LabelJob(name=path.stem, csv_path=path, rows=rows))

    try:
        backend = get_printer(args.backend)
    except PrinterError as exc:
        print(f"labelkit: {exc}", file=sys.stderr)
        return 2

    if not backend.available():
        print(
            f"labelkit: {backend.name} is not available on this machine",
            file=sys.stderr,
        )
        return 2

    try:
        for line in backend.print(jobs):
            print(line)
    except PrinterError as exc:
        print(f"labelkit: {exc}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labelkit",
        description="Unified part data to Brother P-touch label pipeline.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="ingest, verify and write label CSVs")
    run.add_argument("inputs", nargs="*", help="LCSC CSV / MPN list / '-' for stdin")
    run.add_argument(
        "-p",
        "--pn",
        action="append",
        default=[],
        help="MPN or LCSC number to add (repeatable)",
    )
    run.add_argument("--out", help="output directory (default: out)")
    run.add_argument("--templates", help="template directory")
    run.add_argument("--config", help="config TOML file")
    run.add_argument("--offline", action="store_true", help="never call DigiKey or LCSC")
    run.add_argument(
        "--no-lcsc",
        action="store_true",
        help="disable LCSC lookups (DigiKey only)",
    )
    run.add_argument(
        "--strict",
        action="store_true",
        help="block rows where LCSC and DigiKey disagree (default: flag)",
    )
    run.add_argument(
        "--trust-description",
        action="store_true",
        help="parse LCSC descriptions and verify them (default: MPN only)",
    )
    run.add_argument(
        "--allow-unverified",
        action="store_true",
        help="with --trust-description, allow rows when web verification is unavailable",
    )
    run.add_argument("--no-review", action="store_true", help="never prompt")
    run.add_argument(
        "--sort",
        choices=["value", "text", "none"],
        default="value",
        help="label ordering within each template",
    )

    inspect = sub.add_parser("inspect", help="parse inputs without network, show a table")
    inspect.add_argument("inputs", nargs="*", help="LCSC CSV / MPN list / '-' for stdin")
    inspect.add_argument(
        "-p",
        "--pn",
        action="append",
        default=[],
        help="MPN or LCSC number to add (repeatable)",
    )
    inspect.add_argument(
        "--trust-description",
        action="store_true",
        help="parse LCSC descriptions and show their attributes (default: MPN only)",
    )
    inspect.add_argument("--config", help="config TOML file")

    templates = sub.add_parser("templates", help="list label templates")
    templates.add_argument("--templates", help="template directory")

    lbx = sub.add_parser(
        "export-lbx", help="export YAML layouts as P-touch .lbx templates"
    )
    lbx.add_argument("--out", default="out/templates", help="output directory")
    lbx.add_argument("--templates", help="template directory")
    lbx.add_argument("--config", help="config TOML file")
    lbx.add_argument(
        "--type",
        choices=[ptype.value for ptype in PartType if ptype is not PartType.UNKNOWN],
        help="only export this part type",
    )

    printer = sub.add_parser("print", help="send generated CSVs to a printer backend")
    printer.add_argument("--in", dest="in_dir", default="out", help="output directory")
    printer.add_argument(
        "--backend",
        choices=["csv", "bpac", "ptouch-print"],
        default="csv",
        help="printer backend (v1 only csv is functional)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "inspect":
            return cmd_inspect(args)
        if args.command == "templates":
            return cmd_templates(args)
        if args.command == "export-lbx":
            return cmd_export_lbx(args)
        if args.command == "print":
            return cmd_print(args)
    except (FileNotFoundError, TemplateError, LbxError, ValueError) as exc:
        print(f"labelkit: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("labelkit: interrupted", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
