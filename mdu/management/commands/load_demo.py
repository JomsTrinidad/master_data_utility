import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from mdu.models import (
    ChangeRequest,
    MDUApproverScopeRule,
    MDUCert,
    MDUColumnDef,
    MDUCompositeKey,
    MDUCompositeKeyField,
    MDUHeader,
    MDUValidationRule,
)


PW = "password123"


class DisplayIdFactory:
    def __init__(self, year: int = 2026):
        self.year = year
        self.counter = 1

    def next(self) -> str:
        value = f"PC-{self.year}-{self.counter:03d}"
        self.counter += 1
        return value


def mk_user(username: str, groups: list[Group]) -> User:
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    if created:
        user.set_password(PW)
        user.save()
    for group in groups:
        user.groups.add(group)
    return user


def build_rows(columns: list[str], data_rows: list[dict[str, str]], mode: str) -> dict:
    op = "REPLACE" if mode == "snapshot" else "BUILD NEW"

    header_row = {
        "row_type": "header",
        "operation": op,
        "start_dt": "",
        "end_dt": "",
    }
    for i in range(1, 66):
        header_row[f"string_{i:02d}"] = ""

    for idx, label in enumerate(columns, start=1):
        header_row[f"string_{idx:02d}"] = label

    rows = [header_row]

    for source in data_rows:
        row = {
            "row_type": "values",
            "operation": op,
            "start_dt": "",
            "end_dt": "",
        }
        for i in range(1, 66):
            row[f"string_{i:02d}"] = ""

        for idx, _label in enumerate(columns, start=1):
            row[f"string_{idx:02d}"] = source.get(f"string_{idx:02d}", "")

        rows.append(row)

    return {"rows": rows}


def structure_snapshot(columns: list[dict], key_columns: list[str]) -> dict:
    return {
        "row_structure": columns,
        "composite_key": key_columns,
    }


def definition_payload(header_metadata: dict, columns: list[dict], key_columns: list[str]) -> dict:
    payload = {
        "header_metadata": header_metadata,
    }
    payload.update(structure_snapshot(columns, key_columns))
    return payload


def create_structure(
    header: MDUHeader,
    columns: list[dict],
    key_columns: list[str],
    normalization_rules: str = "",
) -> None:
    header.columns.all().delete()
    MDUCompositeKey.objects.filter(header=header).delete()

    created_cols = {}
    for col in columns:
        created = MDUColumnDef.objects.create(
            header=header,
            column_name=col["column_name"],
            data_type=col.get("data_type", "STRING"),
            nullable=col.get("nullable", True),
            required=col.get("required", False),
            default_value=col.get("default_value", ""),
            business_description=col.get("business_description", ""),
            ui_label=col.get("ui_label", ""),
            column_owner=col.get("column_owner", ""),
        )
        created_cols[created.column_name] = created

    composite = MDUCompositeKey.objects.create(
        header=header,
        normalization_rules=normalization_rules,
    )

    for order, col_name in enumerate(key_columns, start=1):
        MDUCompositeKeyField.objects.create(
            composite_key=composite,
            column=created_cols[col_name],
            key_order=order,
        )


def next_version_for(header: MDUHeader) -> int:
    latest = (
        header.changes.filter(status=ChangeRequest.Status.APPROVED)
        .order_by("-version")
        .first()
    )
    if latest and latest.version:
        return latest.version + 1
    return 1


def mk_change(
    *,
    id_factory: DisplayIdFactory,
    header: MDUHeader,
    creator: User,
    status: str,
    operation_hint: str,
    payload: dict,
    requested_by_sid: str,
    business_owner_sid: str,
    approver_ad_group: str,
    change_reason: str,
    change_category: str,
    days_ago: int,
    version: int | None = None,
    decision_note: str = "",
    contributors: list[User] | None = None,
) -> ChangeRequest:
    now = timezone.now()
    created_at = now - timedelta(days=days_ago)

    if version is None and status == ChangeRequest.Status.APPROVED:
        version = next_version_for(header)

    cr = ChangeRequest.objects.create(
        header=header,
        display_id=id_factory.next(),
        collaboration_mode=header.collaboration_mode,
        tracking_id=f"SES-{created_at:%Y%m%d}-{header.ref_name.upper()}",
        status=status,
        version=version,
        operation_hint=operation_hint,
        override_retired_flag="N",
        requested_by_sid=requested_by_sid,
        business_owner_sid=business_owner_sid,
        approver_ad_group=approver_ad_group,
        change_reason=change_reason,
        change_ticket_ref=f"JIRA-{1000 + id_factory.counter}",
        change_category=change_category,
        payload_json=json.dumps(payload),
        submitted_at=created_at if status in [ChangeRequest.Status.SUBMITTED, ChangeRequest.Status.APPROVED] else None,
        decided_at=(created_at + timedelta(hours=4)) if status == ChangeRequest.Status.APPROVED else None,
        decision_note=decision_note,
        decided_by_sid="approver1" if status == ChangeRequest.Status.APPROVED else "",
        created_by=creator,
        created_at=created_at,
    )
    if contributors:
        cr.contributors.add(*contributors)
    return cr


class Command(BaseCommand):
    help = "Load deterministic, workflow-focused demo data for MDU"

    def handle(self, *args, **options):
        self.stdout.write("Loading workflow-focused MDU demo data...")

        # Clean slate
        MDUCert.objects.all().delete()
        ChangeRequest.objects.all().delete()
        MDUCompositeKeyField.objects.all().delete()
        MDUCompositeKey.objects.all().delete()
        MDUColumnDef.objects.all().delete()
        MDUValidationRule.objects.all().delete()
        MDUApproverScopeRule.objects.all().delete()
        MDUHeader.objects.all().delete()

        # Groups / users
        viewer_g, _ = Group.objects.get_or_create(name="viewer")
        maker_g, _ = Group.objects.get_or_create(name="maker")
        steward_g, _ = Group.objects.get_or_create(name="steward")
        approver_g, _ = Group.objects.get_or_create(name="approver")
        bo_g, _ = Group.objects.get_or_create(name="business_owner")

        viewer1 = mk_user("viewer1", [viewer_g])
        maker1 = mk_user("maker1", [maker_g])
        maker2 = mk_user("maker2", [maker_g])
        steward1 = mk_user("steward1", [steward_g])
        steward2 = mk_user("steward2", [steward_g])
        approver1 = mk_user("approver1", [approver_g])
        approver2 = mk_user("approver2", [approver_g])
        business_owner1 = mk_user("business_owner1", [bo_g])

        _ = viewer1, approver1, approver2, steward2  # silence “unused” complaints if linted

        id_factory = DisplayIdFactory()

        # ------------------------------------------------------------------
        # Scenario 1: Active approved Product Mapping + submitted row update
        # ------------------------------------------------------------------
        product_cols = [
            {
                "column_name": "string_01",
                "ui_label": "Branch Id",
                "business_description": "Branch identifier",
                "data_type": "STRING",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_02",
                "ui_label": "Branch Name",
                "business_description": "Branch name",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_03",
                "ui_label": "Country",
                "business_description": "Country code",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_04",
                "ui_label": "Region",
                "business_description": "Geographic region",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_05",
                "ui_label": "Payment Type",
                "business_description": "Payment type code",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_06",
                "ui_label": "Payment Sub Type",
                "business_description": "Payment sub type code",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_07",
                "ui_label": "Product Type",
                "business_description": "Business product type",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_08",
                "ui_label": "Vol In Scope",
                "business_description": "In-scope flag",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_09",
                "ui_label": "CSI Product Group",
                "business_description": "CSI product group",
                "required": True,
                "nullable": False,
                "column_owner": "Payments Ops",
            },
            {
                "column_name": "string_10",
                "ui_label": "CSI Product Cluster",
                "business_description": "CSI product cluster",
                "required": False,
                "nullable": True,
                "column_owner": "Payments Ops",
            },
        ]
        product_key = ["string_01", "string_05", "string_06"]

        product_header = MDUHeader.objects.create(
            ref_name="payment_product_mapping",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Maps branch and payment attributes to CSI product grouping for downstream reporting.",
            category="Product Mapping",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.COLLABORATIVE,
            owning_domain_lob="Payments Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_PAYMENTS_APPROVERS",
            owner_group="Payments Ops",
            tags="payments,product,mapping",
            certification_required=False,
        )
        create_structure(product_header, product_cols, product_key, normalization_rules="TRIM|UPPER")

        product_live_rows = build_rows(
            [
                "branch_id",
                "branch_name",
                "country",
                "region",
                "payment_type",
                "payment_sub_type",
                "product_type",
                "vol_in_scope",
                "csi_product_group",
                "csi_product_cluster",
            ],
            [
                {
                    "string_01": "640",
                    "string_02": "Manila Main",
                    "string_03": "PH",
                    "string_04": "APAC",
                    "string_05": "IR01",
                    "string_06": "DL01",
                    "string_07": "High Value Payments",
                    "string_08": "1",
                    "string_09": "HV",
                    "string_10": "HV_CORE",
                },
                {
                    "string_01": "233",
                    "string_02": "Singapore Hub",
                    "string_03": "SG",
                    "string_04": "APAC",
                    "string_05": "RR02",
                    "string_06": "IL01",
                    "string_07": "Low Value Payments",
                    "string_08": "1",
                    "string_09": "LV",
                    "string_10": "LV_BULK",
                },
                {
                    "string_01": "101",
                    "string_02": "New York Center",
                    "string_03": "US",
                    "string_04": "NAMR",
                    "string_05": "IC03",
                    "string_06": "IF02",
                    "string_07": "Real Time Payments",
                    "string_08": "1",
                    "string_09": "RTP",
                    "string_10": "",
                },
            ],
            mode=product_header.mode,
        )

        product_approved = mk_change(
            id_factory=id_factory,
            header=product_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=product_live_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_PAYMENTS_APPROVERS",
            change_reason="Initial approved baseline for product mapping.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=20,
            decision_note="Approved baseline for demo.",
        )
        product_header.last_approved_change = product_approved
        product_header.save(update_fields=["last_approved_change"])

        product_submitted = build_rows(
            [
                "branch_id",
                "branch_name",
                "country",
                "region",
                "payment_type",
                "payment_sub_type",
                "product_type",
                "vol_in_scope",
                "csi_product_group",
                "csi_product_cluster",
            ],
            [
                {
                    "string_01": "640",
                    "string_02": "Manila Main",
                    "string_03": "PH",
                    "string_04": "APAC",
                    "string_05": "IR01",
                    "string_06": "DL01",
                    "string_07": "High Value Payments",
                    "string_08": "1",
                    "string_09": "HV",
                    "string_10": "HV_INTL",
                },
                {
                    "string_01": "233",
                    "string_02": "Singapore Hub",
                    "string_03": "SG",
                    "string_04": "APAC",
                    "string_05": "RR02",
                    "string_06": "IL01",
                    "string_07": "Low Value Payments",
                    "string_08": "1",
                    "string_09": "LV",
                    "string_10": "LV_PAYROLL",
                },
                {
                    "string_01": "771",
                    "string_02": "Sydney Gateway",
                    "string_03": "AU",
                    "string_04": "APAC",
                    "string_05": "IR02",
                    "string_06": "DL03",
                    "string_07": "Alternative Payments",
                    "string_08": "0",
                    "string_09": "Alt",
                    "string_10": "",
                },
            ],
            mode=product_header.mode,
        )

        mk_change(
            id_factory=id_factory,
            header=product_header,
            creator=maker2,
            status=ChangeRequest.Status.SUBMITTED,
            operation_hint="Edit rows only",
            payload=product_submitted,
            requested_by_sid="maker2",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_PAYMENTS_APPROVERS",
            change_reason="Submitted row update for product mapping approver demo.",
            change_category=ChangeRequest.ChangeCategory.OPERATIONAL_UPDATE,
            days_ago=2,
            version=product_approved.version,
        )

        MDUApproverScopeRule.objects.create(
            header=product_header,
            scope_type="GLOBAL",
            scope_value="GLOBAL",
            approver_ad_group="AD_MDU_PAYMENTS_APPROVERS",
            is_active=True,
        )

        # ------------------------------------------------------------------
        # Scenario 2: Active approved Client Mailing List + collaborative draft
        # ------------------------------------------------------------------
        mailing_cols = [
            {"column_name": "string_01", "ui_label": "Branch Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Branch Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Country", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Region", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Report", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_06", "ui_label": "Frequency", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_07", "ui_label": "Report Format", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_08", "ui_label": "Distro Type", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_09", "ui_label": "Client Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_10", "ui_label": "Mail To", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_11", "ui_label": "Mail Cc", "required": False, "nullable": True, "data_type": "STRING"},
            {"column_name": "string_12", "ui_label": "Mail Bcc", "required": False, "nullable": True, "data_type": "STRING"},
        ]
        mailing_key = ["string_01", "string_05", "string_09"]

        mailing_header = MDUHeader.objects.create(
            ref_name="client_report_mailing_list",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Client report distribution list used by controlled outbound reporting workflows.",
            category="Client Distribution",
            data_classification=MDUHeader.DataClassification.CLASSIFIED,
            collaboration_mode=MDUHeader.CollaborationMode.COLLABORATIVE,
            owning_domain_lob="Client Service",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_CLIENT_SERVICE_APPROVERS",
            owner_group="Client Service",
            tags="client,mailing,distribution",
            certification_required=True,
        )
        create_structure(mailing_header, mailing_cols, mailing_key, normalization_rules="TRIM|LOWER_EMAIL")

        mailing_live_rows = build_rows(
            [
                "branch_id",
                "branch_name",
                "country",
                "region",
                "report",
                "frequency",
                "report_format",
                "distro_type",
                "client_id",
                "mail_to",
                "mail_cc",
                "mail_bcc",
            ],
            [
                {
                    "string_01": "640",
                    "string_02": "Manila Main",
                    "string_03": "PH",
                    "string_04": "APAC",
                    "string_05": "Client Activity Summary",
                    "string_06": "Daily",
                    "string_07": "Standard",
                    "string_08": "EXTERNAL",
                    "string_09": "1000000000001",
                    "string_10": "client.ph@example.com",
                    "string_11": "ops.apac@example.com",
                    "string_12": "",
                },
                {
                    "string_01": "233",
                    "string_02": "Singapore Hub",
                    "string_03": "SG",
                    "string_04": "APAC",
                    "string_05": "Client SLA Scorecard",
                    "string_06": "Weekly",
                    "string_07": "Custom",
                    "string_08": "EXTERNAL",
                    "string_09": "1000000000002",
                    "string_10": "client.sg@example.com",
                    "string_11": "ops.apac@example.com",
                    "string_12": "",
                },
            ],
            mode=mailing_header.mode,
        )

        mailing_approved = mk_change(
            id_factory=id_factory,
            header=mailing_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=mailing_live_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_CLIENT_SERVICE_APPROVERS",
            change_reason="Initial approved baseline for mailing list.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=18,
            decision_note="Approved baseline for demo.",
        )
        mailing_header.last_approved_change = mailing_approved
        mailing_header.save(update_fields=["last_approved_change"])

        mailing_draft = build_rows(
            [
                "branch_id",
                "branch_name",
                "country",
                "region",
                "report",
                "frequency",
                "report_format",
                "distro_type",
                "client_id",
                "mail_to",
                "mail_cc",
                "mail_bcc",
            ],
            [
                {
                    "string_01": "640",
                    "string_02": "Manila Main",
                    "string_03": "PH",
                    "string_04": "APAC",
                    "string_05": "Client Activity Summary",
                    "string_06": "Daily",
                    "string_07": "Standard",
                    "string_08": "EXTERNAL",
                    "string_09": "1000000000001",
                    "string_10": "client.ph@example.com",
                    "string_11": "ops.apac@example.com",
                    "string_12": "",
                },
                {
                    "string_01": "640",
                    "string_02": "Manila Main",
                    "string_03": "PH",
                    "string_04": "APAC",
                    "string_05": "Client Exception Register",
                    "string_06": "Weekly",
                    "string_07": "Custom",
                    "string_08": "EXTERNAL",
                    "string_09": "1000000000003",
                    "string_10": "client.new@example.com",
                    "string_11": "service.team@example.com",
                    "string_12": "",
                },
            ],
            mode=mailing_header.mode,
        )
        mailing_draft["meta"] = {"collab_touched_by": ["maker1"]}

        mk_change(
            id_factory=id_factory,
            header=mailing_header,
            creator=maker1,
            status=ChangeRequest.Status.DRAFT,
            operation_hint="Edit rows only",
            payload=mailing_draft,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_CLIENT_SERVICE_APPROVERS",
            change_reason="Collaborative draft for mailing list demo.",
            change_category=ChangeRequest.ChangeCategory.OPERATIONAL_UPDATE,
            days_ago=1,
            version=mailing_approved.version,
            contributors=[maker2, steward1],
        )

        MDUCert.objects.create(
            header=mailing_header,
            cert_cycle_id="CERT-2026-Q2",
            certification_status="CERTIFIED",
            certification_scope="Full dataset",
            certification_summary="Quarterly mailing list attestation completed; next cycle due soon.",
            certified_by_sid="approver1",
            certified_dttm=timezone.now() - timedelta(days=70),
            cert_expiry_dttm=timezone.now() + timedelta(days=14),
            cert_version=mailing_approved.version,
            evidence_link="https://example.com/cert/client-mailing-list",
        )

        # ------------------------------------------------------------------
        # Scenario 3: Approved classified sanctions reference
        # ------------------------------------------------------------------
        sanctions_cols = [
            {"column_name": "string_01", "ui_label": "Blocked Term", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Reason", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Region", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Source System", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        sanctions_key = ["string_01", "string_03"]

        sanctions_header = MDUHeader.objects.create(
            ref_name="classified_sanctions_term_list",
            ref_type="list",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Classified sanctions screening terms with controlled visibility.",
            category="Compliance Screening",
            data_classification=MDUHeader.DataClassification.CLASSIFIED,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Compliance",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_COMPLIANCE_APPROVERS",
            owner_group="Compliance",
            tags="sanctions,classified,screening",
            certification_required=True,
        )
        create_structure(sanctions_header, sanctions_cols, sanctions_key)

        sanctions_rows = build_rows(
            ["value", "reason", "region", "source_system"],
            [
                {
                    "string_01": "BLOCKED_ENTITY_A",
                    "string_02": "Sanctions review",
                    "string_03": "GLOBAL",
                    "string_04": "Compliance",
                },
                {
                    "string_01": "BLOCKED_ENTITY_B",
                    "string_02": "Regulatory restriction",
                    "string_03": "APAC",
                    "string_04": "Compliance",
                },
            ],
            mode=sanctions_header.mode,
        )

        sanctions_approved = mk_change(
            id_factory=id_factory,
            header=sanctions_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=sanctions_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_COMPLIANCE_APPROVERS",
            change_reason="Initial approved baseline for classified reference.",
            change_category=ChangeRequest.ChangeCategory.POLICY_COMPLIANCE,
            days_ago=30,
            decision_note="Approved baseline for demo.",
        )
        sanctions_header.last_approved_change = sanctions_approved
        sanctions_header.save(update_fields=["last_approved_change"])

        MDUCert.objects.create(
            header=sanctions_header,
            cert_cycle_id="CERT-2026-COMPLIANCE",
            certification_status="CERTIFIED",
            certification_scope="Full dataset",
            certification_summary="Compliance certification in effect.",
            certified_by_sid="approver2",
            certified_dttm=timezone.now() - timedelta(days=40),
            cert_expiry_dttm=timezone.now() + timedelta(days=7),
            cert_version=sanctions_approved.version,
            evidence_link="https://example.com/cert/classified-sanctions",
        )

        # ------------------------------------------------------------------
        # Scenario 4: New reference draft in DEFINE flow
        # ------------------------------------------------------------------
        draft_define_cols = [
            {"column_name": "string_01", "ui_label": "Country", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Business Unit", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Escalation Email", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        draft_define_key = ["string_01", "string_02"]

        draft_header = MDUHeader.objects.create(
            ref_name="country_escalation_matrix",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.IN_REVIEW,
            description="Pending new reference for routing escalations by country and business unit.",
            category="Operations Routing",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Payments Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_PAYMENTS_APPROVERS",
            owner_group="Payments Ops",
            tags="routing,escalation",
            certification_required=False,
        )

        draft_define_payload = definition_payload(
            {
                "ref_name": "country_escalation_matrix",
                "description": "Pending new reference for routing escalations by country and business unit.",
                "ref_type": "map",
                "mode": "snapshot",
                "category": "Operations Routing",
                "data_classification": "GENERAL",
                "collaboration_mode": "SINGLE_OWNER",
                "approval_model": "REFERENCE_LEVEL",
                "approval_scope": "GLOBAL",
                "approver_group_mapping": "AD_MDU_PAYMENTS_APPROVERS",
                "business_owner_sid": "business_owner1",
                "certification_required": False,
            },
            draft_define_cols,
            draft_define_key,
        )

        mk_change(
            id_factory=id_factory,
            header=draft_header,
            creator=steward1,
            status=ChangeRequest.Status.DRAFT,
            operation_hint="DEFINE",
            payload=draft_define_payload,
            requested_by_sid="steward1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_PAYMENTS_APPROVERS",
            change_reason="New reference definition saved for later by steward.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=1,
        )

        # ------------------------------------------------------------------
        # Scenario 5: Existing active reference with submitted DEFINE change
        # ------------------------------------------------------------------
        holiday_cols_live = [
            {"column_name": "string_01", "ui_label": "Branch Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Business Date", "required": True, "nullable": False, "data_type": "DATE"},
            {"column_name": "string_03", "ui_label": "Date Type", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Date Description", "required": False, "nullable": True, "data_type": "STRING"},
        ]
        holiday_key_live = ["string_01", "string_02"]

        holiday_header = MDUHeader.objects.create(
            ref_name="branch_business_calendar",
            ref_type="map",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Approved branch calendar used to classify holidays and weekends.",
            category="Calendar Reference",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_OPERATIONS_APPROVERS",
            owner_group="Operations",
            tags="calendar,holiday,branch",
            certification_required=False,
        )
        create_structure(holiday_header, holiday_cols_live, holiday_key_live)

        holiday_rows = build_rows(
            ["branch_id", "business_dt", "date_type", "date_description"],
            [
                {
                    "string_01": "640",
                    "string_02": "2025-01-27",
                    "string_03": "Weekday",
                    "string_04": "",
                },
                {
                    "string_01": "640",
                    "string_02": "2025-01-28",
                    "string_03": "Holiday",
                    "string_04": "Special Holiday",
                },
            ],
            mode=holiday_header.mode,
        )

        holiday_approved = mk_change(
            id_factory=id_factory,
            header=holiday_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=holiday_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Initial approved baseline for branch calendar.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=25,
            decision_note="Approved baseline for demo.",
        )
        holiday_header.last_approved_change = holiday_approved
        holiday_header.save(update_fields=["last_approved_change"])

        holiday_define_cols = [
            {"column_name": "string_01", "ui_label": "Branch Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Business Date", "required": True, "nullable": False, "data_type": "DATE"},
            {"column_name": "string_03", "ui_label": "Date Type", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Date Description", "required": False, "nullable": True, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Region", "required": False, "nullable": True, "data_type": "STRING"},
        ]
        holiday_define_key = ["string_01", "string_02"]

        holiday_define_payload = definition_payload(
            {
                "ref_name": "branch_business_calendar",
                "description": "Submitted definition update to include Region for scoped calendar reporting.",
                "ref_type": "map",
                "mode": "versioning",
                "category": "Calendar Reference",
                "data_classification": "GENERAL",
                "collaboration_mode": "SINGLE_OWNER",
                "approval_model": "REFERENCE_LEVEL",
                "approval_scope": "GLOBAL",
                "approver_group_mapping": "AD_MDU_OPERATIONS_APPROVERS",
                "business_owner_sid": "business_owner1",
                "certification_required": False,
            },
            holiday_define_cols,
            holiday_define_key,
        )

        mk_change(
            id_factory=id_factory,
            header=holiday_header,
            creator=steward1,
            status=ChangeRequest.Status.SUBMITTED,
            operation_hint="DEFINE",
            payload=holiday_define_payload,
            requested_by_sid="steward1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Submitted definition update for approver review.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=2,
            version=holiday_approved.version,
        )

        # ------------------------------------------------------------------
        # Scenario 6: Retired reference
        # ------------------------------------------------------------------
        retired_header = MDUHeader.objects.create(
            ref_name="legacy_swift_routing_map",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.RETIRED,
            description="Legacy routing map retained for history and retirement demo.",
            category="Legacy Reference",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Treasury",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_TREASURY_APPROVERS",
            owner_group="Treasury",
            tags="legacy,routing,retired",
            certification_required=False,
        )

        # Useful validation rules for demo completeness
        MDUValidationRule.objects.create(
            header=mailing_header,
            rule_name="MAIL_TO_REQUIRED",
            rule_type="REQUIRED_IF",
            rule_config="mail_to is required for all EXTERNAL distro rows",
        )
        MDUValidationRule.objects.create(
            header=product_header,
            rule_name="VOL_IN_SCOPE_ENUM",
            rule_type="ENUM",
            rule_config="Allowed values: 0,1",
        )

        self.stdout.write(self.style.SUCCESS("Workflow-focused demo data loaded successfully."))
        self.stdout.write(
            self.style.SUCCESS(
                "Demo users: viewer1, maker1, maker2, steward1, steward2, approver1, approver2, business_owner1 (password: password123)"
            )
        )
        self.stdout.write("Suggested demo path:")
        self.stdout.write("1. Open payment_product_mapping for active approved baseline + submitted row CR.")
        self.stdout.write("2. Open client_report_mailing_list for classified/certification/collaborative draft demo.")
        self.stdout.write("3. Open country_escalation_matrix for steward DEFINE draft demo.")
        self.stdout.write("4. Open branch_business_calendar for submitted DEFINE approver demo.")
        self.stdout.write("5. Open legacy_swift_routing_map for retired reference demo.")

        # ------------------------------------------------------------------
        # Scenario 7: Country Currency Reference (simple approved list/map)
        # ------------------------------------------------------------------
        currency_cols = [
            {"column_name": "string_01", "ui_label": "Country Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Country Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Currency Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Currency Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Region", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        currency_key = ["string_01"]

        currency_header = MDUHeader.objects.create(
            ref_name="country_currency_reference",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Reference used to map countries to reporting currencies.",
            category="Geographic Reference",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Enterprise Reference Data",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_ENTERPRISE_APPROVERS",
            owner_group="Reference Data",
            tags="country,currency,reference",
            certification_required=False,
        )
        create_structure(currency_header, currency_cols, currency_key)

        currency_rows = build_rows(
            ["country_code", "country_name", "currency_code", "currency_name", "region"],
            [
                {"string_01": "PH", "string_02": "Philippines", "string_03": "PHP", "string_04": "Philippine Peso", "string_05": "APAC"},
                {"string_01": "SG", "string_02": "Singapore", "string_03": "SGD", "string_04": "Singapore Dollar", "string_05": "APAC"},
                {"string_01": "US", "string_02": "United States", "string_03": "USD", "string_04": "US Dollar", "string_05": "NAMR"},
                {"string_01": "GB", "string_02": "United Kingdom", "string_03": "GBP", "string_04": "Pound Sterling", "string_05": "EMEA"},
            ],
            mode=currency_header.mode,
        )

        currency_approved = mk_change(
            id_factory=id_factory,
            header=currency_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=currency_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_ENTERPRISE_APPROVERS",
            change_reason="Initial approved baseline for country currency reference.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=12,
            decision_note="Approved baseline for demo.",
        )
        currency_header.last_approved_change = currency_approved
        currency_header.save(update_fields=["last_approved_change"])

        # ------------------------------------------------------------------
        # Scenario 8: Investigation Queue Mapping with rejected submitted change
        # ------------------------------------------------------------------
        queue_cols = [
            {"column_name": "string_01", "ui_label": "Queue Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Queue Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "LOB", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Priority", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Manager Email", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        queue_key = ["string_01"]

        queue_header = MDUHeader.objects.create(
            ref_name="investigation_queue_mapping",
            ref_type="map",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Reference used to map investigation queues to LOB ownership and escalation contacts.",
            category="Operations Routing",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Investigations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_INVESTIGATIONS_APPROVERS",
            owner_group="Investigations",
            tags="queue,investigation,routing",
            certification_required=False,
        )
        create_structure(queue_header, queue_cols, queue_key)

        queue_rows = build_rows(
            ["queue_code", "queue_name", "lob", "priority", "manager_email"],
            [
                {"string_01": "Q100", "string_02": "APAC Payments Review", "string_03": "Payments", "string_04": "High", "string_05": "apac.review@example.com"},
                {"string_01": "Q200", "string_02": "NAMR Fraud Ops", "string_03": "Fraud", "string_04": "Critical", "string_05": "fraud.ops@example.com"},
            ],
            mode=queue_header.mode,
        )

        queue_approved = mk_change(
            id_factory=id_factory,
            header=queue_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=queue_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_INVESTIGATIONS_APPROVERS",
            change_reason="Initial approved baseline for queue mapping.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=15,
            decision_note="Approved baseline for demo.",
        )
        queue_header.last_approved_change = queue_approved
        queue_header.save(update_fields=["last_approved_change"])

        queue_define_payload = definition_payload(
            {
                "ref_name": "investigation_queue_mapping",
                "description": "Submitted definition update proposing additional regional escalation support.",
                "ref_type": "map",
                "mode": "versioning",
                "category": "Operations Routing",
                "data_classification": "GENERAL",
                "collaboration_mode": "SINGLE_OWNER",
                "approval_model": "REFERENCE_LEVEL",
                "approval_scope": "GLOBAL",
                "approver_group_mapping": "AD_MDU_INVESTIGATIONS_APPROVERS",
                "business_owner_sid": "business_owner1",
                "certification_required": False,
            },
            queue_cols + [
                {"column_name": "string_06", "ui_label": "Region", "required": False, "nullable": True, "data_type": "STRING"},
            ],
            queue_key,
        )

        mk_change(
            id_factory=id_factory,
            header=queue_header,
            creator=steward1,
            status=ChangeRequest.Status.REJECTED,
            operation_hint="DEFINE",
            payload=queue_define_payload,
            requested_by_sid="steward1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_INVESTIGATIONS_APPROVERS",
            change_reason="Definition update rejected due to incomplete downstream impact review.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=5,
            version=queue_approved.version,
            decision_note="Rejected. Regional field requires downstream consumer impact assessment before approval.",
        )

        # ------------------------------------------------------------------
        # Scenario 9: Branch Cutoff Schedule with regional approver scope
        # ------------------------------------------------------------------
        cutoff_cols = [
            {"column_name": "string_01", "ui_label": "Branch Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Region", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Cutoff Type", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Cutoff Time", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Timezone", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        cutoff_key = ["string_01", "string_03"]

        cutoff_header = MDUHeader.objects.create(
            ref_name="branch_cutoff_schedule",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Reference used to define regional branch processing cutoff schedules.",
            category="Operations Schedule",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.REGIONAL,
            approver_group_mapping="AD_MDU_GLOBAL_OPERATIONS_APPROVERS",
            owner_group="Operations",
            tags="cutoff,schedule,branch",
            certification_required=False,
        )
        create_structure(cutoff_header, cutoff_cols, cutoff_key)

        cutoff_rows = build_rows(
            ["branch_id", "region", "cutoff_type", "cutoff_time", "timezone"],
            [
                {"string_01": "640", "string_02": "APAC", "string_03": "Payments", "string_04": "17:00", "string_05": "Asia/Manila"},
                {"string_01": "233", "string_02": "APAC", "string_03": "Investigations", "string_04": "18:00", "string_05": "Asia/Singapore"},
                {"string_01": "501", "string_02": "EMEA", "string_03": "Payments", "string_04": "16:30", "string_05": "Europe/London"},
            ],
            mode=cutoff_header.mode,
        )

        cutoff_approved = mk_change(
            id_factory=id_factory,
            header=cutoff_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=cutoff_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_GLOBAL_OPERATIONS_APPROVERS",
            change_reason="Initial approved baseline for branch cutoff schedule.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=10,
            decision_note="Approved baseline for demo.",
        )
        cutoff_header.last_approved_change = cutoff_approved
        cutoff_header.save(update_fields=["last_approved_change"])

        MDUApproverScopeRule.objects.create(
            header=cutoff_header,
            scope_type="REGION",
            scope_value="APAC",
            approver_ad_group="AD_MDU_APAC_OPERATIONS_APPROVERS",
            is_active=True,
        )
        MDUApproverScopeRule.objects.create(
            header=cutoff_header,
            scope_type="REGION",
            scope_value="EMEA",
            approver_ad_group="AD_MDU_EMEA_OPERATIONS_APPROVERS",
            is_active=True,
        )

        # ------------------------------------------------------------------
        # Scenario 10: Ops Exception Reason Codes with retired/unretired row demo
        # ------------------------------------------------------------------
        exception_cols = [
            {"column_name": "string_01", "ui_label": "Reason Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Reason Description", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Active Flag", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        exception_key = ["string_01"]

        exception_header = MDUHeader.objects.create(
            ref_name="ops_exception_reason_codes",
            ref_type="list",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Operational exception reasons used for workflow tracking and root-cause reporting.",
            category="Operations Codes",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_OPERATIONS_APPROVERS",
            owner_group="Operations",
            tags="exceptions,codes,operations",
            certification_required=False,
        )
        create_structure(exception_header, exception_cols, exception_key)

        exception_rows = build_rows(
            ["reason_code", "reason_description", "active_flag"],
            [
                {"string_01": "R001", "string_02": "Client Not Reachable", "string_03": "Y"},
                {"string_01": "R002", "string_02": "Pending Documentation", "string_03": "Y"},
                {"string_01": "R003", "string_02": "System Timeout", "string_03": "Y"},
            ],
            mode=exception_header.mode,
        )

        exception_approved = mk_change(
            id_factory=id_factory,
            header=exception_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=exception_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Initial approved baseline for exception reason codes.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=8,
            decision_note="Approved baseline for demo.",
        )
        exception_header.last_approved_change = exception_approved
        exception_header.save(update_fields=["last_approved_change"])

        exception_change_payload = {
            "rows": [
                {
                    "row_type": "values",
                    "operation": "KEEP ROW",
                    "string_01": "R001",
                    "string_02": "Client Not Reachable",
                    "string_03": "Y",
                },
                {
                    "row_type": "values",
                    "operation": "UPDATE ROW",
                    "string_01": "R002",
                    "string_02": "Pending Client Documentation",
                    "string_03": "Y",
                },
                {
                    "row_type": "values",
                    "operation": "RETIRE ROW",
                    "string_01": "R003",
                    "string_02": "System Timeout",
                    "string_03": "Y",
                },
                {
                    "row_type": "values",
                    "operation": "UNRETIRE ROW",
                    "string_01": "R004",
                    "string_02": "Late Upstream Feed",
                    "string_03": "Y",
                },
                {
                    "row_type": "values",
                    "operation": "INSERT ROW",
                    "string_01": "R005",
                    "string_02": "Manual Review Triggered",
                    "string_03": "Y",
                },
            ]
        }

        mk_change(
            id_factory=id_factory,
            header=exception_header,
            creator=maker2,
            status=ChangeRequest.Status.SUBMITTED,
            operation_hint="Edit rows only",
            payload=exception_change_payload,
            requested_by_sid="maker2",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Submitted row lifecycle update for exception code demo.",
            change_category=ChangeRequest.ChangeCategory.OPERATIONAL_UPDATE,
            days_ago=1,
            version=exception_approved.version,
        )

        # ------------------------------------------------------------------
        # Scenario 11: Client Contact Restrictions with expired certification
        # ------------------------------------------------------------------
        contact_cols = [
            {"column_name": "string_01", "ui_label": "Client Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Restriction Type", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Restriction Detail", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Region", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        contact_key = ["string_01", "string_02"]

        contact_header = MDUHeader.objects.create(
            ref_name="client_contact_restrictions",
            ref_type="map",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Classified reference used to enforce client communication restrictions.",
            category="Client Controls",
            data_classification=MDUHeader.DataClassification.CLASSIFIED,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Client Service",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_CLIENT_SERVICE_APPROVERS",
            owner_group="Client Service",
            tags="client,restrictions,classified",
            certification_required=True,
        )
        create_structure(contact_header, contact_cols, contact_key)

        contact_rows = build_rows(
            ["client_id", "restriction_type", "restriction_detail", "region"],
            [
                {"string_01": "1000000000101", "string_02": "EMAIL_BLOCK", "string_03": "Do not send automated distribution", "string_04": "APAC"},
                {"string_01": "1000000000102", "string_02": "PHONE_ONLY", "string_03": "Phone outreach only", "string_04": "EMEA"},
            ],
            mode=contact_header.mode,
        )

        contact_approved = mk_change(
            id_factory=id_factory,
            header=contact_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=contact_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_CLIENT_SERVICE_APPROVERS",
            change_reason="Initial approved baseline for classified client contact restrictions.",
            change_category=ChangeRequest.ChangeCategory.POLICY_COMPLIANCE,
            days_ago=40,
            decision_note="Approved baseline for demo.",
        )
        contact_header.last_approved_change = contact_approved
        contact_header.save(update_fields=["last_approved_change"])

        MDUCert.objects.create(
            header=contact_header,
            cert_cycle_id="CERT-2026-Q1-EXPIRED",
            certification_status="EXPIRED",
            certification_scope="Full dataset",
            certification_summary="Certification expired and requires renewal before next attestation cycle.",
            certified_by_sid="approver1",
            certified_dttm=timezone.now() - timedelta(days=120),
            cert_expiry_dttm=timezone.now() - timedelta(days=5),
            cert_version=contact_approved.version,
            evidence_link="https://example.com/cert/client-contact-restrictions",
        )

        # ------------------------------------------------------------------
        # Scenario 12A: Branch Service Catalog - Snapshot version
        # ------------------------------------------------------------------
        svc_cols = [
            {"column_name": "string_01", "ui_label": "Branch Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Service Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Service Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Channel", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_05", "ui_label": "Active Flag", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        svc_key = ["string_01", "string_02"]

        svc_snapshot_header = MDUHeader.objects.create(
            ref_name="branch_service_catalog_snapshot",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Snapshot version of branch service catalog for comparing mode behavior.",
            category="Service Reference",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_OPERATIONS_APPROVERS",
            owner_group="Operations",
            tags="services,snapshot,comparison",
            certification_required=False,
        )
        create_structure(svc_snapshot_header, svc_cols, svc_key)

        svc_snapshot_rows = build_rows(
            ["branch_id", "service_code", "service_name", "channel", "active_flag"],
            [
                {"string_01": "640", "string_02": "S01", "string_03": "Same Day Transfer", "string_04": "Branch", "string_05": "Y"},
                {"string_01": "640", "string_02": "S02", "string_03": "Payroll Upload", "string_04": "Online", "string_05": "Y"},
                {"string_01": "233", "string_02": "S03", "string_03": "Bulk Payment", "string_04": "API", "string_05": "Y"},
            ],
            mode=svc_snapshot_header.mode,
        )

        svc_snapshot_approved = mk_change(
            id_factory=id_factory,
            header=svc_snapshot_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=svc_snapshot_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Approved snapshot baseline for comparison.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=9,
            decision_note="Approved baseline for demo.",
        )
        svc_snapshot_header.last_approved_change = svc_snapshot_approved
        svc_snapshot_header.save(update_fields=["last_approved_change"])

        # ------------------------------------------------------------------
        # Scenario 12B: Branch Service Catalog - Versioning version
        # ------------------------------------------------------------------
        svc_versioning_header = MDUHeader.objects.create(
            ref_name="branch_service_catalog_versioning",
            ref_type="map",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Versioning version of branch service catalog for comparing mode behavior.",
            category="Service Reference",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Operations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_OPERATIONS_APPROVERS",
            owner_group="Operations",
            tags="services,versioning,comparison",
            certification_required=False,
        )
        create_structure(svc_versioning_header, svc_cols, svc_key)

        svc_versioning_rows = build_rows(
            ["branch_id", "service_code", "service_name", "channel", "active_flag"],
            [
                {"string_01": "640", "string_02": "S01", "string_03": "Same Day Transfer", "string_04": "Branch", "string_05": "Y"},
                {"string_01": "640", "string_02": "S02", "string_03": "Payroll Upload", "string_04": "Online", "string_05": "Y"},
                {"string_01": "233", "string_02": "S03", "string_03": "Bulk Payment", "string_04": "API", "string_05": "Y"},
            ],
            mode=svc_versioning_header.mode,
        )

        svc_versioning_approved = mk_change(
            id_factory=id_factory,
            header=svc_versioning_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=svc_versioning_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_OPERATIONS_APPROVERS",
            change_reason="Approved versioning baseline for comparison.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=9,
            decision_note="Approved baseline for demo.",
        )
        svc_versioning_header.last_approved_change = svc_versioning_approved
        svc_versioning_header.save(update_fields=["last_approved_change"])

        # ------------------------------------------------------------------
        # Scenario 13A: Client Reporting Contacts - General
        # ------------------------------------------------------------------
        crc_cols = [
            {"column_name": "string_01", "ui_label": "Client Id", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Client Name", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Contact Email", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_04", "ui_label": "Report Name", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        crc_key = ["string_01", "string_04"]

        crc_general_header = MDUHeader.objects.create(
            ref_name="client_reporting_contacts_general",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="General reference for non-sensitive reporting contact examples.",
            category="Client Distribution",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Client Service",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_CLIENT_SERVICE_APPROVERS",
            owner_group="Client Service",
            tags="client,contacts,general",
            certification_required=False,
        )
        create_structure(crc_general_header, crc_cols, crc_key)

        crc_general_rows = build_rows(
            ["client_id", "client_name", "contact_email", "report_name"],
            [
                {"string_01": "200000000001", "string_02": "Acme Holdings", "string_03": "ops@acme.example.com", "string_04": "Weekly KPI"},
                {"string_01": "200000000002", "string_02": "Northstar Group", "string_03": "reporting@northstar.example.com", "string_04": "Monthly Service Review"},
            ],
            mode=crc_general_header.mode,
        )

        crc_general_approved = mk_change(
            id_factory=id_factory,
            header=crc_general_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=crc_general_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_CLIENT_SERVICE_APPROVERS",
            change_reason="Approved general client reporting contacts baseline.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=11,
            decision_note="Approved baseline for demo.",
        )
        crc_general_header.last_approved_change = crc_general_approved
        crc_general_header.save(update_fields=["last_approved_change"])

        # ------------------------------------------------------------------
        # Scenario 13B: Client Reporting Contacts - Classified
        # ------------------------------------------------------------------
        crc_classified_header = MDUHeader.objects.create(
            ref_name="client_reporting_contacts_classified",
            ref_type="map",
            mode="snapshot",
            status=MDUHeader.Status.ACTIVE,
            description="Classified version of client reporting contacts for controlled visibility comparison.",
            category="Client Distribution",
            data_classification=MDUHeader.DataClassification.CLASSIFIED,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Client Service",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_CLIENT_SERVICE_APPROVERS",
            owner_group="Client Service",
            tags="client,contacts,classified",
            certification_required=True,
        )
        create_structure(crc_classified_header, crc_cols, crc_key)

        crc_classified_rows = build_rows(
            ["client_id", "client_name", "contact_email", "report_name"],
            [
                {"string_01": "300000000001", "string_02": "Redwood Capital", "string_03": "restricted@redwood.example.com", "string_04": "Executive Exception Report"},
                {"string_01": "300000000002", "string_02": "Helios Treasury", "string_03": "private@helios.example.com", "string_04": "Daily Exposure Summary"},
            ],
            mode=crc_classified_header.mode,
        )

        crc_classified_approved = mk_change(
            id_factory=id_factory,
            header=crc_classified_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=crc_classified_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_CLIENT_SERVICE_APPROVERS",
            change_reason="Approved classified client reporting contacts baseline.",
            change_category=ChangeRequest.ChangeCategory.POLICY_COMPLIANCE,
            days_ago=11,
            decision_note="Approved baseline for demo.",
        )
        crc_classified_header.last_approved_change = crc_classified_approved
        crc_classified_header.save(update_fields=["last_approved_change"])

        MDUCert.objects.create(
            header=crc_classified_header,
            cert_cycle_id="CERT-2026-Q2-CLIENT-CONTACTS",
            certification_status="CERTIFIED",
            certification_scope="Full dataset",
            certification_summary="Certified classified contact reference for controlled distribution.",
            certified_by_sid="approver1",
            certified_dttm=timezone.now() - timedelta(days=20),
            cert_expiry_dttm=timezone.now() + timedelta(days=30),
            cert_version=crc_classified_approved.version,
            evidence_link="https://example.com/cert/client-reporting-contacts-classified",
        )

        # ------------------------------------------------------------------
        # Scenario 14A: Investigation Disposition Codes - Single Owner
        # ------------------------------------------------------------------
        disp_cols = [
            {"column_name": "string_01", "ui_label": "Disposition Code", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_02", "ui_label": "Disposition Description", "required": True, "nullable": False, "data_type": "STRING"},
            {"column_name": "string_03", "ui_label": "Severity", "required": True, "nullable": False, "data_type": "STRING"},
        ]
        disp_key = ["string_01"]

        disp_single_header = MDUHeader.objects.create(
            ref_name="investigation_disposition_codes_single_owner",
            ref_type="list",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Single-owner disposition code reference for comparison with collaborative mode.",
            category="Investigations",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.SINGLE_OWNER,
            owning_domain_lob="Investigations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_INVESTIGATIONS_APPROVERS",
            owner_group="Investigations",
            tags="investigations,disposition,single-owner",
            certification_required=False,
        )
        create_structure(disp_single_header, disp_cols, disp_key)

        disp_single_rows = build_rows(
            ["disposition_code", "disposition_description", "severity"],
            [
                {"string_01": "D01", "string_02": "Closed - Valid", "string_03": "Low"},
                {"string_01": "D02", "string_02": "Escalated", "string_03": "High"},
                {"string_01": "D03", "string_02": "Pending Review", "string_03": "Medium"},
            ],
            mode=disp_single_header.mode,
        )

        disp_single_approved = mk_change(
            id_factory=id_factory,
            header=disp_single_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=disp_single_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_INVESTIGATIONS_APPROVERS",
            change_reason="Approved single-owner disposition baseline.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=7,
            decision_note="Approved baseline for demo.",
        )
        disp_single_header.last_approved_change = disp_single_approved
        disp_single_header.save(update_fields=["last_approved_change"])

        # ------------------------------------------------------------------
        # Scenario 14B: Investigation Disposition Codes - Collaborative
        # ------------------------------------------------------------------
        disp_collab_header = MDUHeader.objects.create(
            ref_name="investigation_disposition_codes_collaborative",
            ref_type="list",
            mode="versioning",
            status=MDUHeader.Status.ACTIVE,
            description="Collaborative disposition code reference for comparison with single-owner mode.",
            category="Investigations",
            data_classification=MDUHeader.DataClassification.GENERAL,
            collaboration_mode=MDUHeader.CollaborationMode.COLLABORATIVE,
            owning_domain_lob="Investigations",
            approval_model=MDUHeader.ApprovalModel.REFERENCE_LEVEL,
            approval_scope=MDUHeader.ApprovalScope.GLOBAL,
            approver_group_mapping="AD_MDU_INVESTIGATIONS_APPROVERS",
            owner_group="Investigations",
            tags="investigations,disposition,collaborative",
            certification_required=False,
        )
        create_structure(disp_collab_header, disp_cols, disp_key)

        disp_collab_rows = build_rows(
            ["disposition_code", "disposition_description", "severity"],
            [
                {"string_01": "D01", "string_02": "Closed - Valid", "string_03": "Low"},
                {"string_01": "D02", "string_02": "Escalated", "string_03": "High"},
                {"string_01": "D03", "string_02": "Pending Review", "string_03": "Medium"},
            ],
            mode=disp_collab_header.mode,
        )

        disp_collab_approved = mk_change(
            id_factory=id_factory,
            header=disp_collab_header,
            creator=maker1,
            status=ChangeRequest.Status.APPROVED,
            operation_hint="Edit rows only",
            payload=disp_collab_rows,
            requested_by_sid="maker1",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_INVESTIGATIONS_APPROVERS",
            change_reason="Approved collaborative disposition baseline.",
            change_category=ChangeRequest.ChangeCategory.ENHANCEMENT,
            days_ago=7,
            decision_note="Approved baseline for demo.",
        )
        disp_collab_header.last_approved_change = disp_collab_approved
        disp_collab_header.save(update_fields=["last_approved_change"])

        disp_collab_draft = build_rows(
            ["disposition_code", "disposition_description", "severity"],
            [
                {"string_01": "D01", "string_02": "Closed - Valid", "string_03": "Low"},
                {"string_01": "D02", "string_02": "Escalated to Regional Team", "string_03": "High"},
                {"string_01": "D03", "string_02": "Pending Review", "string_03": "Medium"},
                {"string_01": "D04", "string_02": "Awaiting Client Response", "string_03": "Medium"},
            ],
            mode=disp_collab_header.mode,
        )
        disp_collab_draft["meta"] = {"collab_touched_by": ["maker1", "maker2"]}

        mk_change(
            id_factory=id_factory,
            header=disp_collab_header,
            creator=maker2,
            status=ChangeRequest.Status.DRAFT,
            operation_hint="Edit rows only",
            payload=disp_collab_draft,
            requested_by_sid="maker2",
            business_owner_sid="business_owner1",
            approver_ad_group="AD_MDU_INVESTIGATIONS_APPROVERS",
            change_reason="Collaborative draft update for comparison demo.",
            change_category=ChangeRequest.ChangeCategory.OPERATIONAL_UPDATE,
            days_ago=1,
            version=disp_collab_approved.version,
            contributors=[maker1, steward1],
        )