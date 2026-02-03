import json, os, csv, io, re, hashlib
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.http import FileResponse, Http404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.db import IntegrityError
from datetime import timedelta, date
from django_tables2 import RequestConfig

from .models import MDUHeader, ChangeRequest, MDUCert
from .filters import HeaderFilter, ProposedChangeFilter
from .tables import HeaderTable, ProposedChangeTable, CertTable
from .forms import ProposedChangeForm, CertForm, HeaderForm
from .permissions import group_required, in_group
from .services import payload_rows, derive_business_columns, generate_loader_artifacts

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

def _ref_kind_label(header: MDUHeader) -> str:
    """
    UI label for reference kind/type.
    Uses collaboration_mode if present; falls back safely.
    """
    mode = (getattr(header, "collaboration_mode", "") or "").upper()
    if mode == "COLLABORATIVE":
        return "Collab"
    if mode == "SINGLE_OWNER":
        return "Single"
    # fallback for unexpected/legacy values
    return mode.title() if mode else "Standard"


def _collab_touched_by_set(payload_json_or_obj) -> set[str]:
    """
    Best-effort extraction of "touched by" usernames from payload.
    This is intentionally defensive because payload structure may vary.

    Returns a set of usernames/sids found in any known touch/author fields on rows.
    If none exist, returns empty set (which results in 'Waiting' in the list).
    """
    obj = None

    if isinstance(payload_json_or_obj, dict):
        obj = payload_json_or_obj
    elif isinstance(payload_json_or_obj, str):
        try:
            obj = json.loads(payload_json_or_obj or "{}")
        except Exception:
            obj = {}
    else:
        obj = {}

    rows = obj.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # Common fields we’ve seen across payload variants (safe to scan)
    touch_keys = (
        "touched_by",
        "touched_by_sid",
        "edited_by",
        "edited_by_sid",
        "last_edited_by",
        "last_edited_by_sid",
        "created_by",
        "created_by_sid",
        "maker_sid",
        "author",
        "author_sid",
    )

    touched: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in touch_keys:
            v = (r.get(k) or "").strip()
            if v:
                touched.add(v)

    return touched


def _get_maker2_user():
    """
    Returns a single 'maker2' user if that group exists and has members.
    This avoids guessing a username.
    If no such group/user exists, returns None.
    """
    try:
        grp = Group.objects.filter(name="maker2").first()
        if not grp:
            return None
        User = get_user_model()
        return User.objects.filter(groups=grp).order_by("username").first()
    except Exception:
        return None


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
    """Unified list view optimized for:
    - Drafts (with drift detection + bulk delete for drifted)
    - Pending submissions
    - Decisioned history

    This intentionally avoids mixing Drafts with Decisioned to reduce confusion.
    """
    q = (request.GET.get("q") or "").strip()

    base = ChangeRequest.objects.select_related("header", "created_by").order_by("-updated_at", "-id")
    if q:
        base = base.filter(Q(display_id__icontains=q) | Q(header__ref_name__icontains=q))

    # In collaborative mode, a user may work on a draft they did not create.
    # Keep the list "mine" by including:
    # - changes I created
    # - collaborative drafts where I am an explicit contributor
    my = base.filter(Q(created_by=request.user) | Q(contributors=request.user)).distinct()

    drafts = list(my.filter(status=ChangeRequest.Status.DRAFT))
    submitted = list(my.filter(status=ChangeRequest.Status.SUBMITTED, created_by=request.user))
    decisioned = list(
        my.filter(
            status__in=[ChangeRequest.Status.APPROVED, ChangeRequest.Status.REJECTED],
            created_by=request.user,
        )
    )

    # Drift detection ("baseline changed")
    # - Prefer version compare when available
    # - Fall back to payload fingerprint compare when versions are unknown
    header_cache: dict[int, dict[str, str | int | None]] = {}
    drifted_ids: set[int] = set()

    for d in drafts:
        h = d.header
        if h.pk not in header_cache:
            baseline_payload_latest, baseline_version_latest = _current_baseline_for_header(h)
            header_cache[h.pk] = {
                "baseline_version": baseline_version_latest,
                "baseline_fp": _normalized_payload_fingerprint(baseline_payload_latest),
            }
        info = header_cache[h.pk]
        baseline_version_latest = info.get("baseline_version")
        baseline_fp_latest = info.get("baseline_fp")

        aligned = False
        if d.version is not None and baseline_version_latest is not None:
            aligned = (d.version == baseline_version_latest)
        else:
            aligned = (_normalized_payload_fingerprint(d.payload_json or "") == baseline_fp_latest)

        if not aligned:
            drifted_ids.add(d.pk)

    breadcrumbs = [
        _crumb("Catalog", reverse("mdu:catalog")),
        _crumb("My Proposed Changes", None),
    ]

    # Attach lightweight UI labels (no model changes)
    maker2 = _get_maker2_user()
    maker2_name = getattr(maker2, "username", None)

    def _decorate(ch):
        ch.ref_kind_label = _ref_kind_label(ch.header)
        ch.author_label = getattr(ch.created_by, "username", "") or ""
        if getattr(ch.header, "collaboration_mode", "").upper() == "COLLABORATIVE" and maker2_name:
            touched = _collab_touched_by_set(ch.payload_json or {})
            ch.maker2_status_label = "Complete" if maker2_name in touched else "Waiting"
        else:
            ch.maker2_status_label = "—"
        return ch

    drafts = [_decorate(c) for c in drafts]
    submitted = [_decorate(c) for c in submitted]
    decisioned = [_decorate(c) for c in decisioned]

    return render(request, "mdu/proposed_change_list.html", {
        "q": q,
        "drafts": drafts,
        "submitted": submitted,
        "decisioned": decisioned,
        "drifted_ids": drifted_ids,
        "breadcrumbs": breadcrumbs,
        **_role_flags(request.user),
    })


