from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("mdu", "0010_rename_primary_approver_sid_changerequest_business_owner_sid_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="changerequest",
            name="contributors",
            field=models.ManyToManyField(blank=True, related_name="collab_changes", to=settings.AUTH_USER_MODEL),
        ),
    ]
