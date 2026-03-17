import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

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


def _revision_label(ch):
    """
    Human-readable revision label: 'v1 · PC-2026-001'
    Used in dropdowns and comparison headings.
    """
    ver = f"v{ch.version}" if ch.version is not None else "v—"
    return f"{ver} · {ch.display_id}"


def _build_diff(left, right):
    """Build biz_cols and diff_rows for any two approved CRs."""
    left_rows  = _rows(left.payload_json)  if left  else []
    right_rows = _rows(right.payload_json) if right else []
    biz_cols   = _build_cols(left_rows, right_rows) if (left and right) else []
    diff_rows  = []

    if left and right:
        lv = [r for r in left_rows  if (r.get("row_type") or "").lower() != "header"]
        rv = [r for r in right_rows if (r.get("row_type") or "").lower() != "header"]
        for i in range(max(len(lv), len(rv))):
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
                cells.append({"before": av, "after": bv, "changed": changed})
            diff_rows.append({"key": f"row:{i+1}", "cells": cells, "row_changed": row_changed})

    return biz_cols, diff_rows


@login_required
def compare_versions(request, pk):
    header   = get_object_or_404(MDUHeader, pk=pk)
    # All approved CRs — any two can be compared regardless of version number
    approved = (
        header.changes
        .filter(status=ChangeRequest.Status.APPROVED)
        .order_by("-created_at")
    )

    left_pk  = request.GET.get("v1")
    right_pk = request.GET.get("v2")
    left  = approved.filter(pk=int(left_pk)).first()  if left_pk  else None
    right = approved.filter(pk=int(right_pk)).first() if right_pk else None

    biz_cols, diff_rows = _build_diff(left, right)

    return render(
        request,
        "mdu/compare_versions.html",
        {
            "header":    header,
            "approved":  approved,
            "left":      left,
            "right":     right,
            "biz_cols":  biz_cols,
            "diff_rows": diff_rows,
            "breadcrumbs": [
                {"label": "Catalog",             "url": reverse("mdu:catalog")},
                {"label": header.ref_name,       "url": reverse("mdu:header_detail", kwargs={"pk": header.pk})},
                {"label": "Compare Revisions",   "url": None},
            ],
        },
    )


@login_required
def compare_modal(request, pk):
    header   = get_object_or_404(MDUHeader, pk=pk)
    approved = (
        header.changes
        .filter(status=ChangeRequest.Status.APPROVED)
        .order_by("-created_at")
    )

    # Default left = most recent approved CR
    left_pk  = request.GET.get("left")
    right_pk = request.GET.get("right")

    if not left_pk and approved.exists():
        left_pk = str(approved.first().pk)

    left  = approved.filter(pk=int(left_pk)).first()  if left_pk  else None
    right = approved.filter(pk=int(right_pk)).first() if right_pk else None

    biz_cols, diff_rows = _build_diff(left, right)
    changed_count = sum(1 for r in diff_rows if r.get("row_changed"))

    return render(
        request,
        "mdu/partials/compare_modal.html",
        {
            "header":        header,
            "approved":      approved,
            "left":          left,
            "right":         right,
            "biz_cols":      biz_cols,
            "diff_rows":     diff_rows,
            "changed_count": changed_count,
        },
    )