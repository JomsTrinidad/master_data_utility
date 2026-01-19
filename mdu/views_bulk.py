import csv
import io
import json
import re

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

from .models import MDUHeader, ChangeRequest
from .services import payload_rows


def _safe_rows(payload_json: str):
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _header_row_from_payload(rows):
    return next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}


def _visible_cols_from_payload(rows):
    header_row = _header_row_from_payload(rows)
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    return [c for c in string_cols if (header_row.get(c) or "").strip()]


def _col_labels_from_payload(rows, visible_cols):
    header_row = _header_row_from_payload(rows)
    labels = {}
    for c in visible_cols:
        labels[c] = (header_row.get(c) or "").strip()
    return labels


_HEADER_RE = re.compile(r"^(string_\d{2})\b", re.IGNORECASE)


def _normalize_csv_headers(fieldnames):
    """
    Supports:
      - string_01
      - string_01 (Country Code)
      - string_01 - Country Code
    Returns:
      display_to_tech, tech_names_in_file
    """
    display_to_tech = {}
    tech_names = []

    for h in fieldnames:
        if not h:
            continue
        s = str(h).strip()
        m = _HEADER_RE.match(s)
        if not m:
            continue
        tech = m.group(1).lower()
        display_to_tech[s] = tech
        tech_names.append(tech)

    return display_to_tech, tech_names


def download_bulk_template_csv(request, header_pk):
    """
    CSV template for bulk insert. Header uses technical names plus human hints:
      string_01 (Country Code)
      string_02 (Description)
    """
    header = get_object_or_404(MDUHeader, pk=header_pk)

    latest = header.last_approved_change
    rows = payload_rows(latest.payload_json) if latest and latest.payload_json else []
    visible_cols = _visible_cols_from_payload(rows)

    if not visible_cols:
        visible_cols = ["string_01", "string_02", "string_03"]

    labels = _col_labels_from_payload(rows, visible_cols)

    out_headers = []
    for c in visible_cols:
        lbl = (labels.get(c) or "").strip()
        if lbl:
            out_headers.append(f"{c} ({lbl})")
        else:
            out_headers.append(c)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(out_headers)

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{header.ref_name}_bulk_insert_template.csv"'
    return resp


def bulk_upload_csv(request, pk):
    """
    Legacy endpoint (kept for deep links): append INSERT rows from uploaded CSV into a DRAFT.
    Supports hinted headers like 'string_01 (Country Code)'.
    """
    ch = get_object_or_404(ChangeRequest, pk=pk)

    if ch.status != ChangeRequest.Status.DRAFT:
        messages.error(request, "Bulk Upload Is Only Allowed For Draft Changes.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    f = request.FILES.get("bulk_csv")
    if not f:
        messages.error(request, "Please Choose A CSV File To Upload.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    try:
        text = f.read().decode("utf-8-sig")
    except Exception:
        messages.error(request, "Could Not Read CSV File. Please Upload A UTF-8 CSV.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    current_rows = _safe_rows(ch.payload_json)
    visible_cols = _visible_cols_from_payload(current_rows)

    if not visible_cols:
        messages.error(request, "Cannot Determine Visible Business Columns (Missing Header Row).")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    display_to_tech, tech_in_file = _normalize_csv_headers(fieldnames)

    extra = [t for t in tech_in_file if t.startswith("string_") and t not in visible_cols]
    if extra:
        messages.error(
            request,
            "Upload Blocked. Your File Contains Columns Not Supported By This Reference: "
            + ", ".join(extra)
            + ". Download The Template Again And Do Not Add Extra Columns."
        )
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    overlap = [c for c in visible_cols if c in tech_in_file]
    if not overlap:
        messages.error(request, "CSV Headers Do Not Match The Expected Template. Please Download The Template And Fill That In.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    try:
        obj = json.loads(ch.payload_json or "{}")
    except Exception:
        obj = {}

    rows_list = obj.get("rows", [])
    if not isinstance(rows_list, list):
        rows_list = []

    added = 0
    for row in reader:
        new_row = {"row_type": "values", "operation": "INSERT", "update_rowid": ""}

        for c in visible_cols:
            # Find which display header maps to this tech col
            v = ""
            for display_h, tech in display_to_tech.items():
                if tech == c:
                    v = row.get(display_h, "")
                    break
            if v is None:
                v = ""
            new_row[c] = str(v).strip()

        if all((new_row.get(c) or "") == "" for c in visible_cols):
            continue

        rows_list.append(new_row)
        added += 1

    if added == 0:
        messages.warning(request, "No Rows Were Added (CSV Had No Non-Empty Rows).")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    obj["rows"] = rows_list
    ch.payload_json = json.dumps(obj, indent=2)
    ch.bulk_add_count = ch.bulk_add_count + 1
    ch.updated_at = timezone.now()
    ch.save(update_fields=["payload_json", "bulk_add_count", "updated_at"])

    messages.success(request, f"Bulk Insert Added {added} Rows.")
    return redirect("mdu:proposed_change_edit", pk=ch.pk)
