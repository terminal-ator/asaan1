from django.db import migrations, models
import decimal


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0004_alter_product_options")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="gst_rate",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0"), max_digits=5),
        ),
        migrations.AddField(
            model_name="order",
            name="billing_address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="order",
            name="customer_gstin",
            field=models.CharField(blank=True, max_length=15),
        ),
        migrations.AddField(
            model_name="order",
            name="invoice_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="invoice_number",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="order",
            name="place_of_supply",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="gst_rate",
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal("0"), max_digits=5),
        ),
    ]
