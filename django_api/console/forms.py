from decimal import Decimal, ROUND_HALF_UP

from django import forms

from catalogue.models import Brand, Category, Company, HSN, Product, Shop


class ProductForm(forms.ModelForm):
    rate = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label="Sale rate (₹)")
    mrp = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label="MRP (₹)")
    company_name = forms.ModelChoiceField(queryset=Company.objects.order_by("name"), label="Company", empty_label="Select company")
    brand_name = forms.ModelChoiceField(queryset=Brand.objects.order_by("name"), label="Brand", empty_label="Select brand")
    category_name = forms.ModelChoiceField(queryset=Category.objects.order_by("name"), label="Category", empty_label="Select category")
    hsn = forms.ModelChoiceField(queryset=HSN.objects.order_by("code"), label="HSN", required=False, empty_label="Select HSN")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.company_id:
            self.fields["company_name"].initial = self.instance.company_id
            self.fields["brand_name"].initial = self.instance.brand_id
            self.fields["category_name"].initial = self.instance.category_id
            self.initial["rate"] = Decimal(self.instance.rate) / 100
            self.initial["mrp"] = Decimal(self.instance.mrp) / 100
        if self.instance and self.instance.pk and self.instance.hsn_id:
            self.fields["hsn"].initial = self.instance.hsn_id

        field_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none transition focus:border-brand-500 "
            "focus:ring-4 focus:ring-brand-100"
        )

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault(
                    "class",
                    "h-4 w-4 rounded border-slate-300 text-brand-600 "
                    "focus:ring-brand-500",
                )
            else:
                field.widget.attrs.setdefault("class", field_class)

        # The photo picker is rendered by hand in the product form so phones get
        # big "Take photo" / "Choose" buttons; keep only the attributes Django
        # needs for validation and the degraded (no-JS) case.
        self.fields["image"].widget.attrs["accept"] = "image/*"
        self.fields["image"].widget.initial_text = "Current photo"
        self.fields["image"].widget.clear_checkbox_label = "Remove photo"

    def save(self, commit=True):
        product = super().save(commit=False)
        product.company = self.cleaned_data["company_name"]
        product.brand = self.cleaned_data["brand_name"]
        product.category = self.cleaned_data["category_name"]
        product.hsn = self.cleaned_data.get("hsn")
        product.hsn_code = product.hsn.code if product.hsn else product.hsn_code
        product.rate = int((self.cleaned_data["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        product.mrp = int((self.cleaned_data["mrp"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if product.hsn and not self.initial.get("gst_rate") and not self.data.get("gst_rate"):
            product.gst_rate = product.hsn.default_gst_rate
        if commit:
            product.save()
            self.save_m2m()
        return product

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "simple_name",
            "company_name",
            "brand_name",
            "category_name",
            "hsn",
            "packing",
            "unit",
            "rate",
            "mrp",
            "gst_rate",
            "scheme_percent",
            "image",
            "image_url",
            "active",
        ]
        widgets = {
            "rate": forms.NumberInput(
                attrs={"placeholder": "Rupees, e.g. 1788.00"}
            ),
            "mrp": forms.NumberInput(
                attrs={"placeholder": "Rupees, e.g. 2160.00"}
            ),
        }


SHEET_INPUT = (
    "w-full min-w-[104px] rounded-lg border border-slate-300 bg-white px-2.5 py-2 "
    "text-sm outline-none transition focus:border-brand-500 focus:ring-4 "
    "focus:ring-brand-100"
)
SHEET_CHECKBOX = "h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
SHEET_INPUT_WIDE = SHEET_INPUT.replace("min-w-[104px]", "min-w-[208px]")


class ProductBulkForm(forms.ModelForm):
    """One row of the product sheet. Prices are entered in rupees, stored in paise."""

    rate = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label="Rate (₹)")
    mrp = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label="MRP (₹)")

    class Meta:
        model = Product
        fields = ["rate", "mrp", "gst_rate", "scheme_percent", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["rate"] = Decimal(self.instance.rate) / 100
            self.initial["mrp"] = Decimal(self.instance.mrp) / 100
        for name, field in self.fields.items():
            field.widget.attrs.setdefault(
                "class",
                SHEET_CHECKBOX if isinstance(field.widget, forms.CheckboxInput) else SHEET_INPUT,
            )
            field.widget.attrs["data-column"] = name

    def save(self, commit=True):
        product = super().save(commit=False)
        product.rate = int(
            (self.cleaned_data["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        product.mrp = int(
            (self.cleaned_data["mrp"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        if commit:
            product.save()
        return product


class ShopBulkForm(forms.ModelForm):
    """One row of the shop sheet. Location coordinates are edited individually."""

    class Meta:
        model = Shop
        fields = [
            "store_name",
            "customer_name",
            "mobile",
            "gstin",
            "state",
            "address",
            "active",
        ]
        widgets = {"address": forms.TextInput(attrs={"class": SHEET_INPUT_WIDE})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault(
                "class",
                SHEET_CHECKBOX if isinstance(field.widget, forms.CheckboxInput) else SHEET_INPUT,
            )
            field.widget.attrs["data-column"] = name
