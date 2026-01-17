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


def _mk_user(username, groups):
    u, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@example.com"})
    if created:
        u.set_password(PW)
        u.save()
    for g in groups:
        u.groups.add(g)
    return u


def _payload(ref_type: str, width: int, rows: int, mode: str):
    # placeholder pools
    if ref_type == "map":
        placeholders = [
            "COUNTRY_CODE", "COUNTRY_NAME", "REGION", "SEGMENT", "RISK_TIER", "LOB",
            "CLIENT_TYPE", "CURRENCY", "CHANNEL", "PRODUCT", "STATUS", "EFFECTIVE_DATE",
            "EXPIRY_DATE", "SOURCE_SYSTEM", "COMMENTS", "PRIORITY", "GROUP"
        ]
    else:
        placeholders = [
            "VALUE", "DESCRIPTION", "REASON", "CATEGORY", "SOURCE_SYSTEM",
            "STATUS", "COMMENTS", "REGION", "LOB", "PRIORITY"
        ]

    op = "REPLACE" if mode == "snapshot" else "BUILD NEW"

    # header row
    header_row = {"row_type": "header", "operation": op, "start_dt": "", "end_dt": ""}
    for i in range(1, 66):
        header_row[f"string_{i:02d}"] = ""

    labels = (placeholders * 10)[:width]
    for i, label in enumerate(labels, start=1):
        header_row[f"string_{i:02d}"] = label

    # values rows
    country_samples = [
        ("AU", "Australia"), ("PH", "Philippines"), ("SG", "Singapore"),
        ("US", "United States"), ("JP", "Japan"), ("GB", "United Kingdom")
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


class Command(BaseCommand):
    help = "Load realistic demo data for MDU"

    def handle(self, *args, **options):
        self.stdout.write("Loading MDU demo data...")

        # ✅ clean existing demo data (must be inside handle)
        if HAS_CERT:
            MDUCert.objects.all().delete()
        ChangeRequest.objects.all().delete()
        MDUHeader.objects.all().delete()

        # groups/users
        maker_g, _ = Group.objects.get_or_create(name="maker")
        steward_g, _ = Group.objects.get_or_create(name="steward")
        approver_g, _ = Group.objects.get_or_create(name="approver")

        maker1 = _mk_user("maker1", [maker_g])
        maker2 = _mk_user("maker2", [maker_g])
        _mk_user("steward1", [steward_g])
        approver1 = _mk_user("approver1", [approver_g])

        # helper: next numeric version (per header)
        def next_version_for(header):
            last = header.changes.filter(status=ChangeRequest.Status.APPROVED).order_by("-version").first()
            if last and last.version is not None:
                return last.version + 1
            return 1

        # helper: create changes
        def mk_change(header, display_id, status, creator, days_ago, payload, submitted=False, decided=False, version=None):
            now = timezone.now()
            if version is None:
                # only stamp versions for APPROVED changes (clean UX)
                version = next_version_for(header) if status == ChangeRequest.Status.APPROVED else None

            cr = ChangeRequest.objects.create(
                header=header,
                display_id=display_id,
                tracking_id=f"SES-{now:%Y%m%d}-REQ-{display_id}",
                status=status,
                version=version,
                operation_hint="Edit rows only",
                override_retired_flag="N",
                requested_by_sid=creator.username,
                primary_approver_sid=approver1.username,
                change_reason="Demo change for UX testing",
                change_ticket_ref=f"JIRA-{random.randint(1000,9999)}",
                change_category=random.choice(["Enhancement", "Correction", "Refresh"]),
                risk_impact=random.choice(["Low", "Medium", "High"]),
                request_source_channel=random.choice(["Web UI", "File load", "Email request"]),
                request_source_system=random.choice(["MDU", "Databricks", "Manual"]),
                payload_json=json.dumps(payload),
                submitted_at=(now - timedelta(days=days_ago) if submitted else None),
                decided_at=(now - timedelta(days=days_ago-1) if decided else None),
                decision_note=("Approved in demo" if status == ChangeRequest.Status.APPROVED else ""),
                created_by=creator,
                created_at=now - timedelta(days=days_ago),
            )
            return cr

        # headers
        specs = [
            ("demo_country_segment_mapA", "map", "versioning", MDUHeader.Status.ACTIVE),
            ("demo_country_segment_mapB", "map", "versioning", MDUHeader.Status.ACTIVE),
            ("demo_currency_cutoff_map", "map", "snapshot",   MDUHeader.Status.ACTIVE),
            ("demo_client_tier_map",     "map", "versioning", MDUHeader.Status.IN_REVIEW),
            ("demo_routing_map",         "map", "snapshot",   MDUHeader.Status.RETIRED),

            ("demo_blocked_swift_codes", "list", "snapshot",  MDUHeader.Status.ACTIVE),
            ("demo_blacklist_terms",     "list", "snapshot",  MDUHeader.Status.ACTIVE),
            ("demo_allowed_channels",    "list", "versioning",MDUHeader.Status.PENDING_REVIEW),
            ("demo_ops_exceptions",      "list", "versioning",MDUHeader.Status.ACTIVE),
            ("demo_list_s_04",           "list", "snapshot",  MDUHeader.Status.ACTIVE),
        ]

        # width distribution: 75% 3–8, 20% 9–15, 5% 15–20
        widths = []
        for _ in range(10):
            roll = random.random()
            if roll < 0.75:
                widths.append(random.randint(3, 8))
            elif roll < 0.95:
                widths.append(random.randint(9, 15))
            else:
                widths.append(random.randint(15, 20))

        headers = []
        for i, (ref_name, ref_type, mode, status) in enumerate(specs):
            h = MDUHeader.objects.create(
                ref_name=ref_name,
                ref_type=ref_type,
                mode=mode,
                status=status,
                owner_group=random.choice(["Payments Ops", "Compliance", "Treasury", "Risk", "Client Service"]),
                tags=",".join(random.sample(["country", "segment", "swift", "routing", "cutoff", "risk", "ops"], k=2)),
                description="Demo reference for UX testing and audit flows.",
            )
            headers.append((h, widths[i]))

        # changes + last approved
        pc_counter = 1
        for h, w in headers:
            row_count = random.randint(12, 40) if h.ref_type == "map" else random.randint(8, 25)

            payload1 = _payload(h.ref_type, w, row_count, h.mode)

            if h.status in (MDUHeader.Status.ACTIVE, MDUHeader.Status.IN_REVIEW):
                approved1 = mk_change(
                    h,
                    f"PC-2025-{pc_counter:03d}",
                    ChangeRequest.Status.APPROVED,
                    creator=maker1,
                    days_ago=random.randint(12, 25),
                    payload=payload1,
                    submitted=True,
                    decided=True,
                )
                pc_counter += 1
                h.last_approved_change = approved1
                h.save()

                # add another approved version for some refs (for version compare UI)
                if h.status == MDUHeader.Status.ACTIVE and random.random() < 0.6:
                    payload_v2 = _payload(h.ref_type, w, row_count, h.mode)
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

                # submitted pending change (catalog indicator)
                if h.status == MDUHeader.Status.ACTIVE and random.random() < 0.6:
                    payload_sub = _payload(h.ref_type, w, row_count, h.mode)
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
                payload_d = _payload(h.ref_type, w, row_count, h.mode)
                mk_change(
                    h,
                    f"PC-2025-{pc_counter:03d}",
                    ChangeRequest.Status.DRAFT,
                    creator=maker1,
                    days_ago=random.randint(1, 10),
                    payload=payload_d,
                    submitted=False,
                    decided=False,
                    version=None,
                )
                pc_counter += 1

        # certifications tied to approved version
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

            if len(active_headers) > 1:
                h1 = active_headers[1]
                v1 = h1.last_approved_change.version

                MDUCert.objects.create(
                    header=h1,
                    cert_cycle_id=f"CERT-2023-ANNUAL-v{v1}",
                    certification_status="CERTIFIED",
                    certification_scope="Snapshot",
                    certification_summary="Annual certification review",
                    certified_by_sid="approver1",
                    certified_dttm=now - timedelta(days=400),
                    cert_expiry_dttm=now - timedelta(days=5),
                    evidence_link="https://example.com/cert/demo2",
                )

        self.stdout.write(self.style.SUCCESS("Demo data loaded successfully."))
        self.stdout.write(self.style.SUCCESS("Demo users: maker1/maker2/steward1/approver1  (password: password123)"))
