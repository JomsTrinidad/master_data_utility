from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mdu", "0014_alter_mduheader_ref_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="mduheader",
            name="certification_required",
            field=models.BooleanField(
                default=False,
                help_text="Whether periodic certification is required for this reference.",
            ),
        ),
    ]