@require_POST
@group_required("maker")
def draft_bulk_delete(request):
    """Bulk delete drifted drafts without opening each one.

    Rules:
    - Only DRAFTs created_by the current user
    - Only those that are no longer aligned to the latest approved baseline
    """
    raw_ids = request.POST.getlist("draft_ids")
    try:
        ids = [int(x) for x in raw_ids]
    except Exception:
        ids = []

    if not ids:
        messages.info(request, "No drafts were selected.")
        return redirect("mdu:proposed_change_list")

    qs = ChangeRequest.objects.select_related("header").filter(
        pk__in=ids,
        status=ChangeRequest.Status.DRAFT,
        created_by=request.user,
    )

    deleted = 0
    for d in qs:
        baseline_payload_latest, baseline_version_latest = _current_baseline_for_header(d.header)
        baseline_fp_latest = _normalized_payload_fingerprint(baseline_payload_latest)

        aligned = False
        if d.version is not None and baseline_version_latest is not None:
            aligned = (d.version == baseline_version_latest)
        else:
            aligned = (_normalized_payload_fingerprint(d.payload_json or "") == baseline_fp_latest)

        if aligned:
            continue

        d.delete()
        deleted += 1

    if deleted:
        messages.success(request, f"Deleted {deleted} drifted draft(s).")
    else:
        messages.info(request, "No drifted drafts were deleted.")

    return redirect("mdu:proposed_change_list")


