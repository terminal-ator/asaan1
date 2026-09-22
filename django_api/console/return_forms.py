from django import forms
from decimal import Decimal, ROUND_HALF_UP
from django.forms import inlineformset_factory

from catalogue.models import (
    Order, Purchase, PurchaseReturn, PurchaseReturnItem, SalesReturn, SalesReturnItem,
)


class SalesReturnForm(forms.ModelForm):
    class Meta:
        model = SalesReturn
        fields = ["order", "warehouse", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}


class PurchaseReturnForm(forms.ModelForm):
    class Meta:
        model = PurchaseReturn
        fields = ["purchase", "warehouse", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}


class SalesReturnItemForm(forms.ModelForm):
    rate = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Rate (₹)")
    class Meta:
        model = SalesReturnItem
        fields = ["product", "quantity", "rate", "gst_rate"]
        widgets = {"quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk: self.initial["rate"] = Decimal(self.instance.rate) / 100

    def clean_rate(self):
        return int((self.cleaned_data["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PurchaseReturnItemForm(forms.ModelForm):
    rate = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Rate (₹)")
    class Meta:
        model = PurchaseReturnItem
        fields = ["product", "quantity", "rate", "gst_rate"]
        widgets = {"quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk: self.initial["rate"] = Decimal(self.instance.rate) / 100

    def clean_rate(self):
        return int((self.cleaned_data["rate"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


SalesReturnItemFormSet = inlineformset_factory(SalesReturn, SalesReturnItem, form=SalesReturnItemForm, extra=1, can_delete=True)
PurchaseReturnItemFormSet = inlineformset_factory(PurchaseReturn, PurchaseReturnItem, form=PurchaseReturnItemForm, extra=1, can_delete=True)
