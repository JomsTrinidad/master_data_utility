import json
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from django.utils import timezone

from mdu.models import MDUHeader, ChangeRequest

try:
    from mdu.models import MDUCert
    HAS_CERT = True
except Exception:
    HAS_CERT = False


PW = "password123"


def _mk_user(username: str, groups: list[Group]):
    u, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@example.com"})
    if created:
        u.set_password(PW)
        u.save()
    for g in groups:
        u.groups.add(g)
    return u


def _payload(ref_type: str, width: int, rows: int, mode: str):
    """Build a simple payload the UI can render (header row + values rows)."""
    if ref_type == "map":
        placeholders = [
            "COUNTRY_CODE", "COUNTRY_NAME", "REGION", "SEGMENT", "RISK_TIER", "LOB",
            "CLIENT_TYPE", "CURRENCY", "CHANNEL", "PRODUCT", "STATUS", "EFFECTIVE_DATE",
            "EXPIRY_DATE", "SOURCE_SYSTEM", "COMMENTS", "PRIORITY", "GROUP",
        ]
    else:
        placeholders = [
            "VALUE", "DESCRIPTION", "REASON", "CATEGORY", "SOURCE_SYSTEM",
            "STATUS", "COMMENTS", "REGION", "LOB", "PRIORITY",
        ]

    op = "REPLACE" if mode == "snapshot" else "BUILD NEW"

    header_row = {"row_type": "header", "operation": op, "start_dt": "", "end_dt": ""}
    for i in range(1, 66):
        header_row[f"string_{i:02d}"] = ""

    labels = (placeholders * 10)[:width]
    for i, label in enumerate(labels, start=1):
        header_row[f"string_{i:02d}"] = label

    country_samples = [
        ("AU", "Australia"), ("PH", "Philippines"), ("SG", "Singapore"),
        ("US", "United States"), ("JP", "Japan"), ("GB", "United Kingdom"),
    ]
    segments = ["Retail", "Commercial", "Institutional"]
    risk = ["LOW", "MED", "HIGH"]
    regions = ["APAC", "AMER", "EMEA"]

    values_rows = []
    for r in range(rows):
        row = {"row_type": "values", "operation": op, "start_dt": "", "end_dt": ""}
        for i in range(1, 66):
            row[f"string_{i:02d}"] = ""

        if ref_type == "map":
            cc, cn = random.choice(country_samples)
            row["string_01"] = cc
            if width >= 2:
                row["string_02"] = cn
            if width >= 3:
                row["string_03"] = random.choice(regions)
            if width >= 4:
                row["string_04"] = random.choice(segments)
            if width >= 5:
                row["string_05"] = random.choice(risk)
            for i in range(6, width + 1):
                row[f"string_{i:02d}"] = f"VAL_{i:02d}_{r+1}"
        else:
            row["string_01"] = f"ITEM_{r+1:03d}"
            if width >= 2:
                row["string_02"] = f"Description {r+1}"
            if width >= 3:
                row["string_03"] = random.choice(["Policy", "Sanctions", "Quality", "Ops"])
            for i in range(4, width + 1):
                row[f"string_{i:02d}"] = f"VAL_{i:02d}_{r+1}"

        values_rows.append(row)

    return {"rows": [header_row] + values_rows}



COUNTRY_CAPITALS = {
    "AU": "Canberra",
    "PH": "Manila",
    "SG": "Singapore",
    "US": "Washington",
    "JP": "Tokyo",
    "GB": "London",
    "AR": "Buenos Aires",
    "MX": "Mexico City",
    "CA": "Ottawa",
}

COUNTRY_REGION = {
    "AU": "APAC",
    "PH": "APAC",
    "SG": "APAC",
    "JP": "APAC",
    "GB": "EMEA",
    "US": "NAMR",
    "CA": "NAMR",
    "AR": "LATAM",
    "MX": "LATAM",
}

PAYMENT_TYPE_PREFIXES = ["IR", "RR", "ID", "IC", "XX"]
PAYMENT_SUB_PREFIXES = ["DL", "IL", "IF"]

PRODUCT_TYPES = [
    ("Real Time Payments", "RTP"),
    ("High Value Payments", "HV"),
    ("Low Value Payments", "LV"),
    ("Alternative Payments", "Alt"),
]

