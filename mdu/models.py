from __future__ import annotations

import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class MDUHeader(models.Model):
    class Status(models.TextChoices):
        # Locked lifecycle statuses across MDU (and later loader)
        ACTIVE = "ACTIVE", "Active"
        IN_REVIEW = "IN_REVIEW", "In Review"
        RETIRED = "RETIRED", "Retired"

    class DataClassification(models.TextChoices):
        GENERAL = "GENERAL", "GENERAL Reference Data"
        CLASSIFIED = "CLASSIFIED", "CLASSIFIED Reference Data"

    class CollaborationMode(models.TextChoices):
        SINGLE_OWNER = "SINGLE_OWNER", "Single-owner"
        COLLABORATIVE = "COLLABORATIVE", "Collaborative"

    class ApprovalModel(models.TextChoices):
        REFERENCE_LEVEL = "REFERENCE_LEVEL", "Reference-level"
        ROW_LEVEL = "ROW_LEVEL", "Row-level"

    class ApprovalScope(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        REGIONAL = "REGIONAL", "Regional"

    ref_name = models.CharField(max_length=200, unique=True)
    ref_type = models.CharField(max_length=20, default="map")
    mode = models.CharField(max_length=20, default="versioning")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_REVIEW)

    # Existing fields
    description = models.CharField(max_length=400, blank=True, default="")
    owner_group = models.CharField(max_length=120, blank=True, default="")
    tags = models.CharField(max_length=400, blank=True, default="")

    # --- Priority #1: Governance & workflow configuration (Option B) ---
    category = models.CharField(max_length=120, blank=True, default="")
    data_classification = models.CharField(
        max_length=20,
        choices=DataClassification.choices,
        default=DataClassification.GENERAL,
    )
    collaboration_mode = models.CharField(
        max_length=20,
        choices=CollaborationMode.choices,
        default=CollaborationMode.SINGLE_OWNER,
    )
    owning_domain_lob = models.CharField(max_length=120, blank=True, default="")

    approval_model = models.CharField(
        max_length=30,
        choices=ApprovalModel.choices,
        default=ApprovalModel.REFERENCE_LEVEL,
    )
    approval_scope = models.CharField(
        max_length=20,
        choices=ApprovalScope.choices,
        default=ApprovalScope.GLOBAL,
    )

    # “Approver group mapping” is stored as text in Django (no UI JSON exposure required).
    approver_group_mapping = models.TextField(blank=True, default="")

    # Lifecycle semantics placeholders (configured here; enforced later in UI rules/state)
    effective_dating_rules = models.CharField(max_length=200, blank=True, default="")
    history_retention_expectations = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    last_approved_change = models.ForeignKey(
        "ChangeRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="as_last_for_headers",
    )

    def __str__(self):
        return self.ref_name


class ChangeRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    class ChangeCategory(models.TextChoices):
        NONE = "", "— Select —"
        DATA_CORRECTION = "DATA_CORRECTION", "Data Correction"
        NEW_VALUE_ADD = "NEW_VALUE_ADD", "New Value Add"
        POLICY_COMPLIANCE = "POLICY_COMPLIANCE", "Policy / Compliance"
        OPERATIONAL_UPDATE = "OPERATIONAL_UPDATE", "Operational Update"
        ENHANCEMENT = "ENHANCEMENT", "Enhancement"
        OTHER = "OTHER", "Other"

    class CollaborationMode(models.TextChoices):
        SINGLE_OWNER = "SINGLE_OWNER", "Single-owner"
        COLLABORATIVE = "COLLABORATIVE", "Collaborative"

    class DDAReviewStatus(models.TextChoices):
        NOT_REQUIRED = "NOT_REQUIRED", "Not required"
        REQUIRED = "REQUIRED", "Required"
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="changes")
    display_id = models.CharField(max_length=30, unique=True)

    # --- Multi-window / duplicate submit protection (Priority #1) ---
    draft_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    lock_version = models.PositiveIntegerField(default=1)

    # Snapshot of collaboration mode at the time the CR is created (enables DB constraint)
    collaboration_mode = models.CharField(
        max_length=20,
        choices=CollaborationMode.choices,
        default=CollaborationMode.SINGLE_OWNER,
    )

    tracking_id = models.CharField(max_length=80, blank=True, default="")
    version = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    operation_hint = models.CharField(max_length=40, blank=True, default="")
    override_retired_flag = models.CharField(max_length=1, default="N")

    # --- DDA Review Gate (Priority #1: data model only; enforcement later) ---
    dda_review_status = models.CharField(
        max_length=20,
        choices=DDAReviewStatus.choices,
        default=DDAReviewStatus.NOT_REQUIRED,
    )

    requested_by_sid = models.CharField(max_length=40, blank=True, default="")
    business_owner_sid = models.CharField(max_length=40, blank=True, default="")
    approver_ad_group = models.CharField(max_length=120, blank=True, default="")
    change_reason = models.CharField(max_length=400, blank=True, default="")
    change_ticket_ref = models.CharField(max_length=120, blank=True, default="")
    change_category = models.CharField(
        max_length=60,
        choices=ChangeCategory.choices,
        blank=True,
        default=ChangeCategory.NONE,
    )
    risk_impact = models.CharField(max_length=60, blank=True, default="")
    request_source_channel = models.CharField(max_length=60, blank=True, default="")
    request_source_system = models.CharField(max_length=60, blank=True, default="")

    payload_json = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    decided_by_sid = models.CharField(max_length=40, blank=True, default="")

    override_scope_flag = models.BooleanField(default=False)
    override_scope_reason = models.CharField(max_length=400, blank=True, default="")

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_changes"
    )

    # Collaborative mode: allow multiple contributors to work on the same draft.
    # For SINGLE_OWNER references this remains unused.
    contributors = models.ManyToManyField(
        User,
        blank=True,
        related_name="collab_changes",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    bulk_add_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            # DB layer: one SUBMITTED Change Request per header for non-collab references.
            # (DRAFTs are allowed; only SUBMITTED is restricted.)
            models.UniqueConstraint(
                fields=["header", "collaboration_mode"],
                condition=models.Q(status="SUBMITTED", collaboration_mode="SINGLE_OWNER"),
                name="uniq_submitted_cr_per_header_single_owner",
            )
        ]


    def __str__(self):
        return self.display_id


class MDUCert(models.Model):
    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="certs")
    cert_cycle_id = models.CharField(max_length=40)
    certification_status = models.CharField(max_length=30, default="CERTIFIED")
    certification_scope = models.CharField(max_length=60, blank=True, default="")
    certification_summary = models.CharField(max_length=400, blank=True, default="")
    certified_by_sid = models.CharField(max_length=40, blank=True, default="")
    certified_dttm = models.DateTimeField(null=True, blank=True)
    cert_expiry_dttm = models.DateTimeField(null=True, blank=True)
    cert_version = models.IntegerField(null=True, blank=True)

    evidence_link = models.CharField(max_length=400, blank=True, default="")
    qa_issues_found = models.CharField(max_length=400, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    @property
    def is_expired(self):
        return self.cert_expiry_dttm and self.cert_expiry_dttm < timezone.now()

    @property
    def is_expiring_soon(self):
        if not self.cert_expiry_dttm:
            return False
        now = timezone.now()
        return now <= self.cert_expiry_dttm <= (now + timezone.timedelta(days=30))

    def __str__(self):
        return f"{self.header.ref_name} · {self.cert_cycle_id}"


# ------------------------------
# Priority #1: Schema Governance
# ------------------------------

class MDUColumnGroup(models.Model):
    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="column_groups")
    group_name = models.CharField(max_length=80)
    owner_group = models.CharField(max_length=120, blank=True, default="")

    # Governance rules (enforced later in UI rules/state)
    required_on_insert = models.BooleanField(default=False)
    dependency_rules = models.TextField(blank=True, default="")
    notification_rules = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["header", "group_name"], name="uniq_col_group_per_header")
        ]

    def __str__(self):
        return f"{self.header.ref_name} · {self.group_name}"


class MDUColumnDef(models.Model):
    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="columns")
    column_name = models.CharField(max_length=40)  # e.g., string_01
    data_type = models.CharField(max_length=40, blank=True, default="STRING")

    nullable = models.BooleanField(default=True)
    required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=200, blank=True, default="")

    business_description = models.CharField(max_length=400, blank=True, default="")
    ui_label = models.CharField(max_length=120, blank=True, default="")  # Title Case enforced later

    column_group = models.ForeignKey(
        MDUColumnGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="columns"
    )

    column_owner = models.CharField(max_length=120, blank=True, default="")  # role/group label

    # Deprecation metadata-only; masking handled in consumer views (Priority #3)
    is_deprecated = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["header", "column_name"], name="uniq_col_name_per_header")
        ]

    def __str__(self):
        return f"{self.header.ref_name} · {self.column_name}"


