from django import forms

from catalogue.models import Shop

ORDER_DAY_CHOICES = [
    (0, "Mon"),
    (1, "Tue"),
    (2, "Wed"),
    (3, "Thu"),
    (4, "Fri"),
    (5, "Sat"),
    (6, "Sun"),
]


class ShopForm(forms.ModelForm):
    order_days = forms.MultipleChoiceField(
        choices=ORDER_DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Order days",
        help_text="The shop gets a morning reminder on these days.",
    )

    class Meta:
        model = Shop
        fields = [
            "store_name",
            "customer_name",
            "mobile",
            "gstin",
            "address",
            "state",
            "order_days",
            "latitude",
            "longitude",
            "location_accuracy",
            "active",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["order_days"] = [str(day) for day in (self.instance.order_days or [])]
        input_class = (
            "block w-full rounded-xl border border-slate-300 bg-white px-3 "
            "py-2.5 text-sm outline-none focus:border-brand-500 "
            "focus:ring-4 focus:ring-brand-100"
        )
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "h-4 w-4 rounded border-slate-300 text-brand-600"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "h-4 w-4 rounded border-slate-300 text-brand-600"
            else:
                field.widget.attrs["class"] = input_class

    def clean_order_days(self):
        return sorted(int(value) for value in self.cleaned_data.get("order_days", []))

    def save(self, commit=True):
        shop = super().save(commit=False)
        shop.order_days = self.cleaned_data.get("order_days", [])
        if commit:
            shop.save()
        return shop

