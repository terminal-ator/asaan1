from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0003_normalize_product_lookups")]

    operations = [
        migrations.AlterModelOptions(
            name="product",
            options={"ordering": ["company__name", "brand__name", "name"]},
        ),
    ]
