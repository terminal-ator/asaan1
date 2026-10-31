from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from catalogue.models import ProductBundle
from .bundle_forms import BundleForm, BundleItemFormSet


@staff_member_required
def bundles(request):
    return render(request, "console/bundles.html", {
        "bundles": ProductBundle.objects.prefetch_related("items__product"),
    })


@staff_member_required
def bundle_edit(request, bundle_id=None):
    bundle = get_object_or_404(ProductBundle, pk=bundle_id) if bundle_id else ProductBundle()
    data = request.POST if request.method == "POST" else None
    form = BundleForm(data, instance=bundle)
    formset = BundleItemFormSet(data, instance=bundle, prefix="items")
    if request.method == "POST":
        valid_details = form.is_valid()
        valid_items = formset.is_valid()
        if valid_details and valid_items:
            with transaction.atomic():
                form.save()
                # Delete marked lines before writing replacements, including
                # when a product is moved to a new line in the same edit.
                items = formset.save(commit=False)
                for item in formset.deleted_objects:
                    item.delete()
                for item in items:
                    item.save()
            messages.success(request, "Recommended bundle saved.")
            return redirect("console-bundles")
    return render(request, "console/bundle_form.html", {
        "bundle": bundle, "form": form, "formset": formset,
        "initial_tab": "details" if form.errors or not formset.is_bound else "products",
    })
