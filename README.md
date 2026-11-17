# labelkit

One pipeline from parts to Brother P-touch labels.

- **MPN-first.** Label values come from DigiKey by exact MPN; LCSC fills
  gaps and supplies the LCSC part number. An LCSC description is reference
  only unless you pass `--trust-description`.
- **A part-number CSV is enough.** `lcsc_pn,mpn,qty`, or a single
  `part_number` column with automatic LCSC/MPN detection.
- **Normalized output.** One spelling per package (`0603`, never
  `0603 (1608 Metric)`), RKM resistance (`4k7`), `C0G` for NP0/NPO.
- **Generated descriptions** for non-passives: `4-ch 12-bit dac`,
  `schottky 40V 1A SOD-123 diode`, `16MHz 20pF 30ppm 3225 crystal`.
- **Nothing is guessed.** A row with no resolved source, or a strict
  conflict, is written to `review.csv` and excluded.

## Quick start

```bash
python3 -m pip install -e .        # or run `python3 -m labelkit ...`

# Part-number CSV (LCSC PN and/or MPN)
labelkit run parts.csv --out out

# LCSC invoice / BOM export: MPN column is used, description ignored
labelkit run caps.csv resistors.csv --out out

# Typed MPNs
labelkit run -p RC0603FR-0710KL -p GRM1555C1H471JA01D --out out

# Or stdin
printf 'RC0603FR-0710KL\nGRM1555C1H471JA01D\n' | labelkit run --out out

# Parse only, no network
labelkit inspect caps.csv
labelkit templates
```

A part-number CSV looks like this:

```csv
lcsc_pn,mpn,qty
C22548,RC0603FR-071K,100
C100042,,25
,GRM1555C1H471JA01D,50
```

Either column may be blank, and a single `part_number` column works too:

```csv
part_number,qty
C22548,100
RC0603FR-0710KL,50
```

- LCSC PN only: LCSC resolves the MPN and attributes, then DigiKey verifies.
- MPN only: DigiKey resolves it; LCSC is searched by MPN to backfill the
  LCSC part number.
- Both: DigiKey is primary, LCSC fills missing fields, conflicts are
  flagged. `--strict` blocks on any disagreement instead.

Outputs:

```
out/capacitor.csv      merge CSV for the capacitor template
out/resistor.csv       merge CSV for the resistor template
out/<type>.csv         one per part type present
out/parts.csv          every parsed part, status, description, conflicts
out/review.csv         blocked rows, strict conflicts and their reasons
out/parts.json         machine-readable snapshot for `labelkit print`
```

## Format normalization

`labelkit/formats.yaml` is the editable source of truth. Current defaults:

| Kind | Canonical | Accepted variants |
|---|---|---|
| Chip passives | `0603` | `0603`, `1608`, `1608 Metric`, `0603 (1608 Metric)`, `603` |
| Other chip sizes | `0402`, `0805`, `1206`, `1210`, `2010`, `2512` | metric equivalents map to the imperial code |
| Crystals | `3225` | `3225`, `3.2x2.5` (metric kept, unlike passives) |
| SOT | `SOT-23`, `SOT-23-5`, `SOT-223` | `SOT23`, `SOT23-5`, `SOT-23-3` |
| SOD | `SOD-123`, `SOD-323` | `SOD123` |
| SOIC/TSSOP/QFN | `SOIC-8`, `TSSOP-16`, `QFN-32` | `SOIC8`, `14-TSSOP`, `14TSSOP`, `TSSOP14` |
| Diodes | `SMA`, `SMB`, `SMC` | `DO-214AC`, `DO-214AA`, `DO-214AB` |
| Power | `DPAK`, `D2PAK`, `TO-220` | `TO-252`, `TO-263` |
| Through-hole | `DIP-8` | `DIP8`, `PDIP-8` |

Values:

| Kind | Canonical | Examples normalized |
|---|---|---|
| Resistance | RKM: `4k7`, `1M69`, `590R`, `4R7`, `1R` | `4.7k`, `4k7`, `4700`, `4.7 kOhms` -> `4k7` |
| Capacitance | `100nF`, `1uF`, `4.7pF` | `0.1uF`, `100000pF` -> `100nF` |
| Inductance | `1uH`, `4.7nH` | `1000nH` -> `1uH` |
| Voltage | `50V` | `50 V`, `50VDC` |
| Power | `100mW`, `1W` | `0.1W`, `1/10W` -> `100mW` |
| Current | `20mA`, `1.5A` | `0.02A` -> `20mA` |
| Frequency | `16MHz`, `32.768kHz` | `16000kHz` -> `16MHz` |
| Tolerance | `1%`, `0.1%`, `0.02%` | `±1.0%`, `0.10%` |
| Dielectric | `C0G`, `X7R`, `X5R` | `NP0`, `NPO` -> `C0G` |

