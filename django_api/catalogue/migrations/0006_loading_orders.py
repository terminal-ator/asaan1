from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0005_invoice_and_gst_fields")]

    operations = [
        migrations.CreateModel(
            name="Loading",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("loading_number", models.CharField(max_length=50, unique=True)),
                ("status", models.CharField(choices=[("open", "Open"), ("printed", "Printed"), ("dispatched", "Dispatched")], default="open", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("printed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddField(
            model_name="order",
            name="loading",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="orders", to="catalogue.loading"),
        ),
    ]
