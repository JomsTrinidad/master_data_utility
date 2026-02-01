from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid

def close_extra_open_change_requests(apps, schema_editor):
    ChangeRequest = apps.get_model("mdu", "ChangeRequest")
    now = django.utils.timezone.now()

    open_statuses = ["DRAFT", "SUBMITTED"]

    header_ids = (
        ChangeRequest.objects.filter(status__in=open_statuses)
        .values_list("header_id", flat=True)
        .distinct()
    )

    for hid in header_ids.iterator():
        open_qs = (
            ChangeRequest.objects.filter(header_id=hid, status__in=open_statuses)
            .order_by("-updated_at", "-id")
        )
        keep = open_qs.first()
        if not keep:
            continue

        # Close all other open CRs for this header
        extras = open_qs.exclude(pk=keep.pk)
        for ch in extras.iterator():
            ch.status = "REJECTED"
            ch.decided_at = now
            if not (ch.decision_note or "").strip():
                ch.decision_note = (
                    "Auto-closed during migration to enforce one open Change Request per reference."
                )
            ch.save(update_fields=["status", "decided_at", "decision_note"])



def backfill_draft_uuid(apps, schema_editor):
    ChangeRequest = apps.get_model("mdu", "ChangeRequest")

    # Fill only rows that don't have a UUID yet (fresh DB will have none, existing DB might).
    qs = ChangeRequest.objects.filter(draft_uuid__isnull=True)

    # Use iterator() to avoid loading everything at once.
    for ch in qs.iterator():
        ch.draft_uuid = uuid.uuid4()
        ch.save(update_fields=["draft_uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("mdu", "0006_changerequest_change_category_choices"),
    ]

    operations = [
        # --------------------
        # MDUHeader: new fields
        # --------------------
        migrations.AddField(
            model_name="mduheader",
            name="category",
            field=models.CharField(blank=True, default="", max_length=120),
            
        ),
        migrations.RunPython(close_extra_open_change_requests, migrations.RunPython.noop),

        migrations.AddField(
            model_name="mduheader",
            name="data_classification",
            field=models.CharField(
                choices=[("GENERAL", "GENERAL Reference Data"), ("CLASSIFIED", "CLASSIFIED Reference Data")],
                default="GENERAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="collaboration_mode",
            field=models.CharField(
                choices=[("SINGLE_OWNER", "Single-owner"), ("COLLABORATIVE", "Collaborative")],
                default="SINGLE_OWNER",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="owning_domain_lob",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="approval_model",
            field=models.CharField(
                choices=[("REFERENCE_LEVEL", "Reference-level"), ("ROW_LEVEL", "Row-level")],
                default="REFERENCE_LEVEL",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="approval_scope",
            field=models.CharField(
                choices=[("GLOBAL", "Global"), ("REGIONAL", "Regional")],
                default="GLOBAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="approver_group_mapping",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="effective_dating_rules",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="mduheader",
            name="history_retention_expectations",
            field=models.CharField(blank=True, default="", max_length=200),
        ),

        # -----------------------
        # ChangeRequest: new fields
        # -----------------------

        # Step 1: add nullable, non-unique draft_uuid so SQLite can rebuild without collisions
        migrations.AddField(
            model_name="changerequest",
            name="draft_uuid",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="changerequest",
            name="lock_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="changerequest",
            name="collaboration_mode",
            field=models.CharField(
                choices=[("SINGLE_OWNER", "Single-owner"), ("COLLABORATIVE", "Collaborative")],
                default="SINGLE_OWNER",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="changerequest",
            name="dda_review_status",
            field=models.CharField(
                choices=[
                    ("NOT_REQUIRED", "Not required"),
                    ("REQUIRED", "Required"),
                    ("PENDING", "Pending"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                ],
                default="NOT_REQUIRED",
                max_length=20,
            ),
        ),

        # Step 2: backfill unique UUIDs for existing rows
        migrations.RunPython(backfill_draft_uuid, migrations.RunPython.noop),

        # Step 3: enforce unique + non-null (matching models.py)
        migrations.AlterField(
            model_name="changerequest",
            name="draft_uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),

        # ------------------------------
        # New governance + audit models
        # ------------------------------
        migrations.CreateModel(
            name="MDUColumnGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("group_name", models.CharField(max_length=80)),
                ("owner_group", models.CharField(blank=True, default="", max_length=120)),
                ("required_on_insert", models.BooleanField(default=False)),
                ("dependency_rules", models.TextField(blank=True, default="")),
                ("notification_rules", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("header", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="column_groups", to="mdu.mduheader")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("header", "group_name"), name="uniq_col_group_per_header")
                ],
            },
        ),
        migrations.CreateModel(
            name="MDUColumnDef",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("column_name", models.CharField(max_length=40)),
                ("data_type", models.CharField(blank=True, default="STRING", max_length=40)),
                ("nullable", models.BooleanField(default=True)),
                ("required", models.BooleanField(default=False)),
                ("default_value", models.CharField(blank=True, default="", max_length=200)),
                ("business_description", models.CharField(blank=True, default="", max_length=400)),
                ("ui_label", models.CharField(blank=True, default="", max_length=120)),
                ("column_owner", models.CharField(blank=True, default="", max_length=120)),
                ("is_deprecated", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("column_group", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="columns", to="mdu.mducolumngroup")),
                ("header", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="columns", to="mdu.mduheader")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("header", "column_name"), name="uniq_col_name_per_header")
                ],
            },
        ),
        migrations.CreateModel(
            name="MDUCompositeKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("normalization_rules", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("header", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="composite_key", to="mdu.mduheader")),
            ],
        ),
        migrations.CreateModel(
            name="MDUCompositeKeyField",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key_order", models.PositiveSmallIntegerField(default=1)),
                ("column", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="as_key_field", to="mdu.mducolumndef")),
                ("composite_key", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fields", to="mdu.mducompositekey")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("composite_key", "column"), name="uniq_key_field_per_key"),
                    models.UniqueConstraint(fields=("composite_key", "key_order"), name="uniq_key_order_per_key"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MDUValidationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rule_name", models.CharField(max_length=120)),
                ("rule_type", models.CharField(max_length=60)),
                ("rule_config", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("applies_to_group", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="validation_rules", to="mdu.mducolumngroup")),
                ("header", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="validation_rules", to="mdu.mduheader")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("header", "rule_name"), name="uniq_rule_name_per_header")
                ],
            },
        ),
        migrations.CreateModel(
            name="MDUChangeRowAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("row_index", models.IntegerField()),
                ("operation", models.CharField(choices=[("INSERT ROW", "INSERT ROW"), ("UPDATE ROW", "UPDATE ROW"), ("KEEP ROW", "KEEP ROW"), ("RETIRE ROW", "RETIRE ROW"), ("UNRETIRE ROW", "UNRETIRE ROW")], max_length=20)),
                ("entity_id", models.CharField(blank=True, default="", max_length=64)),
                ("row_id", models.CharField(blank=True, default="", max_length=64)),
                ("prior_row_id", models.CharField(blank=True, default="", max_length=64)),
                ("update_rowid", models.CharField(blank=True, default="", max_length=128)),
                ("is_current", models.CharField(blank=True, default="", max_length=1)),
                ("deleted_flag", models.CharField(blank=True, default="", max_length=1)),
                ("effective_start_dttm", models.DateTimeField(blank=True, null=True)),
                ("effective_end_dttm", models.DateTimeField(blank=True, null=True)),
                ("modified_dttm", models.DateTimeField(blank=True, null=True)),
                ("modified_by", models.CharField(blank=True, default="", max_length=120)),
                ("row_payload_json", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("change_request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="row_audits", to="mdu.changerequest")),
            ],
        ),

        # ------------------------------
        # DB constraint: one open CR per header for SINGLE_OWNER
        # ------------------------------
        migrations.AddConstraint(
            model_name="changerequest",
            constraint=models.UniqueConstraint(
                fields=("header", "collaboration_mode"),
                condition=models.Q(status__in=["DRAFT", "SUBMITTED"], collaboration_mode="SINGLE_OWNER"),
                name="uniq_open_cr_per_header_single_owner",
            ),
        ),
    ]
