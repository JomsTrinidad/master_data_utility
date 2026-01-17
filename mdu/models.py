from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class MDUHeader(models.Model):
    class Status(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "Pending review"
        IN_REVIEW      = "IN_REVIEW", "In review"
        ACTIVE         = "ACTIVE", "Active"
        REJECTED       = "REJECTED", "Rejected"
        RETIRED        = "RETIRED", "Retired"

    ref_name = models.CharField(max_length=200, unique=True)
    ref_type = models.CharField(max_length=20, default="map")
    mode = models.CharField(max_length=20, default="versioning")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW)
    description = models.CharField(max_length=400, blank=True, default="")
    owner_group = models.CharField(max_length=120, blank=True, default="")
    tags = models.CharField(max_length=400, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    last_approved_change = models.ForeignKey(
        "ChangeRequest",
        on_delete=models.SET_NULL,
        null=True, blank=True,
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

    header = models.ForeignKey(MDUHeader, on_delete=models.CASCADE, related_name="changes")
    display_id = models.CharField(max_length=30, unique=True)
    tracking_id = models.CharField(max_length=80, blank=True, default="")
    version = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    operation_hint = models.CharField(max_length=40, blank=True, default="")
    override_retired_flag = models.CharField(max_length=1, default="N")

    requested_by_sid = models.CharField(max_length=40, blank=True, default="")
    primary_approver_sid = models.CharField(max_length=40, blank=True, default="")
    secondary_approver_sid = models.CharField(max_length=40, blank=True, default="")
    change_reason = models.CharField(max_length=400, blank=True, default="")
    change_ticket_ref = models.CharField(max_length=120, blank=True, default="")
    change_category = models.CharField(max_length=60, blank=True, default="")
    risk_impact = models.CharField(max_length=60, blank=True, default="")
    request_source_channel = models.CharField(max_length=60, blank=True, default="")
    request_source_system = models.CharField(max_length=60, blank=True, default="")

    payload_json = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_changes")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

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
