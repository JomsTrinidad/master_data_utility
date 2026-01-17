# Generated manually for demo project
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="MDUHeader",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ref_name", models.CharField(max_length=200, unique=True)),
                ("ref_type", models.CharField(default="map", max_length=20)),
                ("mode", models.CharField(default="versioning", max_length=20)),
                ("status", models.CharField(choices=[("PENDING_REVIEW","Pending review"),("IN_REVIEW","In review"),("ACTIVE","Active"),("REJECTED","Rejected"),("RETIRED","Retired")], default="PENDING_REVIEW", max_length=20)),
                ("owner_group", models.CharField(blank=True, default="", max_length=120)),
                ("tags", models.CharField(blank=True, default="", max_length=400)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ChangeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_id", models.CharField(max_length=30, unique=True)),
                ("tracking_id", models.CharField(blank=True, default="", max_length=80)),
                ("status", models.CharField(choices=[("DRAFT","Draft"),("SUBMITTED","Submitted"),("APPROVED","Approved"),("REJECTED","Rejected")], default="DRAFT", max_length=20)),
                ("operation_hint", models.CharField(blank=True, default="", max_length=40)),
                ("override_retired_flag", models.CharField(default="N", max_length=1)),
                ("requested_by_sid", models.CharField(blank=True, default="", max_length=40)),
                ("primary_approver_sid", models.CharField(blank=True, default="", max_length=40)),
                ("secondary_approver_sid", models.CharField(blank=True, default="", max_length=40)),
                ("change_reason", models.CharField(blank=True, default="", max_length=400)),
                ("change_ticket_ref", models.CharField(blank=True, default="", max_length=120)),
                ("change_category", models.CharField(blank=True, default="", max_length=60)),
                ("risk_impact", models.CharField(blank=True, default="", max_length=60)),
                ("request_source_channel", models.CharField(blank=True, default="", max_length=60)),
                ("request_source_system", models.CharField(blank=True, default="", max_length=60)),
                ("payload_json", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_changes", to="auth.user")),
                ("header", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="changes", to="mdu.mduheader")),
            ],
        ),
        migrations.AddField(
            model_name="mduheader",
            name="last_approved_change",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="as_last_for_headers", to="mdu.changerequest"),
        ),
        migrations.CreateModel(
            name="MDUCert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cert_cycle_id", models.CharField(max_length=40)),
                ("certification_status", models.CharField(default="CERTIFIED", max_length=30)),
                ("certification_scope", models.CharField(blank=True, default="", max_length=60)),
                ("certification_summary", models.CharField(blank=True, default="", max_length=400)),
                ("certified_by_sid", models.CharField(blank=True, default="", max_length=40)),
                ("certified_dttm", models.DateTimeField(blank=True, null=True)),
                ("cert_expiry_dttm", models.DateTimeField(blank=True, null=True)),
                ("evidence_link", models.CharField(blank=True, default="", max_length=400)),
                ("qa_issues_found", models.CharField(blank=True, default="", max_length=400)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("header", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="certs", to="mdu.mduheader")),
            ],
        ),
    ]
