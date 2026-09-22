from django import forms

from catalogue.models import Shop


class ShopForm(forms.ModelForm):
    class Meta:
        model = Shop
        fields = [
            "store_name",
            "customer_name",
            "mobile",
            "gstin",
            "address",
            "state",
            "latitude",
            "longitude",
            "location_accuracy",
            "active",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-brand-500 "
            "focus:ring-4 focus:ring-brand-100"
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "h-4 w-4 rounded border-slate-300 text-brand-600"
                if isinstance(field.widget, forms.CheckboxInput)
                else input_class
            )