HV_CLUSTERS = ["HV_CORE", "HV_INTL", "HV_URGENT"]
LV_CLUSTERS = ["LV_BULK", "LV_PAYROLL", "LV_RETAIL"]

def _rand_code(prefixes: list[str]) -> str:
    p = random.choice(prefixes)
    tail = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(2))
    return f"{p}{tail}"

def _payload_demo_product_mapping(rows: int) -> dict:
    """Payload for demo_product_mapping (map/snapshot) with fixed columns."""
    op = "REPLACE"

    labels = [
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
    ]

    header_row = {"row_type": "header", "operation": op, "start_dt": "", "end_dt": ""}
    for i in range(1, 66):
        header_row[f"string_{i:02d}"] = ""
    for i, label in enumerate(labels, start=1):
        header_row[f"string_{i:02d}"] = label

    values_rows = []
    countries = list(COUNTRY_CAPITALS.keys())

    for r in range(rows):
        cc = random.choice(countries)
        branch_id = f"{random.randint(100, 999)}"  # stored as text
        branch_name = COUNTRY_CAPITALS.get(cc, cc)
        region = COUNTRY_REGION.get(cc, random.choice(["APAC", "EMEA", "LATAM", "NAMR"]))

        product_type, group = random.choice(PRODUCT_TYPES)
        cluster = ""
        if group == "HV":
            cluster = random.choice(HV_CLUSTERS)
        elif group == "LV":
            cluster = random.choice(LV_CLUSTERS)

        row = {"row_type": "values", "operation": op, "start_dt": "", "end_dt": ""}
        for i in range(1, 66):
            row[f"string_{i:02d}"] = ""

        row["string_01"] = branch_id
        row["string_02"] = branch_name
        row["string_03"] = cc
        row["string_04"] = region
        row["string_05"] = _rand_code(PAYMENT_TYPE_PREFIXES)
        row["string_06"] = _rand_code(PAYMENT_SUB_PREFIXES)
        row["string_07"] = product_type
        row["string_08"] = str(random.choice([0, 1]))
        row["string_09"] = group
        row["string_10"] = cluster

        values_rows.append(row)

    return {"rows": [header_row] + values_rows}

def _payload_demo_client_mailing_list(rows: int) -> dict:
    """Payload for demo_client_mailing_list (map/snapshot) with fixed columns."""
    op = "REPLACE"

    labels = [
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
    ]

    header_row = {"row_type": "header", "operation": op, "start_dt": "", "end_dt": ""}
    for i in range(1, 66):
        header_row[f"string_{i:02d}"] = ""
    for i, label in enumerate(labels, start=1):
        header_row[f"string_{i:02d}"] = label

    freqs = ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly", "Ad-hoc"]
    fmts = ["Standard", "Custom"]
    reports = [
        "Client Report Name",
        "Client Activity Summary",
        "Client Exception Register",
        "Client SLA Scorecard",
        "Client Volume Snapshot",
    ]

    values_rows = []
    countries = list(COUNTRY_CAPITALS.keys())

    for _ in range(rows):
        cc = random.choice(countries)
        branch_id = f"{random.randint(100, 999)}"  # stored as text
        branch_name = COUNTRY_CAPITALS.get(cc, cc)
        region = COUNTRY_REGION.get(cc, random.choice(["APAC", "EMEA", "LATAM", "NAMR"]))

        client_id = f"{random.randint(10**12, (10**13)-1)}"  # 13-digit text

        # Simple, clearly fake emails
        dom = random.choice(["example.com", "demo.local", "mail.test"])
        to = f"client{random.randint(1000,9999)}@{dom}"
        cc_email = f"ops{random.randint(1000,9999)}@{dom}"

        row = {"row_type": "values", "operation": op, "start_dt": "", "end_dt": ""}
        for i in range(1, 66):
            row[f"string_{i:02d}"] = ""

        row["string_01"] = branch_id
        row["string_02"] = branch_name
        row["string_03"] = cc
        row["string_04"] = region
        row["string_05"] = random.choice(reports)
        row["string_06"] = random.choice(freqs)
        row["string_07"] = random.choice(fmts)
        row["string_08"] = "EXTERNAL"
        row["string_09"] = client_id
        row["string_10"] = to
        row["string_11"] = cc_email
        row["string_12"] = ""  # mail_bcc

        values_rows.append(row)

    return {"rows": [header_row] + values_rows}

