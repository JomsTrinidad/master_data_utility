import csv
import io
import json

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


def _visible_cols_from_payload(rows):
    header_row = next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    return [c for c in string_cols if (header_row.get(c) or "").strip()]


def download_bulk_template_csv(request, header_pk):
    """
    CSV template for bulk insert.
    Columns match the propose-change table's visible business columns (string_XX).
    """
    header = get_object_or_404(MDUHeader, pk=header_pk)

    latest = header.last_approved_change
    rows = payload_rows(latest.payload_json) if latest and latest.payload_json else []
    visible_cols = _visible_cols_from_payload(rows)

    if not visible_cols:
        # fallback: include first 3
        visible_cols = ["string_01", "string_02", "string_03"]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(visible_cols)

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{header.ref_name}_bulk_insert_template.csv"'
    return resp


def bulk_upload_csv(request, pk):
    """
    Append INSERT rows from uploaded CSV into an existing DRAFT ChangeRequest.

    NOTE: This endpoint is optional. The primary UX uses the Propose Change form's
    "Populate table" action, but keeping this route ensures deep links or older
    bookmarks still work.
    """
    ch = get_object_or_404(ChangeRequest, pk=pk)

    if ch.status != ChangeRequest.Status.DRAFT:
        messages.error(request, "Bulk upload is only allowed for draft changes.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    f = request.FILES.get("bulk_csv")
    if not f:
        messages.error(request, "Please choose a CSV file to upload.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    try:
        text = f.read().decode("utf-8-sig")
    except Exception:
        messages.error(request, "Could not read CSV file. Please upload a UTF-8 CSV.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    try:
        obj = json.loads(ch.payload_json or "{}")
    except Exception:
        obj = {}

    rows_list = obj.get("rows", [])
    if not isinstance(rows_list, list):
        rows_list = []

    current_rows = _safe_rows(ch.payload_json)
    visible_cols = _visible_cols_from_payload(current_rows)

    if not visible_cols:
        messages.error(request, "Cannot determine visible business columns (missing header row).")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    extra = [c for c in fieldnames if c and c.startswith("string_") and c not in visible_cols]
    if extra:
        messages.error(
            request,
            "Upload blocked. Your file contains columns not supported by this reference: "
            + ", ".join(extra)
            + ". Download the template again and do not add extra columns."
        )
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    overlap = [c for c in visible_cols if c in fieldnames]
    if not overlap:
        messages.error(request, "CSV headers do not match the expected template. Please download the template and fill that in.")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    added = 0
    for row in reader:
        new_row = {"row_type": "values", "operation": "INSERT", "update_rowid": ""}

        for c in visible_cols:
            v = row.get(c, "")
            if v is None:
                v = ""
            new_row[c] = str(v).strip()

        if all((new_row.get(c) or "") == "" for c in visible_cols):
            continue

        rows_list.append(new_row)
        added += 1

    if added == 0:
        messages.warning(request, "No rows were added (CSV had no non-empty rows).")
        return redirect("mdu:proposed_change_edit", pk=ch.pk)

    obj["rows"] = rows_list
    ch.payload_json = json.dumps(obj, indent=2)

    # Keep count for audit/telemetry, but no artificial limits.
    ch.bulk_add_count = ch.bulk_add_count + 1
    ch.updated_at = timezone.now()
    ch.save(update_fields=["payload_json", "bulk_add_count", "updated_at"])

    messages.success(request, f"Bulk insert added {added} rows.")
    return redirect("mdu:proposed_change_edit", pk=ch.pk)