Pin count may come before or after the family: `14-TSSOP`, `14tssop`,
`tssop14`, `TSSOP 14`, and `TSSOP-14` all become `TSSOP-14`. `SO` maps to
`SOIC` and `PDIP` maps to `DIP`; `5-SOT-23` becomes `SOT-23-5`, while
`3-SOT-23` collapses to `SOT-23`.

Edit the YAML to change a package alias or the resistance style; no code
change is needed.

## Normalized descriptions

Resistors and capacitors deliberately have **no description**: their
Resistance/Capacitance/Voltage/Tolerance/Dielectric/Size columns already
say everything, and the label templates have no Description column.

Every other type gets one generated line, built from the verified
attributes rather than the supplier's text:

| Type | Example |
|---|---|
| Inductor | `1uH 1.5A 0603 inductor` |
| Ferrite bead | `120R 1A 0603 ferrite bead` |
| Diode | `schottky 40V 1A SOD-123 diode` |
| LED | `green 2.1V 20mA 0603 led` |
| Transistor | `npn 40V 200mA SOT-23 transistor` |
| Crystal | `16MHz 20pF 30ppm 3225 crystal` |
| DAC | `4-ch 12-bit dac` |
| ADC | `2-ch 16-bit adc` |
| Op-amp | `2-ch 10MHz op-amp` |
| Regulator | `ldo 3.3V 1A SOT-223 regulator` |
| MCU | `arm cortex-m3 72MHz 64KB LQFP-48 mcu` |
| Generic IC | `eeprom SOIC-8` |

For ICs the type word and channel/resolution fields come from the DigiKey
category and parameters (`Number of D/A Converters`, `Number of Bits`,
`Gain Bandwidth Product`, ...). DAC/ADC/op-amp/regulator/MCU patterns are
covered; other ICs fall back to `<type> <package>`.

The normalized description is a column in every non-passive label CSV and
in `parts.csv`. The raw supplier text is kept as `source_description`.

## Credentials and configuration

```bash
export DIGIKEY_CLIENT_ID=...
export DIGIKEY_CLIENT_SECRET=...
```

DigiKey uses the v4 product search API with the required
`X-DIGIKEY-Client-Id` / `X-DIGIKEY-Locale-*` headers. LCSC needs no key:
it uses the site's search JSON endpoint and falls back to the product
page's embedded JSON. Both are cached in SQLite
(`~/.cache/labelkit/cache.db`) and rate-limited.

Copy `labelkit.example.toml` to `labelkit.toml` to change locale, cache
path, output directory, rate limits, or tape width.

## Verification and source policy

| Input | Label values from | DigiKey | LCSC | Blocked when |
|---|---|---|---|---|
| MPN list / typed | DigiKey | preferred | fills gaps | neither resolves, or `--strict` conflict |
| LCSC invoice (default) | DigiKey by MPN | preferred | fills gaps | neither resolves, or `--strict` conflict |
| LCSC invoice + `--trust-description` | description | preferred | optional | description/source disagreement |
| ... + `--allow-unverified` | description | not required | not required | never on a known disagreement |

- DigiKey is primary; LCSC fills missing fields and supplies the LCSC PN.
- Disagreements are recorded in `review.csv`, and DigiKey values win.
  `--strict` blocks the row instead.
- `--no-lcsc` disables LCSC lookups entirely.
- `--trust-description` opts into parsing LCSC invoice descriptions and
  verifying them. `--allow-unverified` only relaxes the no-web-access case
  in that mode.

Numeric fields agree within 1 ppm (`4.7 kOhms` = `4k7`, `0.1W` = `100mW`);
`NP0`/`NPO`/`C0G` are equivalent; `0603` and `0603 (1608 Metric)` are
equivalent.

## Templates

Templates live in `labelkit/templates/*.yaml`:

```yaml
name: diode
part_type: diode
tape_mm: 12
fields:
  - {key: supplier_pn, header: "LCSC Number"}
  - {key: mpn,        header: "MPN"}
  - {key: rating,     header: "Voltage"}
  - {key: current,    header: "Current"}
  - {key: package,    header: "Size"}
  - {key: description, header: "Description"}
```

| type | columns |
|---|---|
| resistor | LCSC Number, MPN, Resistance, Power, Tolerance, Size |
| capacitor | LCSC Number, MPN, Capacitance, Voltage, Tolerance, Dielectric, Size |
| inductor | LCSC Number, MPN, Value, Current, Tolerance, Size, Description |
| diode | LCSC Number, MPN, Voltage, Current, Size, Description |
| led | LCSC Number, MPN, Color, Voltage, Current, Size, Description |
| transistor | LCSC Number, MPN, Type, Voltage, Current, Size, Description |
| crystal | LCSC Number, MPN, Frequency, Load, Stability, Size, Description |
| ic | LCSC Number, MPN, Package, Description |

