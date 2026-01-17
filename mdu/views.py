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
from .forms import ProposedChangeForm, CertForm
from .permissions import group_required, in_group
from .services import payload_rows, derive_business_columns, generate_loader_artifacts


def _role_flags(user):
    return {
        "is_maker": in_group(user, "maker"),
        "is_steward": in_group(user, "steward"),
        "is_approver": in_group(user, "approver"),
    }

@login_required
def catalog(request):
    qs = MDUHeader.objects.all().order_by("ref_name")

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
        },
    )

@group_required("maker", "steward", "approver")
def proposed_change_list(request):
    qs = ChangeRequest.objects.select_related("header").order_by("-created_at")
    f = ProposedChangeFilter(request.GET, queryset=qs)
    table = ProposedChangeTable(f.qs)
    RequestConfig(request, paginate={"per_page": 15}).configure(table)
    return render(request, "mdu/proposed_change_list.html", {"filter": f, "table": table, **_role_flags(request.user)})


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


@group_required("maker")
def propose_change(request, header_pk):
    header = get_object_or_404(MDUHeader, pk=header_pk)

    if header.status == MDUHeader.Status.RETIRED:
        messages.warning(request, "This reference is retired. You can still propose a change, but it must be flagged as an override.")

    if request.method == "POST":
        form = ProposedChangeForm(request.POST)
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
    else:
        # Option B: prefill from latest approved sample
        if header.last_approved_change and header.last_approved_change.payload_json:
            initial_payload = header.last_approved_change.payload_json
        else:
            initial_payload = json.dumps({
                "rows": [
                    {"row_type":"header","operation":"BUILD NEW","start_dt":"","end_dt":"","version":"",
                     "string_01":"BUS_FIELD_01","string_02":"BUS_FIELD_02","string_03":"BUS_FIELD_03"}
                ]
            }, indent=2)

        form = ProposedChangeForm(initial={
            "tracking_id": _suggest_tracking_id(),
            "override_retired_flag": "N",
            "payload_json": initial_payload
        })

    return render(request, "mdu/proposed_change_form.html", {"header": header, "form": form, **_role_flags(request.user)})


@group_required("maker", "steward", "approver")
def proposed_change_detail(request, pk):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    rows = payload_rows(ch.payload_json)
    biz_cols = derive_business_columns(rows) if rows else []
    can_edit = (ch.status == ChangeRequest.Status.DRAFT) and in_group(request.user, "maker")
    can_decide = (ch.status == ChangeRequest.Status.SUBMITTED) and in_group(request.user, "approver")

    return render(request, "mdu/proposed_change_detail.html", {
        "ch": ch,
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

    if request.method == "POST":
        form = ProposedChangeForm(request.POST, instance=ch)
        if form.is_valid():
            form.save()
            messages.success(request, "Draft updated.")
            return redirect("mdu:proposed_change_detail", pk=ch.pk)
    else:
        form = ProposedChangeForm(instance=ch)

    return render(request, "mdu/proposed_change_form.html", {"header": ch.header, "form": form, "editing": True, "ch": ch, **_role_flags(request.user)})


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

    # Block rowid in payload (loader rule)
    try:
        data = json.loads(ch.payload_json or "{}")
    except Exception:
        data = {}
    rows = data.get("rows") if isinstance(data, dict) else None
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("rowid"):
                messages.error(request, "Row ID must not be provided. Please remove 'rowid' from the data.")
                return redirect("mdu:proposed_change_detail", pk=ch.pk)

    ch.status = ChangeRequest.Status.SUBMITTED
    ch.submitted_at = timezone.now()
    ch.save(update_fields=["status","submitted_at","tracking_id","updated_at"])
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
    return render(request, "mdu/cert_list.html", {"table": table, **_role_flags(request.user)})


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
    return render(request, "mdu/cert_form.html", {"form": form, **_role_flags(request.user)})


def _safe_rows(payload_json: str):
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []
