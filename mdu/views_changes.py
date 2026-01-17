import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import ChangeRequest


def _rows_from_payload(payload_json: str):
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _header_row(rows):
    return next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}


def _is_values_row(r):
    return (r.get("row_type") or "").lower() != "header"


def _build_biz_cols(before_rows, after_rows):
    """
    Decide which string_XX columns to show and what business label to display.
    Prefer AFTER header labels, fall back to BEFORE.
    """
    after_hdr = _header_row(after_rows)
    before_hdr = _header_row(before_rows)

    string_cols = [f"string_{i:02d}" for i in range(1, 66)]

    def used(col):
        # include if header has label OR any values row uses it (before/after)
        if (after_hdr.get(col) or "").strip() or (before_hdr.get(col) or "").strip():
            return True
        for r in after_rows:
            if (r.get(col) or "").strip():
                return True
        for r in before_rows:
            if (r.get(col) or "").strip():
                return True
        return False

    cols = []
    for col in string_cols:
        if not used(col):
            continue
        biz = (after_hdr.get(col) or "").strip() or (before_hdr.get(col) or "").strip() or col
        cols.append({"tech": col, "biz": biz})
    return cols


def _row_key(row, idx):
    """
    Prefer update_rowid when present (great for UPDATE ROW(S)).
    Otherwise fall back to a stable index-based label.
    """
    u = (row.get("update_rowid") or "").strip()
    if u:
        return f"update:{u}"
    return f"row:{idx+1}"


@login_required
def change_modal(request, pk):
    change = get_object_or_404(ChangeRequest, pk=pk)
    header = change.header

    after_rows = _rows_from_payload(change.payload_json)

    before_rows = []
    latest = getattr(header, "last_approved_change", None)
    if latest and latest.pk != change.pk:
        before_rows = _rows_from_payload(latest.payload_json)

    # biz columns for display
    biz_cols = _build_biz_cols(before_rows, after_rows)

    before_vals = [r for r in before_rows if isinstance(r, dict) and _is_values_row(r)]
    after_vals = [r for r in after_rows if isinstance(r, dict) and _is_values_row(r)]

    max_len = max(len(before_vals), len(after_vals))
    diff_rows = []

    for i in range(max_len):
        b = before_vals[i] if i < len(before_vals) else {}
        a = after_vals[i] if i < len(after_vals) else {}
        key = _row_key(a or b, i)

        cells = []
        for col in biz_cols:
            tech = col["tech"]
            bv = (b.get(tech) or "").strip()
            av = (a.get(tech) or "").strip()
            cells.append({"before": bv, "after": av, "changed": bv != av})

        diff_rows.append({"key": key, "cells": cells})

    return render(
        request,
        "mdu/partials/change_modal.html",
        {
            "change": change,
            "header": header,
            "before_rows": before_rows,
            "proposed_rows": after_rows,
            "biz_cols": biz_cols,
            "diff_rows": diff_rows,
        },
    )