class MDUCompositeKey(models.Model):
    header = models.OneToOneField(MDUHeader, on_delete=models.CASCADE, related_name="composite_key")
    normalization_rules = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.header.ref_name} · composite key"


class MDUCompositeKeyField(models.Model):
    composite_key = models.ForeignKey(MDUCompositeKey, on_delete=models.CASCADE, related_name="fields")
    column = models.ForeignKey(MDUColumnDef, on_delete=models.CASCADE, related_name="as_key_field")
    key_order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["composite_key", "column"], name="uniq_key_field_per_key"),
            models.UniqueConstraint(fields=["composite_key", "key_order"], name="uniq_key_order_per_key"),
        ]

    def __str__(self):
        return f"{self.composite_key.header.ref_name} · key[{self.key_order}]={self.column.column_name}"


class MDUValidationRule(models.Model):
    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="validation_rules")
    rule_name = models.CharField(max_length=120)
    rule_type = models.CharField(max_length=60)  # e.g., REQUIRED_IF, REGEX, ENUM, etc. (enforced later)
    rule_config = models.TextField(blank=True, default="")
    applies_to_group = models.ForeignKey(
        MDUColumnGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="validation_rules"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["header", "rule_name"], name="uniq_rule_name_per_header")
        ]

    def __str__(self):
        return f"{self.header.ref_name} · {self.rule_name}"


class MDUApproverScopeRule(models.Model):
    class ScopeType(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        REGIONAL = "REGIONAL", "Regional"
        LOB = "LOB", "LOB"
        DOMAIN = "DOMAIN", "Domain"

    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="approver_scope_rules")

    scope_type = models.CharField(
        max_length=20,
        choices=ScopeType.choices,
        default=ScopeType.GLOBAL,
    )
    scope_value = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Example: GLOBAL, APAC, EMEA, NAM, OPS, CSI",
    )

    approver_ad_group = models.CharField(max_length=120)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["header", "scope_type", "scope_value", "approver_ad_group"],
                name="uniq_scope_rule_per_header",
            )
        ]

    def __str__(self):
        sv = self.scope_value or "—"
        return f"{self.header.ref_name} · {self.scope_type}:{sv} · {self.approver_ad_group}"


# ------------------------------
# Priority #1: Audit & Traceability
# ------------------------------

class MDUChangeRowAudit(models.Model):
    class Operation(models.TextChoices):
        INSERT_ROW = "INSERT ROW", "INSERT ROW"
        UPDATE_ROW = "UPDATE ROW", "UPDATE ROW"
        KEEP_ROW = "KEEP ROW", "KEEP ROW"
        RETIRE_ROW = "RETIRE ROW", "RETIRE ROW"
        UNRETIRE_ROW = "UNRETIRE ROW", "UNRETIRE ROW"

    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE, related_name="row_audits")

    row_index = models.IntegerField()  # index within payload at time of capture
    operation = models.CharField(max_length=20, choices=Operation.choices)

    # Identity fields (may be filled by loader later; stored here for audit completeness)
    entity_id = models.CharField(max_length=64, blank=True, default="")
    row_id = models.CharField(max_length=64, blank=True, default="")
    prior_row_id = models.CharField(max_length=64, blank=True, default="")

    # System-owned targeting input for UPDATE/RETIRE/UNRETIRE (as per your semantics)
    update_rowid = models.CharField(max_length=128, blank=True, default="")

    is_current = models.CharField(max_length=1, blank=True, default="")     # expected 'Y'/'N' post-load
    deleted_flag = models.CharField(max_length=1, blank=True, default="")   # expected 'Y'/'N' post-load

    effective_start_dttm = models.DateTimeField(null=True, blank=True)
    effective_end_dttm = models.DateTimeField(null=True, blank=True)

    modified_dttm = models.DateTimeField(null=True, blank=True)
    modified_by = models.CharField(max_length=120, blank=True, default="")

    # Snapshot of business values for “what changed” traceability (kept opaque to users)
    row_payload_json = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["change_request", "operation"]),
        ]

    def __str__(self):
        return f"{self.change_request.display_id} · row[{self.row_index}] · {self.operation}"
