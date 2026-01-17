import django_tables2 as tables
from django.utils.html import format_html
from .models import MDUHeader, ChangeRequest, MDUCert

class HeaderTable(tables.Table):
    ref_name = tables.Column(linkify=("mdu:header_detail", {"pk": tables.A("pk")}))
    pending_review = tables.Column(empty_values=(), verbose_name="Pending change", orderable=False)

    class Meta:
        model = MDUHeader
        fields = ("ref_name", "description", "ref_type", "mode", "status", "pending_review", "owner_group", "updated_at")
        attrs = {"class": "table table-striped table-hover align-middle"}
        row_attrs = {
            "class": lambda record: (
                "table-secondary"
                if getattr(record, "status", "") == "RETIRED"
                else ""
            )
        }

    def render_pending_review(self, record):
        # "being reviewed" == at least one submitted proposed change not yet decided
        has_pending = record.changes.filter(status="SUBMITTED").exists()
        if has_pending:
            return format_html('<span class="badge text-bg-warning">In review</span>')
        return ""

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
