from decimal import Decimal, ROUND_HALF_UP

from django import forms

from catalogue.models import Brand, Category, Company, HSN, Product, Supplier


class QuickSupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "mobile", "gstin", "address", "pincode", "state", "email", "pan"]

    def save(self, commit=True):
        data = self.cleaned_data
        supplier, _ = Supplier.objects.get_or_create(
            name=data["name"].strip(),
            mobile=data.get("mobile", "").strip(),
            defaults={
                "gstin": data.get("gstin", "").strip(),
                "address": data.get("address", "").strip(),
                "pincode": data.get("pincode", "").strip(),
                "state": data.get("state", "").strip(),
                "email": data.get("email", "").strip(),
                "pan": data.get("pan", "").strip(),
                "active": True,
            },
        )
        if commit:
            changed = []
            for field in ("gstin", "address", "pincode", "state", "email", "pan"):
                value = data.get(field, "").strip()
                if value and getattr(supplier, field) != value:
                    setattr(supplier, field, value)
                    changed.append(field)
            if changed:
                supplier.save(update_fields=changed + ["updated_at"])
        return supplier


class QuickProductForm(forms.Form):
    sku = forms.CharField(max_length=100)
    name = forms.CharField(max_length=255)
    company = forms.CharField(max_length=150)
    brand = forms.CharField(max_length=150)
    category = forms.CharField(max_length=150)
    hsn_code = forms.CharField(max_length=20, required=False)
    hsn_default_rate = forms.DecimalField(min_value=0, max_value=100, decimal_places=2, max_digits=5, required=False)
    packing = forms.CharField(max_length=150)
    unit = forms.CharField(max_length=50, initial="case")
    rate = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, help_text="Rupees")
    mrp = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, help_text="Rupees")
    gst_rate = forms.DecimalField(min_value=0, max_value=100, decimal_places=2, max_digits=5, required=False)

    def save(self):
        data = self.cleaned_data
        hsn_code = data.get("hsn_code", "").strip()
        hsn = None
        hsn_rate = data.get("hsn_default_rate")
        if hsn_code:
            hsn, _ = HSN.objects.get_or_create(
                code=hsn_code,
                defaults={"default_gst_rate": hsn_rate or 0},
            )
            if hsn_rate is not None and hsn.default_gst_rate != hsn_rate:
                hsn.default_gst_rate = hsn_rate
                hsn.save(update_fields=["default_gst_rate"])
        gst_rate = data.get("gst_rate")
        if gst_rate is None:
            gst_rate = hsn.default_gst_rate if hsn else 0
        product, _ = Product.objects.update_or_create(
            sku=data["sku"],
            defaults={
                "name": data["name"],
                "simple_name": data["name"],
                "company": Company.objects.get_or_create(name=data["company"].strip())[0],
                "brand": Brand.objects.get_or_create(name=data["brand"].strip())[0],
                "category": Category.objects.get_or_create(name=data["category"].strip())[0],
                "hsn": hsn,
                "hsn_code": hsn_code,
                "packing": data["packing"],
                "unit": data["unit"],
                "rate": int((data["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                "mrp": int((data["mrp"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                "gst_rate": gst_rate,
                "active": True,
            },
        )
        return product
