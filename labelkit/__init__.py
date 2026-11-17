"""labelkit -- one pipeline from parts to Brother P-touch labels.

The MPN is the primary key: label values come from DigiKey by exact MPN,
with LCSC used to fill gaps and supply the LCSC part number.  A
part-number CSV may contain an LCSC PN, an MPN, or both.

LCSC descriptions are reference-only by default; ``--trust-description``
opts into parsing them and verifying them against the web sources.

Output is normalized (imperial chip sizes, RKM resistances, C0G
dielectrics) and non-passive parts get a generated one-line description.
Nothing is guessed: unresolved rows are written to ``review.csv`` and
excluded from the printable labels.
"""

__version__ = "0.1.0"
