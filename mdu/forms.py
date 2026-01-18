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

            # Steward/approver-managed governance metadata (makers read-only)
            "requested_by_sid",
            "primary_approver_sid",
            "secondary_approver_sid",
            "version",
            "operation_hint",

            # Maker-managed submission metadata
            "change_reason",
            "change_ticket_ref",
            "change_category",

            # Hidden payload store
            "payload_json",
        ]
        widgets = {
            "requested_by_sid": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "e.g., jdoe123"}),
            "primary_approver_sid": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "e.g., mgr456"}),
            "secondary_approver_sid": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Optional"}),
            "version": forms.NumberInput(attrs={"class": "form-control form-control-sm", "placeholder": "Leave blank"}),
            "operation_hint": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Optional"}),
            "payload_json": forms.Textarea(attrs={"rows": 14, "class": "mono", "placeholder": '{"rows":[{"row_type":"header",...}]}'}),
            "change_category": forms.Select(attrs={"class": "form-select form-select-sm"}),

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
            "certified_dttm": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "cert_expiry_dttm": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
