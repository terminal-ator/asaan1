"""Quick add: one screen per product, built for typing in a run of best sellers.

"Save & add another" comes back with the company, brand, category, HSN and
unit already picked, and archived products can be restored instead of retyped.
"""

from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from catalogue.models import Product
from .forms import ProductForm

# Fields that usually stay the same across a run of products from one brand.
CARRY_OVER = ["company_name", "brand_name", "category_name", "hsn", "unit"]


def generate_sku(name):
    base = slugify(name).upper()[:40] or "ITEM"
    sku, n = base, 2
    while Product.objects.filter(sku=sku).exists():
        sku, n = f"{base}-{n}", n + 1
    return sku


class ProductQuickAddForm(ProductForm):
    class Meta(ProductForm.Meta):
        fields = [
            "name", "simple_name", "company_name", "brand_name", "category_name",
            "packing", "unit", "rate", "mrp", "markup_percent", "hsn", "gst_rate", "scheme_percent", "sku", "image", "regular",
        ]
        labels = {"name": "Name (as in Marg)", "simple_name": "Name shops see"}
        help_texts = {"simple_name": "Optional. Defaults to the Marg name."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sku"].required = False
        self.fields["sku"].help_text = "Use the Marg item code. Left blank, one is made from the name."
        self.fields["gst_rate"].required = False
        self.fields["gst_rate"].help_text = "Filled from the HSN when blank."
        self.fields["scheme_percent"].required = False

    def clean_sku(self):
        sku = self.cleaned_data.get("sku", "").strip()
        existing = Product.objects.filter(sku=sku).first() if sku else None
        if existing and not existing.active:
            raise forms.ValidationError(
                f"SKU {sku} is the archived product “{existing}”. Restore it from "
                "“Bring back an archived product” above instead."
            )
        if existing:
            raise forms.ValidationError(f"SKU {sku} is already used by “{existing}”.")
        return sku

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("sku") and cleaned.get("name") and "sku" not in self.errors:
            cleaned["sku"] = generate_sku(cleaned["name"])
        if cleaned.get("gst_rate") is None:
            hsn = cleaned.get("hsn")
            cleaned["gst_rate"] = hsn.default_gst_rate if hsn else Decimal("0")
        if cleaned.get("scheme_percent") is None:
            cleaned["scheme_percent"] = Decimal("0")
        return cleaned


def duplicate_initial(product):
    """Everything but the SKU and photo, so a pack-size variant only needs its differences."""
    return {
        "name": product.name,
        "simple_name": product.simple_name,
        "company_name": product.company_id,
        "brand_name": product.brand_id,
        "category_name": product.category_id,
        "packing": product.packing,
        "unit": product.unit,
        "rate": Decimal(product.rate) / 100,
        "mrp": Decimal(product.mrp) / 100,
        "markup_percent": product.implied_markup_percent,
        "hsn": product.hsn_id,
        "gst_rate": product.gst_rate,
        "scheme_percent": product.scheme_percent,
        "regular": product.regular,
    }


def _archived_matches(term):
    if not term:
        return []
    return list(
        Product.objects.filter(active=False)
        .filter(
            Q(name__icontains=term) | Q(simple_name__icontains=term)
            | Q(sku__icontains=term) | Q(brand__name__icontains=term)
        )
        .select_related("brand")
        .order_by("brand__name", "name")[:15]
    )


@login_required
def product_quick_add(request):
    carried = {key: request.GET[key] for key in CARRY_OVER if request.GET.get(key)}
    source = None
    if request.GET.get("from"):
        try:
            source = Product.objects.filter(pk=request.GET["from"]).first()
        except ValidationError:
            source = None
    initial = duplicate_initial(source) if source else carried
    form = ProductQuickAddForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, f"Added {product}.")
        if request.POST.get("next") == "another":
            keep = {key: form.data.get(key, "") for key in CARRY_OVER}
            return redirect(f"{reverse('console-product-quick-add')}?{urlencode(keep)}")
        return redirect("console-products")
    find = request.GET.get("find", "").strip()
    return render(request, "console/product_quick_add.html", {
        "form": form,
        "find": find,
        "archived": _archived_matches(find),
        "carried": bool(carried) and not source,
        "source": source,
    })


@login_required
@require_POST
def product_restore(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    product.active = True
    product.save(update_fields=["active", "updated_at"])
    messages.success(request, f"Restored {product}. Check its rate before shops order it.")
    find = request.POST.get("find", "")
    return redirect(f"{reverse('console-product-quick-add')}?{urlencode({'find': find})}")
