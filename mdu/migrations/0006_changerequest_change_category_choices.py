from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mdu", "0005_changerequest_bulk_add_count"),
    ]

    operations = [
        migrations.AlterField(
            model_name="changerequest",
            name="change_category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "— Select —"),
                    ("DATA_CORRECTION", "Data Correction"),
                    ("NEW_VALUE_ADD", "New Value Add"),
                    ("POLICY_COMPLIANCE", "Policy / Compliance"),
                    ("OPERATIONAL_UPDATE", "Operational Update"),
                    ("ENHANCEMENT", "Enhancement"),
                    ("OTHER", "Other"),
                ],
                default="",
                max_length=60,
            ),
        ),
    ]
