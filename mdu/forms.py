from django import forms
from .models import MDUHeader, ChangeRequest, MDUCert


class HeaderForm(forms.ModelForm):
    class Meta:
        model = MDUHeader
        fields = [
            # Identity & governance
            "ref_name",
            "description",
            "category",
            "data_classification",
            "collaboration_mode",
            "owning_domain_lob",

            # Existing
            "ref_type",
            "mode",
            "status",
            "owner_group",
            "tags",

            # Workflow config
            "approval_model",
            "approval_scope",
            "approver_group_mapping",

            # Lifecycle semantics (captured here; enforced later)
            "effective_dating_rules",
            "history_retention_expectations",
        ]
        widgets = {
            "tags": forms.TextInput(attrs={"placeholder": "Comma-separated (e.g., Country, Segmentation)"}),
            "approver_group_mapping": forms.Textarea(attrs={"rows": 3}),
        }


class ProposedChangeForm(forms.ModelForm):
    class Meta:
        model = ChangeRequest
        fields = [
            "tracking_id",

            # Steward/approver-managed governance metadata (makers read-only)
            "requested_by_sid",
            "business_owner_sid",
            "approver_ad_group",
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
            "business_owner_sid": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "e.g., bo123"}),
            "approver_ad_group": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "e.g., AD_GROUP_PAYMENTS_APPROVERS"}),
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
