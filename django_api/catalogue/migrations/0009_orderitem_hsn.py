from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0008_invoice_profile_hsn")]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="hsn_code",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
