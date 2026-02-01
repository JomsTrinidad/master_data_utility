from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mdu", "0007_governance_models"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="changerequest",
            name="uniq_open_cr_per_header_single_owner",
        ),
        migrations.AddConstraint(
            model_name="changerequest",
            constraint=models.UniqueConstraint(
                fields=("header", "collaboration_mode"),
                condition=models.Q(status="SUBMITTED", collaboration_mode="SINGLE_OWNER"),
                name="uniq_submitted_cr_per_header_single_owner",
            ),
        ),
    ]