The resistor and capacitor headers match the existing `caps_out.csv` /
`resistors_out.csv`, so the current P-touch Editor merge layout keeps
working. Edit a YAML to change columns or tape width; `--templates DIR`
points at an alternative directory.

## Label ordering

Within a template, rows are sorted by numeric value (`--sort value`), with
package and MPN as tie-breakers. `--sort text` sorts lexicographically;
`--sort none` keeps input order. Duplicate supplier/MPN rows are merged and
their quantities summed.

## P-touch `.lbx` templates (12 mm)

Each YAML template has a `layout` section describing the label in
millimetres, relative to the printable area:

```yaml
layout:
  length_mm: 22
  margin_mm: 1.0
  # auto_length: false
  items:
    - {field: value,       x: 0, y: 0,    w: 10, h: 7,   size: 13, bold: true, align: center, valign: middle}
    - {field: tolerance,   x: 0, y: 7.2,  w: 5,  h: 4,   size: 8}
    - {field: package,     x: 5, y: 7.2,  w: 5,  h: 4,   size: 8}
    - {field: mpn,         x: 0, y: 11.5, w: 10, h: 4,   size: 6}
    - {field: supplier_pn, x: 0, y: 15.7, w: 10, h: 3.5, size: 5.5}
```

- `field` is a template field or a special (`mpn`, `supplier_pn`,
  `description`); `text` is static text.
- `x`/`y`/`w`/`h` are mm from the top-left of the printable area; `size`
  is points.
- Boxes are validated against `tape_mm - 2 * margin_mm` and
  `length_mm - 2 * margin_mm` when the template loads, so a typo fails
  before printing.
- `align`: `left`/`center`/`right`/`justify`; `valign`:
  `top`/`middle`/`bottom`.
- `shrink: true` lets P-touch Editor shrink long text to fit.
- `name` overrides the b-PAC object name; repeated names get `_2`, `_3`.
- `auto_length: true` exports an auto-length canvas; the default is a fixed
  strip of `length_mm`.

Export:

```bash
labelkit export-lbx --out out/templates
labelkit export-lbx --out out/templates --type resistor
```

Each `.lbx` is a ZIP containing `label.xml` and `prop.xml`. Text objects
are named after their fields, so b-PAC can fill them directly:

```vb
ObjDoc.GetObject("value").Text = "4k7"
ObjDoc.GetObject("mpn").Text = "RC0603FR-074K7L"
```

The default paper is 12 mm wide with 1 mm margins, leaving a 10 mm
printable width. 12 mm is narrow: long MPNs and descriptions may shrink or
wrap; raise a box's `h` or lower its `size` in the YAML if the result is
too small. If Editor asks for a printer or rejects the format, create
one blank 12 mm label in P-touch Editor, save it, and copy its
`format`/`printerID` values into `labelkit.toml`:

```toml
[ptouch]
printer_name = "Brother PT-P710BT"
# printer_id = 0
# format = 0
```

`.lbx` is an undocumented ZIP+XML format. The exporter follows the
P-touch Editor 5.x schema and the output is covered by tests, but open the
first file in Editor on the target machine before relying on it.

## Printing

```bash
labelkit print --in out --backend csv
```

`csv` is the only functional backend today: it reports the generated merge
CSVs, which are what you feed to P-touch Editor's database merge.

`bpac` (Windows + P-touch Editor SDK) and `ptouch-print` (Linux/WSL, USB
passthrough) implement the same interface and fail with a clear message
instead of pretending. `export-lbx` produces the P-touch template from the
same YAML; `print` still consumes the CSVs.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite is offline and covers RKM formatting, package normalization,
description generation, LCSC/DigiKey mapping, caching, the part-number CSV
shapes, the source policy (including conflicts and strict mode), template
layout validation, `.lbx` ZIP/XML export, the CLI, and the full pipeline.

## Known limitations

- LCSC has no public product API. The search JSON/product-page scraper is
  best-effort; if the site changes, it returns no result and DigiKey alone
  is used.
- No connector template yet.
- b-PAC and ptouch-print are interfaces only; no raster renderer yet.
- `.lbx` is an undocumented ZIP+XML format. The exporter follows the
  P-touch Editor 5.x schema, but printer-specific `format`/`printerID`
  values may need to be copied from a blank label saved by Editor.
- IC descriptions are best-effort from common parameters; unusual ICs fall
  back to `<type> <package>`.

## Data caveat

The old resistor CSV contains rows where the description and MPN disagree,
e.g. `RC0603FR-072K2L` is 2.2 kOhm by part number while the description
says 2.32 k. In the default MPN-only mode those descriptions are never
used. In `--trust-description` mode the rows are flagged as mismatches and
must be resolved in `review.csv` before printing.