class Command(BaseCommand):
    help = "Load realistic demo data for MDU"

    def handle(self, *args, **options):
        self.stdout.write("Loading MDU demo data...")

        if HAS_CERT:
            MDUCert.objects.all().delete()
        ChangeRequest.objects.all().delete()
        MDUHeader.objects.all().delete()

        # groups/users
        viewer_g, _ = Group.objects.get_or_create(name="viewer")
        maker_g, _ = Group.objects.get_or_create(name="maker")
        steward_g, _ = Group.objects.get_or_create(name="steward")
        approver_g, _ = Group.objects.get_or_create(name="approver")
        business_owner_g, _ = Group.objects.get_or_create(name="business_owner")

        _mk_user("viewer1", [viewer_g])
        maker1 = _mk_user("maker1", [maker_g])
        maker2 = _mk_user("maker2", [maker_g])
        steward1 = _mk_user("steward1", [steward_g])
        _mk_user("steward2", [steward_g])
        approver1 = _mk_user("approver1", [approver_g])
        _mk_user("approver2", [approver_g])
        business_owner1 = _mk_user("business_owner1", [business_owner_g])

        def next_version_for(header: MDUHeader) -> int:
            last = header.changes.filter(status=ChangeRequest.Status.APPROVED).order_by("-version").first()
            if last and last.version is not None:
                return last.version + 1
            return 1

        def mk_change(
            header: MDUHeader,
            display_id: str,
            status: str,
            creator: User,
            days_ago: int,
            payload: dict,
            submitted: bool = False,
            decided: bool = False,
            version: int | None = None,
        ) -> ChangeRequest:
            now = timezone.now()
            if version is None:
                version = next_version_for(header) if status == ChangeRequest.Status.APPROVED else None

            cr = ChangeRequest.objects.create(
                header=header,
                display_id=display_id,
                collaboration_mode=header.collaboration_mode,
                tracking_id=f"SES-{now:%Y%m%d}-REQ-{display_id}",
                status=status,
                version=version,
                operation_hint="Edit rows only",
                override_retired_flag="N",
                requested_by_sid=creator.username,
                business_owner_sid=business_owner1.username,
                approver_ad_group="AD_GROUP_DEMO_APPROVERS",
                change_reason="Demo change for UX testing",
                change_ticket_ref=f"JIRA-{random.randint(1000, 9999)}",
                change_category=random.choice(
                    [
                        ChangeRequest.ChangeCategory.DATA_CORRECTION,
                        ChangeRequest.ChangeCategory.NEW_VALUE_ADD,
                        ChangeRequest.ChangeCategory.OPERATIONAL_UPDATE,
                        ChangeRequest.ChangeCategory.ENHANCEMENT,
                    ]
                ),
                payload_json=json.dumps(payload),
                submitted_at=(now - timedelta(days=days_ago) if submitted else None),
                decided_at=(now - timedelta(days=days_ago - 1) if decided else None),
                decision_note=("Approved in demo" if status == ChangeRequest.Status.APPROVED else ""),
                created_by=creator,
                created_at=now - timedelta(days=days_ago),
            )
            return cr

        specs = [
            ("demo_country_segment_mapA", "map", "versioning", MDUHeader.Status.ACTIVE),
            ("demo_country_segment_mapB", "map", "versioning", MDUHeader.Status.ACTIVE),
            ("demo_currency_cutoff_map", "map", "snapshot", MDUHeader.Status.ACTIVE),
            ("demo_client_tier_map", "map", "versioning", MDUHeader.Status.IN_REVIEW),
            ("demo_routing_map", "map", "snapshot", MDUHeader.Status.RETIRED),
            ("demo_blocked_swift_codes", "list", "snapshot", MDUHeader.Status.ACTIVE),
            ("demo_blacklist_terms", "list", "snapshot", MDUHeader.Status.ACTIVE),
            ("demo_allowed_channels", "list", "versioning", MDUHeader.Status.PENDING_REVIEW),
            ("demo_ops_exceptions", "list", "versioning", MDUHeader.Status.ACTIVE),
            # Collaborative demo reference
            ("demo_collab_allowlist_terms", "list", "versioning", MDUHeader.Status.ACTIVE),
            ("demo_product_mapping", "map", "snapshot", MDUHeader.Status.ACTIVE),
            ("demo_client_mailing_list", "map", "snapshot", MDUHeader.Status.ACTIVE),
            ("demo_list_s_04", "list", "snapshot", MDUHeader.Status.ACTIVE),
        ]

        widths = []
        for _ in range(len(specs)):
            roll = random.random()
            if roll < 0.75:
                widths.append(random.randint(3, 8))
            elif roll < 0.95:
                widths.append(random.randint(9, 15))
            else:
                widths.append(random.randint(15, 20))

        headers: list[tuple[MDUHeader, int]] = []
        for i, (ref_name, ref_type, mode, status) in enumerate(specs):
            h = MDUHeader.objects.create(
                ref_name=ref_name,
                ref_type=ref_type,
                mode=mode,
                status=status,
                collaboration_mode=(
                    MDUHeader.CollaborationMode.COLLABORATIVE
                    if (ref_name.startswith("demo_collab_") or ref_name in ("demo_product_mapping", "demo_client_mailing_list"))
                    else MDUHeader.CollaborationMode.SINGLE_OWNER
                ),
                owner_group=random.choice(["Payments Ops", "Compliance", "Treasury", "Risk", "Client Service"]),
                tags=",".join(random.sample(["country", "segment", "swift", "routing", "cutoff", "risk", "ops"], k=2)),
                description="Demo reference for UX testing and audit flows.",
            )
            headers.append((h, widths[i]))

        pc_counter = 1
        for h, w in headers:
            row_count = 24 if h.ref_name == "demo_product_mapping" else (18 if h.ref_name == "demo_client_mailing_list" else (random.randint(12, 40) if h.ref_type == "map" else random.randint(8, 25)))
            payload_base = (_payload_demo_product_mapping(row_count) if h.ref_name == "demo_product_mapping" else (_payload_demo_client_mailing_list(row_count) if h.ref_name == "demo_client_mailing_list" else _payload(h.ref_type, w, row_count, h.mode)))

            if h.status in (MDUHeader.Status.ACTIVE, MDUHeader.Status.IN_REVIEW):
                approved1 = mk_change(
                    h,
                    f"PC-2025-{pc_counter:03d}",
                    ChangeRequest.Status.APPROVED,
                    creator=maker1,
                    days_ago=random.randint(12, 25),
                    payload=payload_base,
                    submitted=True,
                    decided=True,
                )
                pc_counter += 1
                h.last_approved_change = approved1
                h.save()

                if h.status == MDUHeader.Status.ACTIVE and random.random() < 0.6:
                    payload_v2 = (_payload_demo_product_mapping(row_count) if h.ref_name == "demo_product_mapping" else (_payload_demo_client_mailing_list(row_count) if h.ref_name == "demo_client_mailing_list" else _payload(h.ref_type, w, row_count, h.mode)))
                    approved2 = mk_change(
                        h,
                        f"PC-2025-{pc_counter:03d}",
                        ChangeRequest.Status.APPROVED,
                        creator=maker1,
                        days_ago=random.randint(6, 11),
                        payload=payload_v2,
                        submitted=True,
                        decided=True,
                    )
                    pc_counter += 1
                    h.last_approved_change = approved2
                    h.save()

                if h.status == MDUHeader.Status.ACTIVE and h.collaboration_mode == MDUHeader.CollaborationMode.SINGLE_OWNER:
                    if random.random() < 0.6:
                        payload_sub = (_payload_demo_product_mapping(row_count) if h.ref_name == "demo_product_mapping" else (_payload_demo_client_mailing_list(row_count) if h.ref_name == "demo_client_mailing_list" else _payload(h.ref_type, w, row_count, h.mode)))
                        mk_change(
                            h,
                            f"PC-2025-{pc_counter:03d}",
                            ChangeRequest.Status.SUBMITTED,
                            creator=maker2,
                            days_ago=random.randint(1, 5),
                            payload=payload_sub,
                            submitted=True,
                            decided=False,
                            version=None,
                        )
                        pc_counter += 1
            else:
                mk_change(
                    h,
                    f"PC-2025-{pc_counter:03d}",
                    ChangeRequest.Status.DRAFT,
                    creator=maker1,
                    days_ago=random.randint(1, 10),
                    payload=payload_base,
                    submitted=False,
                    decided=False,
                    version=None,
                )
                pc_counter += 1

        

        # Collaborative demo: shared draft for demo_product_mapping
        pm_header = next((h for h, _ in headers if h.ref_name == "demo_product_mapping"), None)
        if pm_header:
            baseline_version = pm_header.last_approved_change.version if pm_header.last_approved_change else None
            base_payload = json.loads(pm_header.last_approved_change.payload_json) if pm_header.last_approved_change else _payload_demo_product_mapping(24)
            if isinstance(base_payload, dict):
                base_payload["meta"] = {"collab_touched_by": ["maker1"]}
            pm_draft = mk_change(
                pm_header,
                f"PC-2026-{pc_counter:03d}",
                ChangeRequest.Status.DRAFT,
                creator=maker1,
                days_ago=1,
                payload=base_payload,
                submitted=False,
                decided=False,
                version=baseline_version,
            )
            pm_draft.contributors.add(maker2)
            pm_draft.contributors.add(steward1)
            pc_counter += 1

            
        # Collaborative demo: shared draft for demo_client_mailing_list
        ml_header = next((h for h, _ in headers if h.ref_name == "demo_client_mailing_list"), None)
        if ml_header:
            baseline_version = ml_header.last_approved_change.version if ml_header.last_approved_change else None
            base_payload = json.loads(ml_header.last_approved_change.payload_json) if ml_header.last_approved_change else _payload_demo_client_mailing_list(18)
            # Mark as touched by maker1 only; demo will require maker2 to open + Save Draft before submit
            if isinstance(base_payload, dict):
                base_payload["meta"] = {"collab_touched_by": ["maker1"]}
            ml_draft = mk_change(
                ml_header,
                f"PC-2026-{pc_counter:03d}",
                ChangeRequest.Status.DRAFT,
                creator=maker1,
                days_ago=1,
                payload=base_payload,
                submitted=False,
                decided=False,
                version=baseline_version,
            )
            ml_draft.contributors.add(maker2)
            ml_draft.contributors.add(steward1)
            pc_counter += 1

        # Collaborative demo: shared draft for demo_collab_* reference
        collab_header = next((h for h, _ in headers if h.ref_name.startswith("demo_collab_")), None)
        if collab_header:
            baseline_version = collab_header.last_approved_change.version if collab_header.last_approved_change else None
            base_payload = json.loads(collab_header.last_approved_change.payload_json) if collab_header.last_approved_change else _payload("list", 6, 12, collab_header.mode)
            if isinstance(base_payload, dict):
                base_payload["meta"] = {"collab_touched_by": ["maker1"]}
            collab_draft = mk_change(
                collab_header,
                f"PC-2026-{pc_counter:03d}",
                ChangeRequest.Status.DRAFT,
                creator=maker1,
                days_ago=1,
                payload=base_payload,
                submitted=False,
                decided=False,
                version=baseline_version,
            )
            collab_draft.contributors.add(maker2)
            collab_draft.contributors.add(steward1)
            pc_counter += 1

        # certifications
        if HAS_CERT:
            now = timezone.now()
            active_headers = [h for h, _ in headers if h.status == MDUHeader.Status.ACTIVE and h.last_approved_change]
            if active_headers:
                h0 = active_headers[0]
                v0 = h0.last_approved_change.version
                MDUCert.objects.create(
                    header=h0,
                    cert_cycle_id=f"CERT-2024-ANNUAL-v{v0}",
                    certification_status="CERTIFIED",
                    certification_scope="Full dataset",
                    certification_summary="Annual certification review",
                    certified_by_sid="approver1",
                    certified_dttm=now - timedelta(days=330),
                    cert_expiry_dttm=now + timedelta(days=20),
                    evidence_link="https://example.com/cert/demo1",
                )

        self.stdout.write(self.style.SUCCESS("Demo data loaded successfully."))
        self.stdout.write(
            self.style.SUCCESS(
                "Demo users: viewer1, maker1, maker2, steward1, steward2, approver1, approver2, business_owner1  (password: password123)"
            )
        )