import csv
import json
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from .models import MDUHeader

STRING_COLS = [f"string_{i:02d}" for i in range(1, 66)]
ALLOWED_COLS = set(STRING_COLS)


def _approved_rows(header: MDUHeader) -> list[dict[str, Any]]:
    latest = getattr(header, "last_approved_change", None)
    if not latest:
        return []

    try:
        payload = json.loads(latest.payload_json or "{}")
    except Exception:
        return []

    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
    return out


def _header_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in rows:
        if (r.get("row_type") or "").lower() == "header":
            return r
    return rows[0] if rows else None


def compute_visible_cols(rows: list[dict[str, Any]]) -> list[str]:
    """
    Visible columns = string_XX columns that have a non-empty label in the header row.
    Matches your Approved Data table.
    """
    hdr = _header_row(rows)
    if not hdr:
        return []

    visible: list[str] = []
    for c in STRING_COLS:
        v = hdr.get(c, "")
        if isinstance(v, str):
            v = v.strip()
        if v:
            visible.append(c)
    return visible


def compute_col_labels(rows: list[dict[str, Any]]) -> dict[str, str]:
    """
    Map string_XX -> business label (from the header row), used in table header.
    """
    hdr = _header_row(rows) or {}
    labels: dict[str, str] = {}
    for c in STRING_COLS:
        v = hdr.get(c, "")
        if isinstance(v, str):
            v = v.strip()
        labels[c] = v or ""
    return labels


def parse_cols_param(request, fallback_cols: list[str]) -> list[str]:
    """
    Optional: ?cols=string_01,string_02
    We only allow columns that are:
    - valid string_XX, AND
    - visible on the table (fallback_cols)
    """
    raw = (request.GET.get("cols") or "").strip()
    if not raw:
        return fallback_cols

    requested = [c.strip() for c in raw.split(",") if c.strip()]
    filtered = [c for c in requested if c in ALLOWED_COLS]
    visible_set = set(fallback_cols)
    filtered = [c for c in filtered if c in visible_set]
    return filtered or fallback_cols


def table_export_fieldnames(header: MDUHeader, visible_cols: list[str], col_labels: dict[str, str]) -> list[str]:
    """
    CSV headers match the table's *meta columns*, but business columns export as raw string_XX only.
    Example: UI may show "Country Code [string_01]" but CSV will export "string_01".
    """
    cols = ["ref_name", "row_type", "mode"]

    if getattr(header, "mode", None) != "snapshot":
        cols += ["start_date", "end_date"]

    cols += ["current_version"]

    # Business fields: export raw string_XX only
    cols.extend(visible_cols)

    return cols



def row_to_table_dict(
    header: MDUHeader,
    r: dict[str, Any],
    latest_version: int | None,
    visible_cols: list[str],
    col_labels: dict[str, str],  # kept for signature consistency, not used
) -> dict[str, Any]:
    """
    Builds a row dict that matches the CSV export:
    - Meta columns exactly as shown in the table
    - Business columns exported as raw string_XX only
    """
    out: dict[str, Any] = {
        "ref_name": header.ref_name,
        "row_type": r.get("row_type", ""),
        "mode": getattr(header, "mode", "") or "",
    }

    if getattr(header, "mode", None) != "snapshot":
        out["start_date"] = r.get("start_dt", "") or ""
        out["end_date"] = r.get("end_dt", "") or ""

    out["current_version"] = latest_version if latest_version is not None else ""

    # Business fields: always export raw string_XX
    for c in visible_cols:
        out[c] = r.get(c, "")

    return out


@login_required
def approved_export_csv(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)
    rows = _approved_rows(header)

    latest = getattr(header, "last_approved_change", None)
    latest_version = getattr(latest, "version", None) if latest else None

    visible_cols = compute_visible_cols(rows)
    visible_cols = parse_cols_param(request, visible_cols)  # optional subset, still “visible”
    col_labels = compute_col_labels(rows)

    fieldnames = table_export_fieldnames(header, visible_cols, col_labels)

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{header.ref_name}_approved.csv"'

    writer = csv.DictWriter(resp, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for r in rows:
        writer.writerow(row_to_table_dict(header, r, latest_version, visible_cols, col_labels))

    return resp


@login_required
def approved_export_json(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)
    rows = _approved_rows(header)

    latest = getattr(header, "last_approved_change", None)
    latest_version = getattr(latest, "version", None) if latest else None

    visible_cols = compute_visible_cols(rows)
    visible_cols = parse_cols_param(request, visible_cols)
    col_labels = compute_col_labels(rows)

    # JSON export mirrors the table too, but keeps a structured shape.
    out_rows = []
    for r in rows:
        row_obj = {
            "ref_name": header.ref_name,
            "row_type": r.get("row_type", ""),
            "mode": getattr(header, "mode", "") or "",
            "current_version": latest_version,
        }
        if getattr(header, "mode", None) != "snapshot":
            row_obj["start_date"] = r.get("start_dt", "") or ""
            row_obj["end_date"] = r.get("end_dt", "") or ""

        # business fields (only visible ones)
        row_obj["fields"] = {c: r.get(c, "") for c in visible_cols}
        out_rows.append(row_obj)

    return JsonResponse(
        {
            "ref_name": header.ref_name,
            "ref_type": header.ref_type,
            "mode": getattr(header, "mode", None),
            "current_version": latest_version,
            "visible_cols": visible_cols,
            "col_labels": {c: (col_labels.get(c) or "") for c in visible_cols},
            "rows": out_rows,
        },
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )
