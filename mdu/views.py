import json, os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import FileResponse, Http404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from datetime import timedelta
from django_tables2 import RequestConfig
from datetime import date

from .models import MDUHeader, ChangeRequest, MDUCert
from .filters import HeaderFilter, ProposedChangeFilter
from .tables import HeaderTable, ProposedChangeTable, CertTable
from .forms import ProposedChangeForm, CertForm, HeaderForm
from .permissions import group_required, in_group
from .services import payload_rows, derive_business_columns, generate_loader_artifacts
from django.db.models import Exists, OuterRef
from django.urls import reverse
from .validators import validate_change_request_payload, validate_update_rowids_against_latest_hash
from .validators import validate_update_rowids_against_latest


def _crumb(label, url=None):
    return {"label": label, "url": url}

def _role_flags(user):
    return {
        "is_maker": in_group(user, "maker"),
        "is_steward": in_group(user, "steward"),
        "is_approver": in_group(user, "approver"),
    }

@login_required
def catalog(request):
    qs = MDUHeader.objects.all().order_by("ref_name")

    pending_submitted = ChangeRequest.objects.filter(
        header_id=OuterRef("pk"),
        status="SUBMITTED",
    )
    qs = qs.annotate(has_pending=Exists(pending_submitted))

    # UX default: show Active only, unless user explicitly asks to include other statuses
    include_all = request.GET.get("include_all") in ("1", "true", "True", "on")
    has_status_filter = bool(request.GET.get("status"))

    if not include_all and not has_status_filter:
        qs = qs.filter(status=MDUHeader.Status.ACTIVE)

    f = HeaderFilter(request.GET, queryset=qs)

    table = HeaderTable(f.qs)
    RequestConfig(request, paginate={"per_page": 15}).configure(table)

    return render(
        request,
        "mdu/catalog.html",
        {"filter": f, "table": table, 
         "breadcrumbs": [{"label": "Catalog", "url": None},],
         **_role_flags(request.user)},
    )


@group_required("steward", "approver")
def header_create(request):
    if request.method == "POST":
        form = HeaderForm(request.POST)
        if form.is_valid():
            header = form.save()
            messages.success(request, "Reference created.")
            return redirect("mdu:header_detail", pk=header.pk)
    else:
        form = HeaderForm()

    return render(request, "mdu/header_form.html", {
        "form": form,
        "mode": "create",
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb("New reference", None),
        ],
        **_role_flags(request.user),
    })


@group_required("steward", "approver")
def header_edit(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)

    if request.method == "POST":
        form = HeaderForm(request.POST, instance=header)
        if form.is_valid():
            form.save()
            messages.success(request, "Reference updated.")
            return redirect("mdu:header_detail", pk=header.pk)
    else:
        form = HeaderForm(instance=header)

    return render(request, "mdu/header_form.html", {
        "form": form,
        "header": header,
        "mode": "edit",
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb(header.ref_name, reverse("mdu:header_detail", kwargs={"pk": header.pk})),
            _crumb("Edit reference", None),
        ],
        **_role_flags(request.user),
    })



@login_required
def header_detail(request, pk):
    header = get_object_or_404(MDUHeader, pk=pk)

    latest = header.last_approved_change
    current_version = latest.version if (latest and latest.version is not None) else None

    # Approved data (full dataset)
    all_rows = _safe_rows(latest.payload_json) if latest else []
    data_rows = all_rows

    # Business labels for string_01..65 from the header row
    header_row = next((r for r in all_rows if (r.get("row_type") or "").lower() == "header"), {}) or {}
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]

    # Visible columns should match what the user sees:
    # only columns with a non-empty business label in the header row.
    def has_label(col: str) -> bool:
        return bool((header_row.get(col) or "").strip())

    visible_cols = [c for c in string_cols if has_label(c)]

    # Column labels used by the table header
    col_labels = {c: ((header_row.get(c) or "").strip() or c) for c in visible_cols}

    # For export links (CSV/JSON): pass visible columns as a query param
    export_cols_csv = ",".join(visible_cols)

    # Change history
    changes = header.changes.all().order_by("-created_at")

    # Certifications
    certs = header.certs.all().order_by("-cert_expiry_dttm", "-created_at")
    latest_cert = certs.first() if certs.exists() else None

    cert_badge = None
    if latest_cert and getattr(latest_cert, "cert_expiry_dttm", None):
        now = timezone.now()
        if latest_cert.cert_expiry_dttm < now:
            cert_badge = "overdue"
        elif latest_cert.cert_expiry_dttm <= (now + timedelta(days=30)):
            cert_badge = "soon"
        else:
            cert_badge = "ok"

    pending_change = (
        header.changes
        .filter(status=ChangeRequest.Status.SUBMITTED)
        .order_by("-submitted_at", "-created_at")
        .first()
    )

    # Derived certification labels for the UI (templates stay dumb)
    today = timezone.localdate()
    cert_state = "none"
    cert_badge_class = "secondary"
    cert_label = "Not certified"
    cert_expires_on = None
    cert_certified_on = None
    cert_version = None

    if latest_cert:
        # Your model uses cert_expiry_dttm (datetime). We'll derive a date for display/logic.
        expiry_dt = getattr(latest_cert, "cert_expiry_dttm", None)
        cert_expires_on = expiry_dt.date() if expiry_dt else None

        # If your model has these fields, they'll be picked up; otherwise remain None.
        cert_certified_on = getattr(latest_cert, "certified_on", None)
        cert_version = getattr(latest_cert, "cert_version", None)

        if cert_expires_on:
            days_left = (cert_expires_on - today).days
            if days_left < 0:
                cert_state = "expired"
                cert_badge_class = "danger"
                cert_label = "Expired"
            elif days_left <= 30:
                cert_state = "expiring"
                cert_badge_class = "warning"
                cert_label = "Expiring soon"
            else:
                cert_state = "valid"
                cert_badge_class = "success"
                cert_label = "Certified"
        else:
            cert_state = "valid"
            cert_badge_class = "success"
            cert_label = "Certified"

    return render(
        request,
        "mdu/header_detail.html",
        {
            "header": header,
            "breadcrumbs": [
                _crumb("Catalog", reverse("mdu:catalog")),
                _crumb(header.ref_name, None),
            ],
            "latest": latest,
            "current_version": current_version,
            "data_rows": data_rows,
            "visible_cols": visible_cols,
            "col_labels": col_labels,
            "export_cols_csv": export_cols_csv,  # <-- use this in Export CSV/JSON links
            "changes": changes,
            "certs": certs,
            "latest_cert": latest_cert,
            "cert_badge": cert_badge,
            "pending_change": pending_change,
            "cert_state": cert_state,
            "cert_badge_class": cert_badge_class,
            "cert_label": cert_label,
            "cert_expires_on": cert_expires_on,
            "cert_certified_on": cert_certified_on,
            "cert_version": cert_version,
            **_role_flags(request.user),
        },
    )


@group_required("maker", "steward", "approver")
def proposed_change_list(request):
    qs = ChangeRequest.objects.select_related("header").order_by("-created_at")
    f = ProposedChangeFilter(request.GET, queryset=qs)
    table = ProposedChangeTable(f.qs)
    RequestConfig(request, paginate={"per_page": 15}).configure(table)
    return render(request, "mdu/proposed_change_list.html", {
        "filter": f,
        "table": table,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb("Proposed Changes", None),
        ],
        **_role_flags(request.user)
    })


def _next_display_id():
    year = timezone.now().strftime("%Y")
    prefix = f"PC-{year}-"
    last = ChangeRequest.objects.filter(display_id__startswith=prefix).order_by("-display_id").first()
    n = 1
    if last:
        try:
            n = int(last.display_id.split("-")[-1]) + 1
        except Exception:
            n = 1
    return f"{prefix}{n:04d}"


def _suggest_tracking_id():
    stamp = timezone.now().strftime("%Y%m%d")
    n = ChangeRequest.objects.filter(created_at__date=timezone.now().date()).count() + 1
    return f"SES{stamp}-REQ{n:06d}"


def compute_dirty_cells(baseline_payload_json: str, current_payload_json: str):
    """
    Returns a dict like {"3:string_01": True, "5:string_02": True}
    where the key format matches the row_index used in the template naming:
      name="cell__<row_index>__string_XX"

    We compare row-by-row by index (including the header row index),
    and only mark VALUES rows and only business fields string_01..string_65.
    """
    dirty = {}

    base_rows = _safe_rows(baseline_payload_json)
    cur_rows = _safe_rows(current_payload_json)

    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    n = min(len(base_rows), len(cur_rows))

    for idx in range(n):
        b = base_rows[idx] if isinstance(base_rows[idx], dict) else {}
        c = cur_rows[idx] if isinstance(cur_rows[idx], dict) else {}

        # Only track dirty business cells on VALUES rows
        if (c.get("row_type") or "").lower() != "values":
            continue

        for col in string_cols:
            bv = (b.get(col) or "")
            cv = (c.get(col) or "")
            if str(bv).strip() != str(cv).strip():
                dirty[f"{idx}:{col}"] = True

    return dirty

def _lock_meta_fields_for_maker(post, *, user, existing: ChangeRequest | None = None):
    """Enforce 'makers can't edit governance metadata' without breaking POST.

    - requested_by_sid: always auto-filled from the logged-in user for makers
    - other governance fields: pinned to existing values (edit) or blank (create)
    """
    if not in_group(user, "maker"):
        return
    if in_group(user, "steward") or in_group(user, "approver"):
        return

    # Always pin requested_by_sid to the logged-in maker
    post["requested_by_sid"] = (getattr(user, "username", "") or "").strip()

    lock_to_existing = ["version", "primary_approver_sid", "secondary_approver_sid"]
    for f in lock_to_existing:
        post[f] = getattr(existing, f, "") if existing else ""



@group_required("maker")
def propose_change(request, header_pk):
    header = get_object_or_404(MDUHeader, pk=header_pk)

    # Prevent conflicts: only one SUBMITTED change at a time
    if header.changes.filter(status=ChangeRequest.Status.SUBMITTED).exists():
        messages.error(
            request,
            "A pending change already exists for this reference. Please wait for approval/rejection before proposing a new change."
        )
        return redirect("mdu:header_detail", pk=header.pk)

    if header.status == MDUHeader.Status.RETIRED:
        messages.warning(
            request,
            "This reference is retired. You can still propose a change, but it must be flagged as an override."
        )

    dirty_cells = {}
    baseline_payload_json = ""

    # ----------------------------
    # GET: initialize baseline + form
    # ----------------------------
    if request.method != "POST":
        if header.last_approved_change and header.last_approved_change.payload_json:
            initial_payload = header.last_approved_change.payload_json
        else:
            initial_payload = json.dumps({
                "rows": [
                    {
                        "row_type": "header",
                        "operation": "BUILD NEW",
                        "start_dt": "",
                        "end_dt": "",
                        "version": "",
                        "string_01": "BUS_FIELD_01",
                        "string_02": "BUS_FIELD_02",
                        "string_03": "BUS_FIELD_03",
                    }
                ]
            }, indent=2)

        baseline_payload_json = initial_payload

        form = ProposedChangeForm(initial={
            "tracking_id": _suggest_tracking_id(),
            "override_retired_flag": "N",
            "payload_json": initial_payload,
        })

        payload = initial_payload
        rows = payload_rows(payload)

    # ----------------------------
    # POST: bulk upload / insert row / save draft
    # ----------------------------
    else:
        post = request.POST.copy()

        # baseline comes from hidden input; fallback to current payload_json
        baseline_payload_json = post.get("baseline_payload_json", "") or post.get("payload_json", "")

        # Apply any edits from grid inputs into payload_json
        post["payload_json"] = _apply_cell_edits_to_payload_json(
            post.get("payload_json", ""),
            post
        )

        _lock_meta_fields_for_maker(post, user=request.user)

        action = post.get("action")  # only exists on POST

        # ----- Bulk upload (NO draft creation) -----
        if action == "bulk_upload":
            temp_rows = payload_rows(post.get("payload_json", ""))
            visible_cols_now = _visible_cols_from_rows(temp_rows)

            if not visible_cols_now:
                messages.error(request, "Cannot upload: header row does not define any business fields.")
                payload = post.get("payload_json", "")
                rows = temp_rows
                form = ProposedChangeForm(post)
                dirty_cells = compute_dirty_cells(baseline_payload_json, payload)

            else:
                new_payload, added, err = _append_csv_rows_as_inserts(
                    post.get("payload_json", ""),
                    request.FILES.get("bulk_csv"),
                    visible_cols_now
                )

                if err:
                    messages.error(request, err)
                else:
                    messages.success(request, f"Added {added} rows from CSV.")

                post["payload_json"] = new_payload
                payload = new_payload
                rows = payload_rows(payload)
                form = ProposedChangeForm(post)
                dirty_cells = compute_dirty_cells(baseline_payload_json, payload)

        # Insert new row (no save yet) -> re-render
        elif action == "add_row":
            try:
                obj = json.loads(post.get("payload_json", "") or "{}")
            except Exception:
                obj = {}

            rows_list = obj.get("rows", [])
            if not isinstance(rows_list, list):
                rows_list = []

            new_row = {"row_type": "values", "operation": "INSERT", "update_rowid": ""}
            for i in range(1, 66):
                new_row[f"string_{i:02d}"] = ""

            rows_list.append(new_row)
            obj["rows"] = rows_list
            post["payload_json"] = json.dumps(obj, indent=2)

            payload = post["payload_json"]
            rows = payload_rows(payload)
            form = ProposedChangeForm(post)
            dirty_cells = compute_dirty_cells(baseline_payload_json, payload)

        # Normal save draft path
        else:
            form = ProposedChangeForm(post)
            if form.is_valid():
                ch = form.save(commit=False)
                ch.header = header
                ch.display_id = _next_display_id()
                ch.created_by = request.user
                if not ch.tracking_id:
                    ch.tracking_id = _suggest_tracking_id()
                ch.save()
                messages.success(request, "Draft saved. Review the table, then submit when ready.")
                return redirect("mdu:proposed_change_detail", pk=ch.pk)

            # invalid form -> re-render with errors + preserve dirty
            payload = post.get("payload_json", "")
            rows = payload_rows(payload)
            dirty_cells = compute_dirty_cells(baseline_payload_json, payload)

    # ----------------------------
    # Shared column layout (match header_detail)
    # ----------------------------
    header_row = next(
        (r for r in (rows or []) if (r.get("row_type") or "").lower() == "header"),
        {}
    ) or {}

    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    visible_cols = [c for c in string_cols if (header_row.get(c) or "").strip()]
    col_labels = {c: ((header_row.get(c) or "").strip() or c) for c in visible_cols}

    return render(request, "mdu/proposed_change_form.html", {
        "header": header,
        "form": form,
        "rows": rows,
        "visible_cols": visible_cols,
        "col_labels": col_labels,
        "dirty_cells": dirty_cells,
        "baseline_payload_json": baseline_payload_json,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb(header.ref_name, reverse("mdu:header_detail", kwargs={"pk": header.pk})),
            _crumb("Propose Change", None),
        ],
        **_role_flags(request.user),
    })


@require_POST
@group_required("maker", "steward", "approver")
def proposed_change_discard(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)

    if ch.status != ChangeRequest.Status.DRAFT:
        messages.error(request, "Only Draft Changes Can Be Discarded.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    # Makers can discard only their own drafts. Stewards/Approvers can discard any draft.
    if in_group(request.user, "maker") and not (in_group(request.user, "steward") or in_group(request.user, "approver")):
        if ch.created_by_id and ch.created_by_id != request.user.id:
            messages.error(request, "You Can Only Discard Drafts You Created.")
            return redirect("mdu:proposed_change_detail", pk=ch.pk)

    header_pk = ch.header_id
    ch.delete()
    messages.success(request, "Draft Discarded.")
    return redirect("mdu:header_detail", pk=header_pk)


@group_required("maker", "steward", "approver")
def proposed_change_detail(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    rows = payload_rows(ch.payload_json)
    biz_cols = derive_business_columns(rows) if rows else []
    can_edit = (ch.status == ChangeRequest.Status.DRAFT) and in_group(request.user, "maker")
    can_decide = (ch.status == ChangeRequest.Status.SUBMITTED) and in_group(request.user, "approver")

    return render(request, "mdu/proposed_change_detail.html", {
        "ch": ch,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb("Proposed Changes", reverse("mdu:proposed_change_list")),
            _crumb(ch.display_id, None),
        ],
        "rows": rows,
        "biz_cols": biz_cols,
        "can_edit": can_edit,
        "can_decide": can_decide,
        **_role_flags(request.user)
    })
@group_required("maker")
def proposed_change_edit(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)

    if ch.status != ChangeRequest.Status.DRAFT:
        messages.error(request, "Only drafts can be edited.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    header = ch.header
    dirty_cells = {}
    baseline_payload_json = ""

    if request.method != "POST":
        baseline_payload_json = ch.payload_json or ""
        form = ProposedChangeForm(instance=ch)
        payload = baseline_payload_json
        rows = payload_rows(payload)

    else:
        post = request.POST.copy()

        baseline_payload_json = post.get("baseline_payload_json", "") or (ch.payload_json or "")

        post["payload_json"] = _apply_cell_edits_to_payload_json(
            post.get("payload_json", ""),
            post
        )

        _lock_meta_fields_for_maker(post, user=request.user, existing=ch)


        action = post.get("action")

        if action == "add_row":
            try:
                obj = json.loads(post.get("payload_json", "") or "{}")
            except Exception:
                obj = {}

            rows_list = obj.get("rows", [])
            if not isinstance(rows_list, list):
                rows_list = []

            new_row = {"row_type": "values", "operation": "INSERT", "update_rowid": ""}
            for i in range(1, 66):
                new_row[f"string_{i:02d}"] = ""

            rows_list.append(new_row)
            obj["rows"] = rows_list
            post["payload_json"] = json.dumps(obj, indent=2)

            dirty_cells = compute_dirty_cells(baseline_payload_json, post["payload_json"])

            form = ProposedChangeForm(post, instance=ch)
            payload = post["payload_json"]
            rows = payload_rows(payload)

        else:
            form = ProposedChangeForm(post, instance=ch)
            if form.is_valid():
                form.save()
                messages.success(request, "Draft updated.")
                return redirect("mdu:proposed_change_detail", pk=ch.pk)

            payload = post.get("payload_json", "")
            dirty_cells = compute_dirty_cells(baseline_payload_json, payload)
            rows = payload_rows(payload)

    header_row = next(
        (r for r in (rows or []) if (r.get("row_type") or "").lower() == "header"),
        {}
    ) or {}

    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    visible_cols = [c for c in string_cols if (header_row.get(c) or "").strip()]
    col_labels = {c: ((header_row.get(c) or "").strip() or c) for c in visible_cols}

    return render(request, "mdu/proposed_change_form.html", {
        "header": header,
        "form": form,
        "rows": rows,
        "visible_cols": visible_cols,
        "col_labels": col_labels,
        "dirty_cells": dirty_cells,
        "baseline_payload_json": baseline_payload_json,
        "editing": True,
        "ch": ch,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb(header.ref_name, reverse("mdu:header_detail", kwargs={"pk": header.pk})),
            _crumb(ch.display_id, reverse("mdu:proposed_change_detail", kwargs={"pk": ch.pk})),
            _crumb("Edit", None),
        ],
        **_role_flags(request.user),
    })



@group_required("maker")
@require_POST
def proposed_change_submit(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    if ch.status != ChangeRequest.Status.DRAFT:
        raise Http404()

    if not ch.tracking_id:
        ch.tracking_id = _suggest_tracking_id()

    if ch.header.status == MDUHeader.Status.RETIRED and ch.override_retired_flag != "Y":
        messages.error(request, "This reference is retired. To proceed, set 'Override retired' to Y.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    # Submit-time guard rails (aligned to loader)
    errors, warnings = validate_change_request_payload(header=ch.header, change_request=ch)

    e2, w2 = validate_update_rowids_against_latest(header=ch.header, change_request=ch)
    errors.extend(e2)
    warnings.extend(w2)

    for w in warnings:
        messages.warning(request, w)

    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect("mdu:proposed_change_detail", pk=ch.pk)


    ch.status = ChangeRequest.Status.SUBMITTED
    ch.submitted_at = timezone.now()
    ch.save(update_fields=["status", "submitted_at", "tracking_id", "updated_at"])
    messages.success(request, "Submitted for approval.")
    return redirect("mdu:proposed_change_detail", pk=ch.pk)


@group_required("approver")
@require_POST
def proposed_change_decide(request, pk, decision):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    if ch.status != ChangeRequest.Status.SUBMITTED:
        raise Http404()

    note = (request.POST.get("note") or "").strip()

    if decision == "approve":
        ch.status = ChangeRequest.Status.APPROVED
        ch.decided_at = timezone.now()
        ch.decision_note = note
        ch.save(update_fields=["status","decided_at","decision_note","updated_at"])

        header = ch.header
        header.last_approved_change = ch
        header.status = MDUHeader.Status.ACTIVE
        header.save(update_fields=["last_approved_change","status","updated_at"])
        messages.success(request, "Approved. You can now generate load files.")

    elif decision == "reject":
        ch.status = ChangeRequest.Status.REJECTED
        ch.decided_at = timezone.now()
        ch.decision_note = note
        ch.save(update_fields=["status","decided_at","decision_note","updated_at"])
        messages.info(request, "Rejected.")

    else:
        raise Http404()

    return redirect("mdu:proposed_change_detail", pk=ch.pk)


@group_required("approver")
def generate_load_files(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    if ch.status != ChangeRequest.Status.APPROVED:
        messages.error(request, "Only approved changes can generate load files.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    include_cert = request.GET.get("include_cert") == "1"
    zip_path = generate_loader_artifacts(ch.header, ch, include_cert=include_cert)
    return FileResponse(open(zip_path, "rb"), as_attachment=True, filename=os.path.basename(zip_path))


@group_required("maker", "steward", "approver")
def cert_list(request):
    qs = MDUCert.objects.select_related("header").order_by("-created_at")
    table = CertTable(qs)
    RequestConfig(request, paginate={"per_page": 15}).configure(table)
    return render(request, "mdu/cert_list.html", {
    "table": table,
    "breadcrumbs": [
        _crumb("Catalog", reverse("mdu:catalog")),
        _crumb("Certifications", None),
    ],
    **_role_flags(request.user)
    })


@group_required("steward", "approver")
def cert_create(request):
    if request.method == "POST":
        form = CertForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Certification saved.")
            return redirect("mdu:cert_list")
    else:
        form = CertForm()
    return render(request, "mdu/cert_form.html", {
    "form": form,
    "breadcrumbs": [
        _crumb("Catalog", reverse("mdu:catalog")),
        _crumb("Certifications", reverse("mdu:cert_list")),
        _crumb("New", None),
    ],
    **_role_flags(request.user)
    })


def _safe_rows(payload_json: str):
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _apply_cell_edits_to_payload_json(payload_json: str, post_data) -> str:
    """
    Takes existing payload_json and applies table cell edits from POST inputs:
    cell__<row_index>__<colname> = value
    Returns updated payload_json string.
    """
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}

    rows = obj.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # Apply edits
    for key, val in post_data.items():
        if not key.startswith("cell__"):
            continue
        try:
            _, idx_str, col = key.split("__", 2)
            idx = int(idx_str)
        except Exception:
            continue

        if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
            rows[idx][col] = val

    obj["rows"] = rows
    return json.dumps(obj, indent=2)

import csv, io  # add at top of file too

def _visible_cols_from_rows(rows):
    header_row = next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    return [c for c in string_cols if (header_row.get(c) or "").strip()]

def _append_csv_rows_as_inserts(payload_json: str, uploaded_file, visible_cols):
    """
    Reads CSV and appends VALUES rows as INSERT into payload_json.
    Blocks if CSV includes business columns outside visible_cols.
    Returns (new_payload_json, added_count, error_msg)
    """
    if not uploaded_file:
        return payload_json, 0, "Please choose a CSV file to upload."

    try:
        text = uploaded_file.read().decode("utf-8-sig")
    except Exception:
        return payload_json, 0, "Could not read CSV file. Please upload a UTF-8 CSV."

    reader = csv.DictReader(io.StringIO(text))
    csv_cols = reader.fieldnames or []

    # Strict block: CSV has columns not visible in table
    extra = [c for c in csv_cols if c and c.startswith("string_") and c not in visible_cols]
    if extra:
        return payload_json, 0, (
            "Upload blocked. Your file contains columns not supported by this reference: "
            + ", ".join(extra)
            + ". Download the template again and do not add extra columns."
        )

    # Parse payload
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}

    rows_list = obj.get("rows", [])
    if not isinstance(rows_list, list):
        rows_list = []

    added = 0
    for row in reader:
        new_row = {"row_type": "values", "operation": "INSERT", "update_rowid": ""}
        for c in visible_cols:
            v = row.get(c, "")
            if v is None:
                v = ""
            new_row[c] = str(v).strip()

        # skip empty rows
        if all((new_row.get(c) or "") == "" for c in visible_cols):
            continue

        rows_list.append(new_row)
        added += 1

    obj["rows"] = rows_list
    return json.dumps(obj, indent=2), added, None
