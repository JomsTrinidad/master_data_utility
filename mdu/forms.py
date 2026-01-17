from django import forms
from .models import MDUHeader, ChangeRequest, MDUCert

class HeaderForm(forms.ModelForm):
    class Meta:
        model = MDUHeader
        fields = ["ref_name", "ref_type", "mode", "status", "owner_group", "tags"]
        widgets = {
            "tags": forms.TextInput(attrs={"placeholder": "Comma-separated (e.g., Country, Segmentation)"}),
        }

class ProposedChangeForm(forms.ModelForm):
    class Meta:
        model = ChangeRequest
        fields = [
            "tracking_id",
            "override_retired_flag",
            "change_reason",
            "change_ticket_ref",
            "change_category",
            "risk_impact",
            "request_source_channel",
            "request_source_system",
            "payload_json",
        ]
        widgets = {
            "payload_json": forms.Textarea(attrs={"rows": 14, "class": "mono", "placeholder": '{"rows":[{"row_type":"header",...}]}'})
        }

class CertForm(forms.ModelForm):
    class Meta:
        model = MDUCert
        fields = [
            "header",
            "cert_cycle_id",
            "certification_status",
            "certification_scope",
            "certification_summary",
            "certified_by_sid",
            "certified_dttm",
            "cert_expiry_dttm",
            "evidence_link",
            "qa_issues_found",
        ]
        widgets = {
            "certified_dttm": forms.DateTimeInput(attrs={"type":"datetime-local"}),
            "cert_expiry_dttm": forms.DateTimeInput(attrs={"type":"datetime-local"}),
        }
