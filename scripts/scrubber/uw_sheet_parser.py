"""scrubber/uw_sheet_parser.py — parse ONE Breeze per-deal "UW Sheet 2.5" form.

Each UW Sheet is a single deal (one merchant) in a FORM layout (label cell +
value cell), NOT a row-table. This module reads the authoritative tab and
produces the canonical deal dict the scorer consumes.

LABEL-DRIVEN (resilient to row/col drift): we locate each field by its LABEL
text and read a known offset, rather than hardcoding coordinates.

Layout (verified 2026-06-30 against EAGLE METAL + METROCITY):
  Left block   — label in col A, value in col B (rows ~2-9 + "1st Position").
  Revenue table— header row carries "True Revenue" + "Monthly Leverage"; the
                 "Average" row holds the per-deal averages (True Revenue avg,
                 Monthly Leverage avg).
  Positions box— header row has Status/Funder/Daily/Weekly/Monthly/
                 "Leverage Per Funder"; one row per funder until a "Total" row.

CC's funder rule (2026-06-30): a "position/funder" that COUNTS is one paying
DAILY or WEEKLY. MONTHLY-cadence lenders are NOT positions and do NOT count
toward the position count or the leverage %. So position_count and leverage_pct
are computed over daily/weekly funders only.
"""

from __future__ import annotations

import re
from typing import Any, Optional

PREFERRED_TABS = ["UW Sheet 2.5", "UW Sheet 2.0", "UW sheet 1.0"]
_CADENCE_TO_MONTHLY = {"daily": 21.67, "weekly": 4.333}  # for any recompute need


def pick_tab(workbook) -> tuple[Any, str]:
    """Return (worksheet, tab_name) using the newest available UW Sheet tab."""
    for name in PREFERRED_TABS:
        if name in workbook.sheetnames:
            return workbook[name], name
    return workbook.active, workbook.active.title


