from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from catalogue.models import Scheme
from .scheme_forms import SchemeForm


def _status(scheme, today):
    if not scheme.active:
        return "Off"
    if scheme.starts_on and scheme.starts_on > today:
        return "Scheduled"
    if scheme.ends_on and scheme.ends_on < today:
        return "Ended"
    return "Running"


@staff_member_required
def schemes(request):
    today = timezone.localdate()
    items = Scheme.objects.annotate(product_count=Count("products")).prefetch_related("products")
    return render(request, "console/schemes.html", {
        "schemes": [(scheme, _status(scheme, today)) for scheme in items],
    })


@staff_member_required
def scheme_edit(request, scheme_id=None):
    scheme = get_object_or_404(Scheme, pk=scheme_id) if scheme_id else Scheme()
    form = SchemeForm(request.POST or None, instance=scheme)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Scheme saved. New orders get it from now on.")
        return redirect("console-schemes")
    selected = {str(value) for value in (form["products"].value() or [])}
    return render(request, "console/scheme_form.html", {
        "scheme": scheme,
        "form": form,
        "products": form.fields["products"].queryset,
        "selected": selected,
        "initial_tab": "products" if form.errors.get("products") or (scheme.pk and not form.errors) else "details",
    })
