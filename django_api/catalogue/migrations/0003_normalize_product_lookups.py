from django.db import migrations, models
import django.db.models.deletion


def copy_lookup_values(apps, schema_editor):
    Product = apps.get_model("catalogue", "Product")
    Company = apps.get_model("catalogue", "Company")
    Brand = apps.get_model("catalogue", "Brand")
    Category = apps.get_model("catalogue", "Category")

    for product in Product.objects.all():
        company, _ = Company.objects.get_or_create(name=product.company)
        brand, _ = Brand.objects.get_or_create(name=product.brand)
        category, _ = Category.objects.get_or_create(name=product.category)
        product.company_ref_id = company.pk
        product.brand_ref_id = brand.pk
        product.category_ref_id = category.pk
        product.save(update_fields=["company_ref", "brand_ref", "category_ref"])


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0002_order_status")]

    operations = [
        migrations.CreateModel(
            name="Brand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="product",
            name="brand_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="catalogue.brand"),
        ),
        migrations.AddField(
            model_name="product",
            name="category_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="catalogue.category"),
        ),
        migrations.AddField(
            model_name="product",
            name="company_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="catalogue.company"),
        ),
        migrations.RunPython(copy_lookup_values, migrations.RunPython.noop),
        migrations.RemoveField(model_name="product", name="brand"),
        migrations.RemoveField(model_name="product", name="category"),
        migrations.RemoveField(model_name="product", name="company"),
        migrations.RenameField(model_name="product", old_name="brand_ref", new_name="brand"),
        migrations.RenameField(model_name="product", old_name="category_ref", new_name="category"),
        migrations.RenameField(model_name="product", old_name="company_ref", new_name="company"),
        migrations.AlterField(
            model_name="product",
            name="brand",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalogue.brand"),
        ),
        migrations.AlterField(
            model_name="product",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalogue.category"),
        ),
        migrations.AlterField(
            model_name="product",
            name="company",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalogue.company"),
        ),
    ]
