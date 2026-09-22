from django import forms

from catalogue.models import Order


class OrderBillingForm(forms.ModelForm):
    """Billing details copied onto a printed order slip.

    While bills are raised by hand in Marg, the app only prepares the data:
    invoice numbering, IRN and acknowledgement fields are paused until
    auto-billing resumes.
    """

    class Meta:
        model = Order
        fields = [
            "customer_gstin",
            "billing_address",
            "place_of_supply",
        ]
        widgets = {
            "billing_address": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-emerald-600 "
            "focus:ring-2 focus:ring-emerald-100"
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", input_class)


class OrderInvoiceForm(forms.ModelForm):
    """Unused while billing happens in Marg. Kept for auto-billing later."""

    class Meta:
        model = Order
        fields = [
            "customer_gstin",
            "billing_address",
            "place_of_supply",
            "invoice_number",
            "invoice_date",
            "irn",
            "ack_number",
            "ack_date",
            "qr_code_data",
        ]
        widgets = {
            "billing_address": forms.Textarea(attrs={"rows": 3}),
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            "ack_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "qr_code_data": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-emerald-600 "
            "focus:ring-2 focus:ring-emerald-100"
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", input_class)
