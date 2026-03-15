from django import forms
from django.conf import settings
from .models import MDUHeader, ChangeRequest, MDUCert


class HeaderForm(forms.ModelForm):
    # Multi-select Business Function — stored comma-separated in owning_domain_lob
    owning_domain_lob = forms.MultipleChoiceField(
        choices=[],          # populated in __init__ from settings
        required=False,
        label="Business Function",
        widget=forms.CheckboxSelectMultiple,
    )

    # Approver Group — real ChoiceField populated from settings
    approver_group_mapping = forms.ChoiceField(
        choices=[],          # populated in __init__
        required=True,
        label="Approver Group",
    )

    # Category — dropdown from settings
    category = forms.ChoiceField(
        choices=[],          # populated in __init__
        required=False,
        label="Category",
    )

    # Description — enforce required server-side (model field is blank=True for legacy reasons)
    description = forms.CharField(
        required=True,
        label="Description",
        max_length=400,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Description is required."},
    )

    # Certification Required — stored on header.certification_required
    certification_required = forms.BooleanField(
        required=False,
        label="Certification Required",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Business Function choices
        bf_choices = getattr(settings, "BUSINESS_FUNCTION_CHOICES", [])
        self.fields["owning_domain_lob"].choices = bf_choices

        # Approver Group choices from settings; blank sentinel first
        ag_choices = [("", "Select Approver Group")] + list(
            getattr(settings, "APPROVER_GROUP_CHOICES", [])
        )
        self.fields["approver_group_mapping"].choices = ag_choices

        # Category choices from settings
        self.fields["category"].choices = getattr(
            settings, "REFERENCE_CATEGORY_CHOICES", [("", "— Select Category —")]
        )

        # Default Data Change Mode to 'snapshot' for new (unsaved) instances
        if not (self.instance and self.instance.pk):
            self.initial.setdefault('mode', 'snapshot')

        # Pre-populate from comma-separated string stored in the model
        if self.instance and self.instance.pk:
            raw = self.instance.owning_domain_lob or ""
            self.initial["owning_domain_lob"] = [v.strip() for v in raw.split(",") if v.strip()]

            # Pre-populate certification_required from model
            self.initial["certification_required"] = self.instance.certification_required

    def clean_owning_domain_lob(self):
        values = self.cleaned_data.get("owning_domain_lob") or []
        return ",".join(values)

    def clean_approver_group_mapping(self):
        val = (self.cleaned_data.get("approver_group_mapping") or "").strip()
        if not val:
            raise forms.ValidationError("Approver Group is required.")
        return val

    def clean_category(self):
        # Allow blank — category is optional
        return self.cleaned_data.get("category") or ""

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
            "tags",

            # Workflow config
            "approval_model",
            "approval_scope",
            "approver_group_mapping",

            # Certification
            "certification_required",
        ]
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