@group_required("approver", "business_owner")
def my_approvals(request):
    """Approver inbox: show only items awaiting a decision."""

    def _ops_and_totals(payload_json: str) -> tuple[int, str]:
        """Return (total_rows_affected, change_category) derived from payload operations."""
        try:
            obj = json.loads(payload_json or "{}")
        except Exception:
            obj = {}
        rows = obj.get("rows", [])
        if not isinstance(rows, list):
            rows = []

        ops = {
            "INSERT ROW": 0,
            "UPDATE ROW": 0,
            "RETIRE ROW": 0,
            "UNRETIRE ROW": 0,
        }

        for r in rows:
            if not isinstance(r, dict):
                continue
            if (r.get("row_type") or "").lower() == "header":
                continue
            op = (r.get("operation") or "").strip().upper()
            op = _normalize_operation(op)
            if op in ops:
                ops[op] += 1

        total = sum(ops.values())

        nonzero = [k for k, v in ops.items() if v]
        if not nonzero:
            category = "No Data Change"
        elif len(nonzero) == 1:
            category = nonzero[0].replace(" ROW", "").title()
        else:
            category = "Mixed Data Change"

        return total, category

    qs = (
        ChangeRequest.objects
        .select_related("header", "created_by")
        .filter(status=ChangeRequest.Status.SUBMITTED)
        .order_by("submitted_at", "-updated_at", "-id")
    )

    items = []
    for ch in qs:
        total_rows, category = _ops_and_totals(ch.payload_json)
        requested_by_sid = ch.requested_by_sid or (ch.created_by.username if ch.created_by else "")
        items.append({
            "ch": ch,
            "category": category,
            "requested_by_sid": requested_by_sid or "—",
            "total_rows": total_rows,
        })

    return render(request, "mdu/my_approvals.html", {
        "items": items,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb("My Approvals", None),
        ],
        **_role_flags(request.user),
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

def compute_baseline_update_ids(baseline_payload_json: str) -> dict[int, str]:
    """
    Builds baselineUpdateIds used by the UI to auto-populate update_rowid.
    - Keyed by row index (same index used in table inputs)
    - Hash is deterministic and based on business fields string_01..string_65
    """
    try:
        base_obj = json.loads(baseline_payload_json or "{}")
    except Exception:
        base_obj = {}

    rows = base_obj.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # Import here to avoid refactors / circulars
    from .validators import _deterministic_rowhash_from_values_row

    out: dict[int, str] = {}
    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        if (r.get("row_type") or "").lower() != "values":
            continue
        out[idx] = _deterministic_rowhash_from_values_row(r)

    return out


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

    lock_to_existing = ["version", "business_owner_sid", "approver_ad_group"]
    for f in lock_to_existing:
        post[f] = getattr(existing, f, "") if existing else ""

def _normalized_payload_fingerprint(payload_json: str) -> str:
    """
    Stable fingerprint to compare whether a draft aligns to latest baseline.
    Avoids whitespace/indent differences.
    """
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}
    try:
        s = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    except Exception:
        s = payload_json or ""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _current_baseline_for_header(header: MDUHeader) -> tuple[str, int | None]:
    """
    Returns (baseline_payload_json, baseline_version)
    baseline_version is best-effort from last_approved_change.version.
    """
    if header.last_approved_change and header.last_approved_change.payload_json:
        baseline_payload = header.last_approved_change.payload_json
        baseline_version = header.last_approved_change.version
        return baseline_payload, baseline_version

    # Fallback: minimal header-only payload, no version known
    baseline_payload = json.dumps({
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
    return baseline_payload, None


@group_required("maker")
def propose_change(request, header_pk):
    header = get_object_or_404(MDUHeader, pk=header_pk)

    # Non-collab guardrail: block NEW proposals if there is an OPEN change.
    # OPEN = DRAFT or SUBMITTED. For SINGLE_OWNER, route user to the existing open CR.
    if header.collaboration_mode == "SINGLE_OWNER":
        open_ch = (
            header.changes
            .filter(status__in=[ ChangeRequest.Status.SUBMITTED])
            .order_by("-updated_at", "-id")
            .first()
        )

        if open_ch:
            messages.error(
                request,
                "A pending change already exists for this reference. Please wait for approval or rejection before proposing a new change."
            )

            # SUBMITTED (or anything unexpected that is open) goes to detail
            return redirect("mdu:proposed_change_detail", pk=open_ch.pk)


    baseline_payload_latest, baseline_version_latest = _current_baseline_for_header(header)
    baseline_fp_latest = _normalized_payload_fingerprint(baseline_payload_latest)

    # Draft picker
    # - Single-owner: only the current user's drafts
    # - Collaborative: include drafts shared with the current user
    if header.collaboration_mode == "COLLABORATIVE":
        drafts_qs = (
            header.changes
            .filter(status=ChangeRequest.Status.DRAFT)
            .filter(Q(created_by=request.user) | Q(contributors=request.user))
            .distinct()
            .order_by("-updated_at", "-id")
        )
    else:
        drafts_qs = (
            header.changes
            .filter(status=ChangeRequest.Status.DRAFT, created_by=request.user)
            .order_by("-updated_at", "-id")
        )

    def _draft_is_aligned(d: ChangeRequest) -> bool:
        # Prefer version compare when both are known
        if d.version is not None and baseline_version_latest is not None:
            return d.version == baseline_version_latest
        # Fallback to payload fingerprint compare
        return _normalized_payload_fingerprint(d.payload_json or "") == baseline_fp_latest

    drafts = list(drafts_qs)
    aligned_draft = None
    stale_drafts = []

    for d in drafts:
        if aligned_draft is None and _draft_is_aligned(d):
            aligned_draft = d
        else:
            stale_drafts.append(d)

    # Breadcrumbs (consistent with other screens)
    breadcrumbs = [
        _crumb("Catalog", reverse("mdu:catalog")),
        _crumb(header.ref_name, reverse("mdu:header_detail", kwargs={"pk": header.pk})),
        _crumb("Propose Change", None),
    ]

    # GET: if any drafts exist, show picker
    if request.method != "POST" and drafts:
        latest_id = drafts[0].id
        return render(request, "mdu/draft_picker.html", {
            "header": header,
            "aligned_draft": aligned_draft,
            "stale_drafts": stale_drafts,
            "latest_id": latest_id,
            "baseline_version_latest": baseline_version_latest,
            "breadcrumbs": breadcrumbs,
            **_role_flags(request.user),
        })

    # POST: picker actions (no auto-save unless explicitly saving in the editor)
    if request.method == "POST":
        post = request.POST.copy()

        if post.get("picker") == "1":
            action = (post.get("action") or "").strip()

            if action == "use_aligned":
                if not aligned_draft:
                    messages.error(request, "No current draft was found to continue.")
                    return redirect("mdu:header_detail", pk=header.pk)
                return redirect("mdu:proposed_change_edit", pk=aligned_draft.pk)

            if action == "discard_replace_aligned":
                if aligned_draft:
                    aligned_draft.delete()
                    messages.warning(
                        request,
                        f"A saved draft already existed for {header.ref_name}. It was discarded and a new draft will be created using the latest approved version."
                    )

                # Open baseline editor (NO SAVE)
                initial_payload = _normalize_payload_operations(baseline_payload_latest)
                baseline_payload_json = initial_payload
                dirty_cells = {}
                request_overview_open = True

                form = ProposedChangeForm(initial={
                    "tracking_id": _suggest_tracking_id(),
                    "override_retired_flag": "N",
                    "payload_json": initial_payload,
                })

                payload = initial_payload
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
                    "baseline_update_ids_json": json.dumps(compute_baseline_update_ids(baseline_payload_json)),
                    "request_overview_open": request_overview_open,
                    "focus_row_index": None,
                    "rows_added_count": 0,
                    "editing": False,
                    "ch": None,
                    "change": None,
                    "breadcrumbs": breadcrumbs,
                    **_role_flags(request.user),
                })

            if action == "create_new":
                # Open baseline editor (NO SAVE)
                initial_payload = _normalize_payload_operations(baseline_payload_latest)
                baseline_payload_json = initial_payload
                dirty_cells = {}
                request_overview_open = True

                form = ProposedChangeForm(initial={
                    "tracking_id": _suggest_tracking_id(),
                    "override_retired_flag": "N",
                    "payload_json": initial_payload,
                })

                payload = initial_payload
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
                    "baseline_update_ids_json": json.dumps(compute_baseline_update_ids(baseline_payload_json)),
                    "request_overview_open": request_overview_open,
                    "focus_row_index": None,
                    "rows_added_count": 0,
                    "editing": False,
                    "ch": None,
                    "change": None,
                    "breadcrumbs": breadcrumbs,
                    **_role_flags(request.user),
                })

            if action == "view_draft":
                try:
                    did = int(post.get("draft_id") or "0")
                except Exception:
                    did = 0
                d = drafts_qs.filter(id=did).first()
                if not d:
                    messages.error(request, "Draft not found.")
                    return redirect("mdu:header_detail", pk=header.pk)
                return redirect("mdu:proposed_change_detail", pk=d.pk)

            if action == "discard_draft":
                try:
                    did = int(post.get("draft_id") or "0")
                except Exception:
                    did = 0
                d = drafts_qs.filter(id=did).first()
                if not d:
                    messages.error(request, "Draft not found.")
                    return redirect("mdu:header_detail", pk=header.pk)
                d.delete()
                messages.success(request, "Draft discarded.")
                return redirect("mdu:propose_change", header_pk=header.pk)


    # GET: if drafts exist, show picker instead of jumping directly
    if request.method != "POST" and drafts_qs.exists():
        latest_id = drafts_qs.first().id
        return render(request, "mdu/draft_picker.html", {
            "header": header,
            "drafts": drafts_qs,
            "latest_id": latest_id,
            "baseline_version_latest": baseline_version_latest,
            **_role_flags(request.user),
        })

    # POST from picker: user chose a draft or requested a fresh one
    if request.method == "POST" and (request.POST.get("picker") == "1"):
        action = (request.POST.get("action") or "").strip()

        if action == "use_draft":
            try:
                draft_id = int(request.POST.get("draft_id") or "0")
            except Exception:
                draft_id = 0

            ch = drafts_qs.filter(id=draft_id).first()
            if not ch:
                messages.error(request, "Selected draft was not found.")
                return redirect("mdu:header_detail", pk=header.pk)

            # Determine if draft aligns to current baseline:
            # Prefer version compare when available; fallback to payload fingerprint compare.
            draft_is_stale = False
            if ch.version is not None and baseline_version_latest is not None:
                draft_is_stale = (ch.version != baseline_version_latest)
            else:
                draft_fp = _normalized_payload_fingerprint(ch.payload_json or "")
                draft_is_stale = (draft_fp != baseline_fp_latest)

            if draft_is_stale:
                # Show confirm screen: discard old draft + create new aligned to latest baseline
                return render(request, "mdu/draft_picker.html", {
                    "header": header,
                    "drafts": drafts_qs,
                    "latest_id": drafts_qs.first().id if drafts_qs.exists() else None,
                    "baseline_version_latest": baseline_version_latest,
                    "stale_draft_id": ch.id,
                    "stale_draft_display_id": ch.display_id,
                    "stale_draft_updated_at": ch.updated_at,
                    "show_stale_confirm": True,
                    **_role_flags(request.user),
                })

            # Draft is aligned -> continue editing it
            return redirect("mdu:proposed_change_edit", pk=ch.pk)

        if action == "discard_and_create_new":
            try:
                stale_id = int(request.POST.get("stale_draft_id") or "0")
            except Exception:
                stale_id = 0

            stale = drafts_qs.filter(id=stale_id).first()
            if stale:
                stale.delete()
                messages.warning(
                    request,
                    f"An older draft was found for {header.ref_name}. It was discarded and a new draft will be created using the latest approved version."
                )

            # Fall through into normal propose_change flow (create new baseline-aligned draft)
            # We reset request.method handling by continuing; the code below will handle POST normally.

        if action == "create_new":
            # Fall through into normal propose_change flow (create new baseline-aligned draft)
            pass






    if header.status == MDUHeader.Status.RETIRED:
        messages.warning(
            request,
            "This reference is retired. You can still propose a change, but it must be flagged as an override."
        )

    request_overview_open = True

    dirty_cells = {}
    baseline_payload_json = ""

    # Used by template to scroll/focus and show inline "X rows added"
    focus_row_index = None
    rows_added_count = 0

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
        # Draft picker actions (do NOT save on create-new)
        # When user chooses "Create New Draft" from the picker, render the baseline editor
        # (same as GET) and let the user decide whether to Save Draft.
        if post.get("picker") == "1" and post.get("action") in ("create_new", "discard_and_create_new"):
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

            # keep overview open by default
            request_overview_open = True

            # Skip the rest of POST handling (no add_row/bulk_upload/save)
            # and continue to the shared render() at the bottom.
        else:
            # existing POST logic continues below
            pass

        post = request.POST.copy()

        if not (post.get("picker") == "1" and post.get("action") in ("create_new", "discard_and_create_new")):
            request_overview_open = (post.get("request_overview_open") == "1")

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
            # capture pre-count so we can focus the first newly added row
            try:
                obj_before = json.loads(post.get("payload_json", "") or "{}")
            except Exception:
                obj_before = {}
            rows_list_before = obj_before.get("rows", [])
            if not isinstance(rows_list_before, list):
                rows_list_before = []
            pre_count = len(rows_list_before)

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
                    rows_added_count = 0
                    focus_row_index = None
                else:
                    rows_added_count = added
                    if added > 0:
                        focus_row_index = pre_count  # first newly added row
                        messages.success(request, f"Added {added} rows from CSV.")
                    else:
                        focus_row_index = None
                        messages.warning(request, "No rows were added (CSV had no non-empty rows).")

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

            new_row = {"row_type": "values", "operation": "INSERT ROW", "update_rowid": ""}
            for i in range(1, 66):
                new_row[f"string_{i:02d}"] = ""

            rows_list.append(new_row)
            obj["rows"] = rows_list
            post["payload_json"] = json.dumps(obj, indent=2)

            # row added UX signals
            rows_added_count = 1
            focus_row_index = len(rows_list) - 1

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

                # Snapshot collaboration mode for DB constraints + workflow rules
                ch.collaboration_mode = header.collaboration_mode

                # Stamp baseline version so we can detect stale drafts later
                _, baseline_version_latest = _current_baseline_for_header(header)
                ch.version = baseline_version_latest

                try:
                    ch.save()
                except IntegrityError:
                    # DB constraint: one open CR per non-collab reference (SINGLE_OWNER)
                    # Convert race-condition into the standard guardrail message.
                    messages.error(
                        request,
                        "A pending change already exists for this reference. Please wait for approval or rejection before proposing a new change."
                    )
                    return redirect("mdu:header_detail", pk=header.pk)




                drafts_url = reverse("mdu:proposed_change_list")

                messages.success(
                    request,
                    mark_safe(
                        'Draft saved. Review the table, then submit when ready. '
                        f'To review your drafts, click <a href="{drafts_url}">here</a>.'
                    )
                )

                next_action = request.POST.get("save_next", "stay")
                if next_action == "back":
                    return redirect("mdu:header_detail", pk=header.pk)

                # Stay on edit screen and tag URL so we can auto-show a “saved” toast
                return redirect(f"{reverse('mdu:proposed_change_edit', kwargs={'pk': ch.pk})}?saved=1")

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
        "baseline_update_ids_json": json.dumps(compute_baseline_update_ids(baseline_payload_json)),
        "request_overview_open": request_overview_open,

        # NEW: for scroll/focus + inline notification under table
        "focus_row_index": focus_row_index,
        "rows_added_count": rows_added_count,

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

    # --- UI toggles (server-driven) ---
    view_mode = (request.GET.get("view") or "changes").lower()
    show_changes_only = view_mode != "all"

    diff_format = (request.GET.get("format") or "diff").lower()
    if diff_format not in ("diff", "clean"):
        diff_format = "diff"

    # --- Proposed rows (after) ---
    rows = payload_rows(ch.payload_json)
    biz_cols = derive_business_columns(rows) if rows else []

    # --- Baseline rows (before) ---
    def _rows_from_payload(payload_json: str):
        try:
            obj = json.loads(payload_json or "{}")
        except Exception:
            obj = {}
        r = obj.get("rows", [])
        return r if isinstance(r, list) else []

    header = ch.header
    before_payload = ""
    latest = getattr(header, "last_approved_change", None)

    if latest and latest.pk != ch.pk:
        before_payload = latest.payload_json or ""
    else:
        prev = (
            header.changes
            .filter(status=ChangeRequest.Status.APPROVED)
            .exclude(pk=ch.pk)
            .order_by("-version", "-decided_at", "-id")
            .first()
        )
        before_payload = (prev.payload_json if prev else "") or ""

    before_rows = _rows_from_payload(before_payload)
    after_rows = _rows_from_payload(ch.payload_json)

    # --- Diff rows (baseline vs proposed), business columns only ---
    def _header_row(rows_list):
        return next((r for r in rows_list if (r.get("row_type") or "").lower() == "header"), {}) or {}

    def _is_values_row(r):
        return (r.get("row_type") or "").lower() != "header"

    def _build_biz_cols(before_rows_list, after_rows_list):
        after_hdr = _header_row(after_rows_list)
        before_hdr = _header_row(before_rows_list)
        string_cols = [f"string_{i:02d}" for i in range(1, 66)]

        def used(col):
            if (after_hdr.get(col) or "").strip() or (before_hdr.get(col) or "").strip():
                return True
            for r in after_rows_list:
                if (r.get(col) or "").strip():
                    return True
            for r in before_rows_list:
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

    diff_cols = _build_biz_cols(before_rows, after_rows)
    before_vals = [r for r in before_rows if isinstance(r, dict) and _is_values_row(r)]
    after_vals = [r for r in after_rows if isinstance(r, dict) and _is_values_row(r)]

    # Effective dating columns are relevant for non-snapshot references.
    show_effective_dates = (header.mode or "").lower() != "snapshot"

    max_len = max(len(before_vals), len(after_vals)) if (before_vals or after_vals) else 0
    diff_rows = []
    for i in range(max_len):
        b = before_vals[i] if i < len(before_vals) else {}
        a = after_vals[i] if i < len(after_vals) else {}

        op = _normalize_operation((a.get("operation") or "").strip())
        if not op:
            # Defensive: treat missing op as KEEP
            op = "KEEP ROW"

        row_type = (a.get("row_type") or "values")
        start_dt = (a.get("start_dt") or "")
        end_dt = (a.get("end_dt") or "")

        is_insert = (op == "INSERT ROW")

        cells = []
        row_changed = False
        for col in diff_cols:
            tech = col["tech"]
            bv = (b.get(tech) or "").strip()
            av = (a.get(tech) or "").strip()
            changed = (bv != av)
            if changed:
                row_changed = True
            cells.append({"before": bv, "after": av, "changed": changed})

        # Operation changes matter even when values are identical.
        op_is_change = op in {"UPDATE ROW", "INSERT ROW", "RETIRE ROW", "UNRETIRE ROW"}
        row_effective_changed = row_changed or op_is_change

        diff_rows.append({
            "row_type": row_type,
            "operation": op,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "is_insert": is_insert,
            "change_comment": (a.get("change_comment") or "").strip(),
            "cells": cells,
            "row_changed": row_effective_changed,
        })

    # Counts for View toggles (must be server-derived)
    all_count = len(after_vals)
    changes_count = sum(1 for r in diff_rows if r.get("row_changed"))

    if show_changes_only:
        diff_rows = [r for r in diff_rows if r.get("row_changed")]

    # --- Drift-aware edit button ---
    can_decide = (ch.status == ChangeRequest.Status.SUBMITTED) and (
        in_group(request.user, "approver") or in_group(request.user, "business_owner")
    )

    can_edit = False
    if (ch.status == ChangeRequest.Status.DRAFT) and in_group(request.user, "maker"):
        baseline_payload_latest, baseline_version_latest = _current_baseline_for_header(header)
        baseline_fp_latest = _normalized_payload_fingerprint(baseline_payload_latest)
        if ch.version is not None and baseline_version_latest is not None:
            can_edit = (ch.version == baseline_version_latest)
        else:
            can_edit = (_normalized_payload_fingerprint(ch.payload_json or "") == baseline_fp_latest)

    # Change summary (values rows only)
    def _op(r):
        return _normalize_operation((r.get("operation") or "").strip())

    started_total = len(before_vals)

    added = sum(1 for r in after_vals if _op(r) in {"INSERT ROW", "UNRETIRE ROW"})
    updated = sum(1 for r in after_vals if _op(r) == "UPDATE ROW")
    deleted = sum(1 for r in after_vals if _op(r) == "RETIRE ROW")
    unchanged = sum(1 for r in after_vals if _op(r) in {"KEEP ROW", ""})

    once_approved_total = unchanged + updated + added + deleted

    return render(request, "mdu/proposed_change_detail.html", {
        "ch": ch,
        "breadcrumbs": [
            _crumb("Catalog", reverse("mdu:catalog")),
            _crumb("My Proposed Changes", reverse("mdu:proposed_change_list")),
            _crumb(ch.display_id, None),
        ],
        "rows": rows,
        "biz_cols": biz_cols,
        "can_edit": can_edit,
        "can_decide": can_decide,
        "diff_cols": diff_cols,
        "diff_rows": diff_rows,
        "before_exists": bool(before_rows),
        "show_changes_only": show_changes_only,
        "view_mode": "all" if not show_changes_only else "changes",
        "view_counts": {"all": all_count, "changes": changes_count},
        "diff_format": diff_format,
        "show_effective_dates": show_effective_dates,
        "change_summary": {
            "started_total": started_total,
            "once_approved_total": once_approved_total,
            "unchanged": unchanged,
            "updated": updated,
            "added": added,
            "deleted": deleted,
        },
        **_role_flags(request.user)
    })
