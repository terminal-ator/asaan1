from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.forms import inlineformset_factory

from catalogue.models import Purchase, PurchaseItem


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = [
            "supplier",
            "warehouse",
            "supplier_invoice_number",
            "supplier_invoice_date",
            "tds_rate",
            "notes",
        ]
        widgets = {
            "supplier_invoice_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-brand-500 "
            "focus:ring-4 focus:ring-brand-100"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = field_class


class PurchaseItemForm(forms.ModelForm):
    rate = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Rate / unit (₹)",
    )
    taxable_total = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=14,
        decimal_places=2,
        label="Taxable total (₹)",
        help_text="Enter the complete taxable value; unit rate is back-calculated.",
    )

    class Meta:
        model = PurchaseItem
        fields = ["product", "quantity", "rate", "gst_rate"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
            "rate": forms.NumberInput(attrs={"min": "0"}),
            "gst_rate": forms.NumberInput(attrs={"step": "0.01", "min": "0", "max": "100"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["taxable_total"] = Decimal(self.instance.line_total) / 100
            self.initial["rate"] = Decimal(self.instance.rate) / 100
        input_class = (
            "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 "
            "text-sm outline-none focus:border-brand-500 focus:ring-4 "
            "focus:ring-brand-100"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = input_class

    def clean(self):
        cleaned = super().clean()
        quantity = cleaned.get("quantity")
        taxable_total = cleaned.get("taxable_total")
        if quantity and taxable_total is not None:
            taxable_paise = int((taxable_total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            cleaned["taxable_total"] = taxable_paise
            cleaned["rate"] = int(
                (Decimal(taxable_paise) / quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        elif cleaned.get("rate") is not None:
            cleaned["rate"] = int((cleaned["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cleaned


PurchaseItemFormSet = inlineformset_factory(
    Purchase,
    PurchaseItem,
    form=PurchaseItemForm,
    extra=1,
    can_delete=True,
)
