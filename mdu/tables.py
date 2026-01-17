import django_tables2 as tables
from django.utils.html import format_html
from django.utils.text import Truncator
from django.urls import reverse
from .models import MDUHeader, ChangeRequest, MDUCert

class HeaderTable(tables.Table):
    # ref_name is intentionally NOT a hyperlink. Entire row is clickable.
    ref_name = tables.Column(verbose_name="Reference Name")
    
    description = tables.Column(verbose_name="Description",
        attrs={"td": {"class": "truncate col-desc"},"th": {"class": "col-desc"},},)
    
    ref_type = tables.Column(verbose_name="Reference Type")
    
    mode = tables.Column(verbose_name="Mode")
    
    status = tables.Column(verbose_name="Status")

    pending_review = tables.Column(empty_values=(), verbose_name="Pending Change", accessor="has_pending", order_by=("has_pending",))
    owner_group = tables.Column(verbose_name="Owner Group")
    
    updated_at = tables.DateTimeColumn(verbose_name="Updated At")

    class Meta:
        model = MDUHeader
        fields = ("ref_name", "description", "ref_type", "mode", "status", "pending_review", "owner_group", "updated_at")
        attrs = {"class": "table table-striped table-hover align-middle"}
        row_attrs = {
            "data-href": lambda record: reverse("mdu:header_detail", kwargs={"pk": record.pk}),
            "role": "button",
            "tabindex": "0",
            "class": lambda record: " ".join(
                c for c in [
                    "clickable-row",
                    ("table-secondary" if getattr(record, "status", "") == "RETIRED" else ""),
                ] if c
            ),
        }

    def render_pending_review(self, record):
        has_pending = getattr(record, "has_pending", None)
        if has_pending is None:
            has_pending = record.changes.filter(status="SUBMITTED").exists()
        if has_pending:
            return format_html('<span class="badge text-bg-warning">In review</span>')
        return ""


    def render_description(self, value):
        full = (value or "").strip()
        short = Truncator(full).chars(40, truncate="…")  # adjust char limit here
        # title= shows full text on hover (native browser tooltip)
        return format_html('<span class="truncate" title="{}">{}</span>', full, short)


class ProposedChangeTable(tables.Table):
    display_id = tables.Column(linkify=("mdu:proposed_change_detail", {"pk": tables.A("pk")}))
    class Meta:
        model = ChangeRequest
        fields = ("display_id", "header", "status", "submitted_at", "decided_at")
        attrs = {"class": "table table-striped table-hover align-middle"}

class CertTable(tables.Table):
    header = tables.Column(linkify=("mdu:header_detail", {"pk": tables.A("header_id")}))
    class Meta:
        model = MDUCert
        fields = ("header", "cert_cycle_id", "certification_status", "cert_expiry_dttm")
        attrs = {"class": "table table-striped table-hover align-middle"}
