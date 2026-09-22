from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0010_einvoice_fields")]

    operations = [
        migrations.CreateModel(
            name="InvoiceSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("prefix", models.CharField(max_length=10)),
                ("financial_year", models.CharField(max_length=9)),
                ("next_number", models.PositiveIntegerField(default=1)),
            ],
        ),
        migrations.AddConstraint(
            model_name="invoicesequence",
            constraint=models.UniqueConstraint(fields=("prefix", "financial_year"), name="unique_invoice_sequence_year"),
        ),
    ]
