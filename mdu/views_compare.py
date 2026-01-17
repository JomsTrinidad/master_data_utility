import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import MDUHeader, ChangeRequest


def _rows(payload_json: str):
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _header_row(rows):
    return next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}


def _build_cols(left_rows, right_rows):
    a_hdr = _header_row(left_rows)
    b_hdr = _header_row(right_rows)
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]

    def used(col):
        if (a_hdr.get(col) or "").strip() or (b_hdr.get(col) or "").strip():
            return True
        for r in left_rows + right_rows:
            if (r.get(col) or "").strip():
                return True
        return False

    cols = []
    for col in string_cols:
        if not used(col):
            continue
        biz = (a_hdr.get(col) or "").strip() or (b_hdr.get(col) or "").strip() or col
        cols.append({"tech": col, "biz": biz})
    return cols

@login_required
def compare_versions(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)

    # Approved changes with numeric versions
					  
    approved = header.changes.filter(status=ChangeRequest.Status.APPROVED).exclude(version__isnull=True).order_by("-version")
						
    v1 = request.GET.get("v1")
    v2 = request.GET.get("v2")

    left = right = None
    left_rows = right_rows = []
    biz_cols = []
    diff_rows = []

    if left and right:
        lv = [r for r in left_rows if (r.get("row_type") or "").lower() != "header"]
        rv = [r for r in right_rows if (r.get("row_type") or "").lower() != "header"]

        max_len = max(len(lv), len(rv))
        for i in range(max_len):
            a = lv[i] if i < len(lv) else {}
            b = rv[i] if i < len(rv) else {}

            cells = []
            row_changed = False

            for col in biz_cols:
                tech = col["tech"]
                av = (a.get(tech) or "").strip()
                bv = (b.get(tech) or "").strip()
                changed = av != bv

                if changed:
                    row_changed = True

                cells.append({
                    "before": av,
                    "after": bv,
                    "changed": changed,
                })

            diff_rows.append({
                "key": f"row:{i+1}",
                "cells": cells,
                "row_changed": row_changed,   # ✅ precomputed
            })


@login_required
def compare_modal(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)

    approved = (
        header.changes
        .filter(status=ChangeRequest.Status.APPROVED)
        .exclude(version__isnull=True)
        .order_by("-version")
    )

    latest_version = approved.first().version if approved.exists() else None

    # Default: LEFT = latest approved version
    v_left = request.GET.get("left")
    v_right = request.GET.get("right")

    if not v_left and latest_version is not None:
        v_left = str(latest_version)

    left = approved.filter(version=int(v_left)).first() if v_left else None
    right = approved.filter(version=int(v_right)).first() if v_right else None

    left_rows = _rows(left.payload_json) if left else []
    right_rows = _rows(right.payload_json) if right else []

    biz_cols = _build_cols(left_rows, right_rows) if (left and right) else []
    diff_rows = []

    if left and right:
        lv = [r for r in left_rows if (r.get("row_type") or "").lower() != "header"]
        rv = [r for r in right_rows if (r.get("row_type") or "").lower() != "header"]

        max_len = max(len(lv), len(rv))
        for i in range(max_len):
            a = lv[i] if i < len(lv) else {}
            b = rv[i] if i < len(rv) else {}
            cells = []
            for col in biz_cols:
                tech = col["tech"]
                av = (a.get(tech) or "").strip()
                bv = (b.get(tech) or "").strip()
                cells.append({"before": av, "after": bv, "changed": av != bv})
            diff_rows.append({"key": f"row:{i+1}", "cells": cells})

    return render(
        request,
        "mdu/partials/compare_modal.html",
        {
            "header": header,
            "approved": approved,
            "latest_version": latest_version,
            "left": left,
            "right": right,
            "biz_cols": biz_cols,
            "diff_rows": diff_rows,
        },
    )
