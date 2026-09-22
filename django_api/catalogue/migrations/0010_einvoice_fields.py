from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0009_orderitem_hsn")]

    operations = [
        migrations.AddField(model_name="order", name="irn", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="order", name="ack_number", field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="order", name="ack_date", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="order", name="qr_code_data", field=models.TextField(blank=True)),
        migrations.AddField(model_name="order", name="einvoice_uploaded_at", field=models.DateTimeField(blank=True, null=True)),
    ]
