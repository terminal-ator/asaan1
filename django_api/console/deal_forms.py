from django import forms

from catalogue.models import Product


class DealRowForm(forms.Form):
    """One weekday row on the daily deals sheet."""

    weekday = forms.IntegerField(widget=forms.HiddenInput)
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label="Product",
        empty_label="— no deal —",
    )
    percent = forms.DecimalField(
        min_value=0,
        max_value=100,
        required=False,
        decimal_places=2,
        label="Extra % off",
    )
    note = forms.CharField(max_length=150, required=False, label="Note")
    active = forms.BooleanField(required=False, initial=True, label="Active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = (
            Product.objects.filter(active=True)
            .select_related("company")
            .order_by("name")
        )
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault(
                    "class", "h-4 w-4 rounded border-slate-300 text-brand-600"
                )
            else:
                field.widget.attrs.setdefault(
                    "class",
                    "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
                )
