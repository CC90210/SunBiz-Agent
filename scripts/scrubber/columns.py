"""scrubber/columns.py — header adapter: live shared-sheet schema → the keys
import_mca_leads.map_row_to_lead_data() expects.

WHY THIS EXISTS: import_mca_leads.py was written for Adon's ORIGINAL export
(headers: "Phone Number", "Positions", "Funding Company"). The live sheets
SunBiz shares from admin@sunbizfunding.com use a DIFFERENT schema:

    Phone 1 (most accurate) | P1 Type | Phone 2 | P2 Type | First Name |
    Last Name | Company | Email | Company Email | Revenue ($) |
    Positions (MCA stack) | Funding Detail

read_rows() normalizes headers via _norm_header (lowercase, non-alnum→"_"),
so "Phone 1 (most accurate)" → "phone_1_most_accurate", "Positions (MCA
stack)" → "positions_mca_stack", "Funding Detail" → "funding_detail".

Without remapping, the importer reads phone_number / positions /
funding_company as None and silently produces phone-less, position-less,
funder-less leads (and therefore a meaningless leverage score). This adapter
bridges the two schemas. It is a NO-OP on the original format (those headers
already match the importer's keys, so none of the aliases below collide).
"""

from __future__ import annotations

from typing import Any

# normalized-source-header → importer-expected-key.
# Only fills the importer key when the source header is present AND the
# importer key isn't already populated (so the original schema is untouched).
HEADER_ALIASES: dict[str, str] = {
    # phones
    "phone_1_most_accurate": "phone_number",
    "phone_1": "phone_number",
    "phone1": "phone_number",
    "best_phone_1": "phone_number",
    "phone_2": "phone2",
    "best_phone_2": "phone2",
    "phone_3": "phone3",
    # phone type metadata (importer reads numbertype_2 / numbertype_3)
    "p2_type": "numbertype_2",
    "p3_type": "numbertype_3",
    # MCA fields
    "positions_mca_stack": "positions",
    "position_mca_stack": "positions",
    "funding_detail": "funding_company",
    "funding_details": "funding_company",
    # revenue (importer already accepts "revenue"/"annual_revenue"; map the
    # parenthesized variant just in case _norm_header leaves a trailing token)
    "revenue": "revenue",
}


def normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `raw` with importer-expected keys filled in
    from their live-sheet aliases. Original keys are preserved (so
    sheet-column 'previously submitted' detection still works)."""
    out = dict(raw)
    for src, dst in HEADER_ALIASES.items():
        if src == dst:
            continue
        if src in out:
            src_val = out.get(src)
            dst_val = out.get(dst)
            src_filled = src_val not in (None, "")
            dst_empty = dst_val in (None, "")
            if src_filled and dst_empty:
                out[dst] = src_val
    return out
