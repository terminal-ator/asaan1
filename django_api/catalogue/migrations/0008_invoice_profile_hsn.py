from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0007_shop_records")]

    operations = [
        migrations.CreateModel(
            name="DistributorProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legal_name", models.CharField(default="Ordex Distributor", max_length=200)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                ("address", models.TextField(blank=True)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("invoice_prefix", models.CharField(default="INV", max_length=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name="product",
            name="hsn_code",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