@group_required("maker")
def proposed_change_edit(request, pk):
    
    ch = get_object_or_404(ChangeRequest, pk=pk)

    # Collaborative drafts can be edited by explicit contributors (and the creator).
    # Single-owner drafts remain restricted to the creator.
    if ch.header.collaboration_mode == "COLLABORATIVE":
        is_collab_editor = (ch.created_by_id == request.user.id) or ch.contributors.filter(pk=request.user.pk).exists()
        if not is_collab_editor:
            messages.error(request, "This draft is not shared with you.")
            return redirect("mdu:proposed_change_detail", pk=ch.pk)
    else:
        if ch.created_by_id != request.user.id:
            messages.error(request, "Only the creator of this draft can edit it.")
            return redirect("mdu:proposed_change_detail", pk=ch.pk)

    if ch.status != ChangeRequest.Status.DRAFT:
        messages.error(request, "Only drafts can be edited.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    header = ch.header
    # If this draft is no longer aligned to the latest approved baseline, force read-only view.
    # (Users may keep it for reference, but must discard & recreate to submit.)
    baseline_payload_latest, baseline_version_latest = _current_baseline_for_header(header)
    baseline_fp_latest = _normalized_payload_fingerprint(baseline_payload_latest)

    aligned = False
    if ch.version is not None and baseline_version_latest is not None:
        aligned = (ch.version == baseline_version_latest)
    else:
        aligned = (_normalized_payload_fingerprint(ch.payload_json or "") == baseline_fp_latest)

    if not aligned:
        messages.error(
            request,
            f"The approved data for {header.ref_name} has changed since this draft was created. This draft is view-only. Discard it and create a new draft to submit."
        )
        return redirect("mdu:proposed_change_detail", pk=ch.pk)



    dirty_cells = {}
    baseline_payload_json = ""

    request_overview_open = True


    # NEW: used by template to scroll/focus and show inline "X rows added"
    focus_row_index = None
    rows_added_count = 0

    if request.method != "POST":

        # Baseline must always be the latest approved payload (dirty detection is baseline-driven).
        baseline_payload_json = (
            header.last_approved_change.payload_json
            if header.last_approved_change and header.last_approved_change.payload_json
            else ""
        )

        form = ProposedChangeForm(instance=ch)

        # Render the DRAFT payload (not the baseline)
        payload = _normalize_payload_operations(ch.payload_json or baseline_payload_json)
        rows = payload_rows(payload)
        # Dirty cells must be computed on GET so highlighting survives reload/redirect
        dirty_cells = compute_dirty_cells(baseline_payload_json, payload)

    else:
        post = request.POST.copy()

        request_overview_open = (post.get("request_overview_open") == "1")

        baseline_payload_json = (
            post.get("baseline_payload_json", "")
            or (
                header.last_approved_change.payload_json
                if header.last_approved_change and header.last_approved_change.payload_json
                else ""
            )
        )

        
        post["payload_json"] = _apply_cell_edits_to_payload_json(
            post.get("payload_json", ""),
            post
        )

        post["payload_json"] = _normalize_payload_operations(post["payload_json"])

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

            new_row = {"row_type": "values", "operation": "INSERT ROW", "update_rowid": ""}
            for i in range(1, 66):
                new_row[f"string_{i:02d}"] = ""

            rows_list.append(new_row)
            obj["rows"] = rows_list
            post["payload_json"] = json.dumps(obj, indent=2)

            # NEW: row added UX signals
            rows_added_count = 1
            focus_row_index = len(rows_list) - 1

            dirty_cells = compute_dirty_cells(baseline_payload_json, post["payload_json"])

            form = ProposedChangeForm(post, instance=ch)
            payload = post["payload_json"]
            rows = payload_rows(payload)

        elif action == "bulk_upload":
            f = request.FILES.get("bulk_csv")
            if not f:
                messages.error(request, "Please choose a CSV file to upload.")
                form = ProposedChangeForm(post, instance=ch)
                payload = post.get("payload_json", "")
                dirty_cells = compute_dirty_cells(baseline_payload_json, payload)
                rows = payload_rows(payload)

            else:
                # --- build visible_cols from current header row in payload_json ---
                payload_before = post.get("payload_json", "") or "{}"
                rows_before = payload_rows(payload_before)

                header_row = next(
                    (r for r in (rows_before or []) if (r.get("row_type") or "").lower() == "header"),
                    {}
                ) or {}

                string_cols = [f"string_{i:02d}" for i in range(1, 66)]
                visible_cols = [c for c in string_cols if (header_row.get(c) or "").strip()]

                if not visible_cols:
                    messages.error(request, "Cannot determine business columns for this reference. (Missing header row labels.)")
                    form = ProposedChangeForm(post, instance=ch)
                    payload = payload_before
                    dirty_cells = compute_dirty_cells(baseline_payload_json, payload)
                    rows = rows_before

                else:
                    # --- read csv, allow hinted headers like: string_01 (Country Code) ---
                    try:
                        text = f.read().decode("utf-8-sig")
                    except Exception:
                        messages.error(request, "Could not read CSV file. Please upload a UTF-8 CSV.")
                        form = ProposedChangeForm(post, instance=ch)
                        payload = payload_before
                        dirty_cells = compute_dirty_cells(baseline_payload_json, payload)
                        rows = rows_before

                    else:
                        reader = csv.DictReader(io.StringIO(text))
                        fieldnames = reader.fieldnames or []

                        header_re = re.compile(r"^(string_\d{2})\b", re.IGNORECASE)
                        display_to_tech = {}
                        tech_cols_in_file = []

                        for h in fieldnames:
                            if not h:
                                continue
                            s = str(h).strip()
                            m = header_re.match(s)
                            if not m:
                                continue
                            tech = m.group(1).lower()
                            display_to_tech[s] = tech
                            tech_cols_in_file.append(tech)

                        # Reject extra columns beyond the reference
                        extra = [t for t in tech_cols_in_file if t.startswith("string_") and t not in visible_cols]
                        if extra:
                            messages.error(
                                request,
                                "Upload blocked. Your file contains columns not supported by this reference: "
                                + ", ".join(extra)
                                + ". Download the template again and do not add extra columns."
                            )
                            form = ProposedChangeForm(post, instance=ch)
                            payload = payload_before
                            dirty_cells = compute_dirty_cells(baseline_payload_json, payload)
                            rows = rows_before

                        else:
                            try:
                                obj = json.loads(payload_before or "{}")
                            except Exception:
                                obj = {}

                            rows_list = obj.get("rows", [])
                            if not isinstance(rows_list, list):
                                rows_list = []

                            pre_count = len(rows_list)
                            added = 0

                            for r in reader:
                                new_row = {"row_type": "values", "operation": "INSERT ROW", "update_rowid": ""}

                                for c in visible_cols:
                                    v = ""
                                    for display_h, tech in display_to_tech.items():
                                        if tech == c:
                                            v = r.get(display_h, "")
                                            break
                                    if v is None:
                                        v = ""
                                    new_row[c] = str(v).strip()

                                # skip totally empty rows
                                if all((new_row.get(c) or "") == "" for c in visible_cols):
                                    continue

                                rows_list.append(new_row)
                                added += 1

                            obj["rows"] = rows_list
                            post["payload_json"] = json.dumps(obj, indent=2)

                            # NEW: row added UX signals
                            rows_added_count = added
                            if added > 0:
                                focus_row_index = pre_count  # first newly added row
                                messages.success(request, f"Added {added} rows.")
                            else:
                                messages.warning(request, "No rows were added (CSV had no non-empty rows).")

                            dirty_cells = compute_dirty_cells(baseline_payload_json, post["payload_json"])
                            form = ProposedChangeForm(post, instance=ch)
                            payload = post["payload_json"]
                            rows = payload_rows(payload)

        else:
            form = ProposedChangeForm(post, instance=ch)
            if form.is_valid():

                # Optimistic locking: detect multi-window edits
                try:
                    posted_lock = int((post.get("lock_version") or "").strip() or "0")
                except Exception:
                    posted_lock = 0

                if posted_lock != ch.lock_version:
                    messages.error(
                        request,
                        "This draft was updated in another window. Please reload the page and apply your changes again."
                    )
                    return redirect("mdu:proposed_change_edit", pk=ch.pk)

                ch2 = form.save(commit=False)

                # IMPORTANT: carry over any fields that are not part of the form
                ch2.header = ch.header
                ch2.display_id = ch.display_id
                ch2.created_by = ch.created_by
                ch2.status = ch.status
                ch2.version = ch.version

                # Snapshot collaboration mode for DB constraints + workflow rules
                ch2.collaboration_mode = ch.header.collaboration_mode

                # Persist the edited payload_json that we computed above (server truth)
                ch2.payload_json = post.get("payload_json", ch.payload_json) or ""

                # Bump lock version on every successful save
                ch2.lock_version = ch.lock_version + 1

                ch2.save(update_fields=[
                    "tracking_id",
                    "requested_by_sid",
                    "business_owner_sid",
                    "approver_ad_group",
                    "version",
                    "operation_hint",
                    "change_reason",
                    "change_ticket_ref",
                    "change_category",
                    "payload_json",
                    "collaboration_mode",
                    "lock_version",
                    "updated_at",
                ])

                # Collaborative mode: ensure the editor is recorded as a contributor.
                if ch2.header.collaboration_mode == "COLLABORATIVE":
                    if request.user.is_authenticated:
                        ch2.contributors.add(request.user)



                # Link to the list screen (adjust URL name if your project uses a different one)
                drafts_url = reverse("mdu:proposed_change_list")

                messages.success(
                    request,
                    mark_safe(
                        'Draft saved. Review the table, then submit when ready. '
                        f'To review your drafts, click <a href="{drafts_url}">here</a>.'
                    )
                )

                # Decide where to go next based on the modal choice
                next_action = request.POST.get("save_next", "stay")
                if next_action == "back":
                    return redirect("mdu:header_detail", pk=header.pk)

                # Stay on the same edit screen
                return redirect(f"{reverse('mdu:proposed_change_edit', kwargs={'pk': ch.pk})}?saved=1")


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
        "baseline_update_ids_json": json.dumps(compute_baseline_update_ids(baseline_payload_json)),
        "request_overview_open": request_overview_open,

        # NEW: for scroll/focus + inline notification under table
        "focus_row_index": focus_row_index,
        "rows_added_count": rows_added_count,

        "editing": True,
        "ch": ch,
        "change": ch,  # keep template compatibility if it expects 'change'
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

    posted_uuid = (request.POST.get("draft_uuid") or "").strip()
    posted_lock_raw = (request.POST.get("lock_version") or "").strip()

    # Idempotent submit handling:
    # - If it was already submitted, treat as success IF draft_uuid matches
    if ch.status == ChangeRequest.Status.SUBMITTED:
        if posted_uuid and str(ch.draft_uuid) == posted_uuid:
            messages.info(request, "This change request was already submitted.")
            return redirect("mdu:proposed_change_detail", pk=ch.pk)
        raise Http404()

    # Only drafts can be submitted
    if ch.status != ChangeRequest.Status.DRAFT:
        raise Http404()

    # Draft UUID must match (submit from stale tab is blocked)
    if not posted_uuid or str(ch.draft_uuid) != posted_uuid:
        messages.error(
            request,
            "This draft was refreshed or replaced. Please reload the page before submitting."
        )
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    # Optimistic locking must match
    try:
        posted_lock = int(posted_lock_raw or "0")
    except Exception:
        posted_lock = 0

    if posted_lock != ch.lock_version:
        messages.error(
            request,
            "This draft was updated in another window. Please reload the page before submitting."
        )
        return redirect("mdu:proposed_change_detail", pk=ch.pk)


    ch.status = ChangeRequest.Status.SUBMITTED
    ch.submitted_at = timezone.now()

    # Bump lock version as part of submit transition
    ch.lock_version = ch.lock_version + 1

    ch.save(update_fields=["status", "submitted_at", "tracking_id", "lock_version", "updated_at"])
    messages.success(request, "Submitted for approval.")
    return redirect("mdu:proposed_change_detail", pk=ch.pk)

@require_POST
@group_required("approver", "business_owner")
def proposed_change_decide(request, pk, decision):
    ch = get_object_or_404(ChangeRequest, pk=pk)
    if ch.status != ChangeRequest.Status.SUBMITTED:
        raise Http404()

    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "A decision comment is required.")
        return redirect("mdu:proposed_change_detail", pk=ch.pk)

    if decision == "approve":
        ch.status = ChangeRequest.Status.APPROVED
        ch.decided_at = timezone.now()
        ch.decision_note = note
        ch.decided_by_sid = (getattr(request.user, "username", "") or "").strip()
        ch.save(update_fields=["status","decided_at","decision_note","decided_by_sid","updated_at"])

        header = ch.header
        header.last_approved_change = ch
        header.status = MDUHeader.Status.ACTIVE
        header.save(update_fields=["last_approved_change","status","updated_at"])
        messages.success(request, "Approved. You can now generate load files.")

    elif decision == "reject":
        ch.status = ChangeRequest.Status.REJECTED
        ch.decided_at = timezone.now()
        ch.decision_note = note
        ch.decided_by_sid = (getattr(request.user, "username", "") or "").strip()
        ch.save(update_fields=["status","decided_at","decision_note","decided_by_sid","updated_at"])
        messages.info(request, "Rejected.")

    else:
        raise Http404()

    return redirect("mdu:my_approvals")


