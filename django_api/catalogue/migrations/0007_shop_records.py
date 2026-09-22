from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


def copy_shops(apps, schema_editor):
    Order = apps.get_model("catalogue", "Order")
    Shop = apps.get_model("catalogue", "Shop")

    for order in Order.objects.all():
        data = order.shop or {}
        mobile = str(data.get("mobile", "")).strip()
        store_name = str(data.get("storeName", "")).strip()
        if not mobile and not store_name:
            continue
        shop = Shop.objects.filter(mobile=mobile, store_name=store_name).first()
        if not shop:
            shop = Shop.objects.create(
                store_name=store_name or "Unnamed shop",
                customer_name=str(data.get("customerName", "")).strip(),
                mobile=mobile,
                gstin=str(data.get("gstin", "")).strip(),
                address=str(data.get("address", "")).strip(),
                state=str(data.get("state", "")).strip(),
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                location_accuracy=data.get("locationAccuracy"),
            )
        order.shop_record_id = shop.pk
        order.save(update_fields=["shop_record"])


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0006_loading_orders")]

    operations = [
        migrations.CreateModel(
            name="Shop",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("store_name", models.CharField(max_length=200)),
                ("customer_name", models.CharField(blank=True, max_length=150)),
                ("mobile", models.CharField(max_length=30)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                ("address", models.TextField(blank=True)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("latitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("location_accuracy", models.PositiveIntegerField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["store_name", "mobile"]},
        ),
        migrations.AddField(
            model_name="order",
            name="shop_record",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="orders", to="catalogue.shop"),
        ),
        migrations.RunPython(copy_shops, migrations.RunPython.noop),
    ]
