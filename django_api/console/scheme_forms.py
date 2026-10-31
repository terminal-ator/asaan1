from django import forms
from django.db.models import Q

from catalogue.models import Product, Scheme
from .bundle_forms import style_fields


class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = ["name", "percent", "starts_on", "ends_on", "active", "products"]
        labels = {"percent": "Scheme %", "starts_on": "Starts on", "ends_on": "Ends on"}
        help_texts = {
            "starts_on": "Leave blank to start now.",
            "ends_on": "Leave blank to run until switched off.",
        }
        widgets = {
            "percent": forms.NumberInput(attrs={"min": 0, "max": 100, "step": "0.01", "placeholder": "e.g. 3"}),
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            # The template renders the checkboxes itself, with search.
            "products": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Archived products already in the scheme stay listed so saving does
        # not silently drop them; new picks come from the live catalogue.
        current = self.instance.products.all() if self.instance.pk else Product.objects.none()
        self.fields["products"].queryset = (
            Product.objects.filter(Q(active=True) | Q(pk__in=current))
            .select_related("brand", "company")
            .order_by("brand__name", "name")
        )
        style_fields(self)

    def clean(self):
        cleaned = super().clean()
        starts, ends = cleaned.get("starts_on"), cleaned.get("ends_on")
        if starts and ends and ends < starts:
            self.add_error("ends_on", "The end date must be on or after the start date.")
        if cleaned.get("active") and not cleaned.get("products"):
            self.add_error("products", "Pick at least one product for an active scheme.")
        return cleaned