@group_required("approver", "business_owner")
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


def _normalize_operation(op: str) -> str:
    """
    Normalize all operation values to LOCKED UI/Audit labels.
    """
    s = (op or "").strip().upper()

    # Legacy mappings (do not allow these to persist)
    if s == "INSERT":
        return "INSERT ROW"
    if s == "UPDATE":
        return "UPDATE ROW"
    if s in ("DELETE", "REMOVE"):
        return "RETIRE ROW"
    if s in ("RETAIN", ""):
        return "KEEP ROW"

    # Already correct (LOCKED)
    if s in ("INSERT ROW", "UPDATE ROW", "KEEP ROW", "RETIRE ROW", "UNRETIRE ROW"):
        return s

    # Unknown -> default safe behavior for VALUES rows
    return "KEEP ROW"


def _normalize_payload_operations(payload_json: str) -> str:
    """
    Ensure every VALUES row has a valid LOCKED operation label.
    Header rows are left untouched.
    """
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}

    rows = obj.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    for r in rows:
        if not isinstance(r, dict):
            continue

        row_type = (r.get("row_type") or "").strip().lower()
        if row_type != "values":
            continue

        r["operation"] = _normalize_operation(r.get("operation", ""))

    obj["rows"] = rows
    return json.dumps(obj, indent=2)


