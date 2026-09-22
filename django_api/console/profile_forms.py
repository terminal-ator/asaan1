from django import forms

from catalogue.models import DistributorProfile


class DistributorProfileForm(forms.ModelForm):
    class Meta:
        model = DistributorProfile
        fields = ["legal_name", "gstin", "address", "state", "invoice_prefix"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-brand-500 "
            "focus:ring-4 focus:ring-brand-100"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = input_class

