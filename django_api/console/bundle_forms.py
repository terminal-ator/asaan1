from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from catalogue.models import Product, ProductBundle, ProductBundleItem


def style_fields(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = (
            "h-4 w-4 rounded border-slate-300 text-brand-600"
            if isinstance(field.widget, forms.CheckboxInput)
            else "block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm"
        )


class BundleForm(forms.ModelForm):
    class Meta:
        model = ProductBundle
        fields = ["name", "shop_type", "description", "active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class BundleItemForm(forms.ModelForm):
    class Meta:
        model = ProductBundleItem
        fields = ["product", "quantity"]
        widgets = {"quantity": forms.NumberInput(attrs={"min": 1, "max": 100_000})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # An existing inactive product remains editable, but cannot be added
        # to a new bundle. The public catalogue excludes inactive products.
        self.fields["product"].queryset = Product.objects.filter(
            Q(active=True) | Q(pk=self.instance.product_id)
        ).select_related("company").order_by("name", "sku")
        self.fields["product"].label_from_instance = (
            lambda product: f"{product} · {product.sku} · {product.unit}"
        )
        style_fields(self)


class BaseBundleItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        items = [
            form.cleaned_data for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if not items:
            raise forms.ValidationError("Add at least one product to the bundle.")
        if self.instance.active and not any(item["product"].active for item in items):
            raise forms.ValidationError("An active bundle needs at least one active product.")


BundleItemFormSet = inlineformset_factory(
    ProductBundle, ProductBundleItem, form=BundleItemForm,
    formset=BaseBundleItemFormSet, extra=1, can_delete=True,
    max_num=100, validate_max=True,
)