def _apply_cell_edits_to_payload_json(payload_json: str, post_data) -> str:
    """
    Takes existing payload_json and applies:
      1) table cell edits:
         cell__<row_index>__<colname> = value
      2) system-owned row intent + ids:
         op__<row_index> = "" | "KEEP ROW" | "UPDATE ROW" | "INSERT ROW" | "RETIRE ROW" | "UNRETIRE ROW"
         update_rowid__<row_index> = <hash>
         row_delete__<row_index> = "0" | "1"  (UI toggle; persisted by op/update_rowid)
      3) optional reviewer context:
         change_comment__<row_index> = <text>

    Returns updated payload_json string.
    """
    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}

    rows = obj.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    # ---------- 1) Apply business cell edits ----------
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

    # ---------- 2) Apply system-owned row intent + update_rowid ----------
    for key, val in post_data.items():
        # op__<idx>
        if key.startswith("op__"):
            try:
                _, idx_str = key.split("__", 1)
                idx = int(idx_str)
            except Exception:
                continue
            if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
                op = (val or "").strip().upper()

                # Backward-compat and normalization (older payloads / older UI posts)
                legacy_map = {
                    "RETAIN": "KEEP ROW",
                    "KEEP": "KEEP ROW",
                    "UPDATE": "UPDATE ROW",
                    "INSERT": "INSERT ROW",
                    "DELETE": "RETIRE ROW",
                    "UNRETIRE": "UNRETIRE ROW",
                }
                op = legacy_map.get(op, op)

                # Empty op means "KEEP ROW" for baseline-aligned rows
                if not op:
                    op = "KEEP ROW"

                # Internal-only op used by JS when undoing a brand-new INSERT row.
                # These rows are removed from the payload before saving.
                if op == "SKIP":
                    rows[idx]["operation"] = "SKIP"
                else:
                    rows[idx]["operation"] = op
            continue

        # update_rowid__<idx>
        if key.startswith("update_rowid__"):
            try:
                _, idx_str = key.split("__", 1)
                idx = int(idx_str)
            except Exception:
                continue
            if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
                rows[idx]["update_rowid"] = (val or "").strip()
            continue

        # change_comment__<idx> (optional, user-facing)
        if key.startswith("change_comment__"):
            try:
                _, idx_str = key.split("__", 1)
                idx = int(idx_str)
            except Exception:
                continue
            if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
                rows[idx]["change_comment"] = (val or "").strip()
            continue

        # change_comment__<idx> (optional)
        if key.startswith("change_comment__"):
            try:
                _, idx_str = key.split("__", 1)
                idx = int(idx_str)
            except Exception:
                continue
            if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
                rows[idx]["change_comment"] = (val or "").strip()
            continue

        # row_delete__<idx> is UI-facing; operation drives the loader meaning
        # (kept here only to avoid dropping the POST field; no direct payload field needed)
        if key.startswith("row_delete__"):
            continue

    # Drop internal-only hidden rows
    rows = [r for r in rows if not (isinstance(r, dict) and (r.get("operation") == "SKIP"))]

    obj["rows"] = rows
    return json.dumps(obj, indent=2)