# ── value coercion ───────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    """Money/number → float. Tolerates $, commas, %, blanks, #DIV/0!."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f
    s = str(v).strip()
    if not s or s.upper().startswith("#DIV") or s.upper() in ("N/A", "NA", "-"):
        return None
    s = re.sub(r"[\$,%\s]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _pct(v: Any) -> Optional[float]:
    """Leverage cell → percent number. Handles '32.90%' and 0.329 fractions."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f * 100.0 if -1.0 < f < 1.0 and f != 0 else f  # fraction → %
    n = _num(v)
    return n


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _is_yes(v: Any) -> bool:
    return _str(v) is not None and _str(v).strip().lower() in ("yes", "y", "true", "1")


# ── locating labels ────────────────────────────────────────────────────────

def _build_label_index(ws, max_row: int = 90, max_col: int = 30) -> dict[str, tuple[int, int]]:
    """First occurrence of each string label → (row, col)."""
    idx: dict[str, tuple[int, int]] = {}
    for row in ws.iter_rows(min_row=1, max_row=min(max_row, ws.max_row or max_row), max_col=max_col):
        for c in row:
            if isinstance(c.value, str):
                t = c.value.strip()
                if t and t not in idx:
                    idx[t] = (c.row, c.column)
    return idx


def _right_of(ws, idx: dict, label: str) -> Any:
    """Value in the cell immediately right of `label` (the col-A/col-B form)."""
    if label not in idx:
        return None
    r, c = idx[label]
    return ws.cell(r, c + 1).value


# ── positions box ──────────────────────────────────────────────────────────

def is_active_position(p: dict[str, Any]) -> bool:
    """CC's funder rule (2026-06-30) in ONE place — a position that COUNTS toward
    the 2-4 position count and the <40% leverage cap. It must pay DAILY or WEEKLY
    (monthly lenders are not MCA positions), NOT be already Paid Off, and NOT be
    the "Breeze Advance" row (the new advance being offered, not an existing
    stack position). Imported by the parser AND the Telegram packet renderer so
    the rule can never drift between scoring and display."""
    return (
        p.get("cadence") in ("daily", "weekly")
        and not p.get("paid_off")
        and not p.get("is_breeze_advance")
    )


def _parse_positions(ws, idx: dict) -> list[dict[str, Any]]:
    """Read the positions box: one dict per funder row.
    {status, funder, cadence, payment, leverage_pct}. Stops at the Total row."""
    if "Funder" not in idx:
        return []
    hdr_row, funder_col = idx["Funder"]
    status_col = idx.get("Status", (hdr_row, funder_col - 1))[1]
    daily_col = idx.get("Daily", (hdr_row, funder_col + 1))[1]
    weekly_col = idx.get("Weekly", (hdr_row, funder_col + 2))[1]
    monthly_col = idx.get("Monthly", (hdr_row, funder_col + 3))[1]
    lev_col = idx.get("Leverage Per Funder", (hdr_row, funder_col + 4))[1]
    total_row = idx.get("Total", (None, None))[0]

    # trailing columns (Date Funded / Payoff Amount / Assumed End Date / Notes)
    # carry the "Paid Off" marker; scan a generous span right of Leverage.
    scan_to = lev_col + 8

    out: list[dict[str, Any]] = []
    r = hdr_row + 1
    last = (total_row - 1) if total_row else (hdr_row + 14)
    while r <= last and r <= (ws.max_row or last):
        funder = _str(ws.cell(r, funder_col).value)
        daily = _num(ws.cell(r, daily_col).value)
        weekly = _num(ws.cell(r, weekly_col).value)
        monthly = _num(ws.cell(r, monthly_col).value)
        lev = _pct(ws.cell(r, lev_col).value)
        # cadence by which payment column is populated (>0)
        if daily and daily > 0:
            cadence, payment = "daily", daily
        elif weekly and weekly > 0:
            cadence, payment = "weekly", weekly
        elif monthly and monthly > 0:
            cadence, payment = "monthly", monthly
        else:
            cadence, payment = None, None
        # "Paid Off" marker anywhere in the row's trailing cells.
        paid_off = False
        for cc in range(funder_col, min(scan_to, ws.max_column) + 1):
            cv = ws.cell(r, cc).value
            if isinstance(cv, str) and "paid off" in cv.lower():
                paid_off = True
                break
        if funder or cadence:
            out.append({
                "status": _str(ws.cell(r, status_col).value),
                "funder": funder,
                "cadence": cadence,
                "payment": payment,
                "leverage_pct": lev,
                "paid_off": paid_off,
                "is_breeze_advance": bool(funder and "breeze advance" in funder.lower()),
            })
        r += 1
    return out


# ── main ─────────────────────────────────────────────────────────────────

def parse_uw_sheet(workbook) -> dict[str, Any]:
    """Parse one UW Sheet workbook → canonical deal dict."""
    ws, tab = pick_tab(workbook)
    idx = _build_label_index(ws)

    # left block (label in col A → value in col B)
    iso_broker = _str(_right_of(ws, idx, "ISO Shop / Broker"))
    business = _str(_right_of(ws, idx, "Business Legal Name"))
    prev_sub_raw = _right_of(ws, idx, "Previously Submitted?")
    data_merge = _str(_right_of(ws, idx, "Data Merch Notes"))
    nyscef = _str(_right_of(ws, idx, "NYSCEF Notes"))
    tib = _str(_right_of(ws, idx, "TIB"))
    industry = _str(_right_of(ws, idx, "Industry"))
    state = _str(_right_of(ws, idx, "State"))
    first_position = _str(_right_of(ws, idx, "1st Position"))

    # revenue table: averages live on the "Average" row, under the
    # "True Revenue" and "Monthly Leverage" columns.
    true_rev_avg = monthly_lev_avg = None
    if "Average" in idx and "True Revenue" in idx:
        avg_row = idx["Average"][0]
        true_rev_avg = _num(ws.cell(avg_row, idx["True Revenue"][1]).value)
        if "Monthly Leverage" in idx:
            monthly_lev_avg = _pct(ws.cell(avg_row, idx["Monthly Leverage"][1]).value)

    # contact / entity (Jotform block) — best-effort, often partially filled
    owner_first = _str(_right_of(ws, idx, "Owner First Name"))
    owner_last = _str(_right_of(ws, idx, "Owner Last Name"))
    owner_name = " ".join(p for p in (owner_first, owner_last) if p) or None
    email = _str(_right_of(ws, idx, "Email"))
    phone = _str(_right_of(ws, idx, "Phone"))
    ein = _str(_right_of(ws, idx, "Federal Tax ID"))
    business_address = _str(_right_of(ws, idx, "Business Address"))

    positions = _parse_positions(ws, idx)

    # CC's rule: positions/leverage count DAILY + WEEKLY funders only (monthly
    # lenders are not MCA positions). ALSO exclude positions that are already
    # Paid Off (no longer an obligation) and the "Breeze Advance" row (that's
    # the NEW advance being offered, not an existing stack position). The
    # remainder is the active stack the 2-4 count + <40% leverage rules apply to.
    counted = [p for p in positions if is_active_position(p)]
    position_count = len(counted)
    counted_lev = [p["leverage_pct"] for p in counted if p.get("leverage_pct") is not None]
    leverage_pct = round(sum(counted_lev), 2) if counted_lev else (0.0 if not counted else None)

    return {
        "tab": tab,
        "iso_broker": iso_broker,
        "business_legal_name": business,
        "previously_submitted": _is_yes(prev_sub_raw),
        "previously_submitted_raw": _str(prev_sub_raw),
        "data_merge_notes": data_merge,
        "nyscef_notes": nyscef,
        "tib": tib,
        "industry": industry,
        "state": state,
        "first_position": first_position,
        "owner_name": owner_name,
        "email": email,
        "phone": phone,
        "ein": ein,
        "business_address": business_address,
        "true_revenue_monthly": true_rev_avg,      # avg monthly True Revenue (col H)
        "sheet_monthly_leverage": monthly_lev_avg,  # the sheet's own avg (incl. monthly funders)
        "positions": positions,
        "counted_funders": counted,                 # daily/weekly only
        "position_count": position_count,           # daily/weekly count (the 2-4 rule)
        "leverage_pct": leverage_pct,               # sum of daily/weekly funder leverage (the <40% rule)
    }