def _visible_cols_from_rows(rows):
    header_row = next((r for r in rows if (r.get("row_type") or "").lower() == "header"), {}) or {}
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    return [c for c in string_cols if (header_row.get(c) or "").strip()]


_HEADER_RE = re.compile(r"^(string_\d{2})\b", re.IGNORECASE)

def _append_csv_rows_as_inserts(payload_json: str, uploaded_file, visible_cols: list[str]):
    """
    Appends CSV rows as INSERT rows to payload_json.
    Accepts headers like:
      - string_01
      - string_01 (VALUE)
      - string_01 - VALUE
    Rejects extra string_nn columns not present in visible_cols.
    """
    if not uploaded_file:
        return payload_json, 0, "Please choose a CSV file to upload."

    try:
        text = uploaded_file.read().decode("utf-8-sig")
    except Exception:
        return payload_json, 0, "Could not read CSV file. Please upload a UTF-8 CSV."

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    # map display header -> tech header
    display_to_tech = {}
    tech_cols_in_file = []

    for h in fieldnames:
        if not h:
            continue
        s = str(h).strip()
        m = _HEADER_RE.match(s)
        if not m:
            continue
        tech = m.group(1).lower()
        display_to_tech[s] = tech
        tech_cols_in_file.append(tech)

    # if none recognized, it is not the template
    if not tech_cols_in_file:
        return payload_json, 0, "CSV headers do not match the expected template. Please download the template and use that."

    # reject extra columns
    extra = [t for t in tech_cols_in_file if t.startswith("string_") and t not in visible_cols]
    if extra:
        return payload_json, 0, (
            "Upload blocked. Your file contains columns not supported by this reference: "
            + ", ".join(extra)
            + ". Download the template again and do not add extra columns."
        )

    try:
        obj = json.loads(payload_json or "{}")
    except Exception:
        obj = {}

    rows_list = obj.get("rows", [])
    if not isinstance(rows_list, list):
        rows_list = []

    added = 0
    for r in reader:
        new_row = {"row_type": "values", "operation": "INSERT ROW", "update_rowid": ""}

        for c in visible_cols:
            v = ""
            for display_h, tech in display_to_tech.items():
                if tech == c:
                    v = r.get(display_h, "")
                    break
            if v is None:
                v = ""
            new_row[c] = str(v).strip()

        if all((new_row.get(c) or "") == "" for c in visible_cols):
            continue

        rows_list.append(new_row)
        added += 1

    obj["rows"] = rows_list
    new_payload = json.dumps(obj, indent=2)

    if added == 0:
        return new_payload, 0, "No rows were added (CSV had no non-empty rows)."

    return new_payload, added, None
