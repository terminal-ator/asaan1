"""Staff-only product workspace, quick editing and image uploads."""

import io
import json
from decimal import Decimal
from functools import wraps

from PIL import Image, ImageOps, UnidentifiedImageError

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from catalogue.models import Brand, Category, Company, HSN, Product
from .forms import ProductForm


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def staff_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Your session expired. Please sign in again."}, status=401)
        if not request.user.is_active or not request.user.is_staff:
            return JsonResponse({"error": "Staff access is required."}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def attribute_data(product):
    return {
        "sku": product.sku, "name": product.name, "simple_name": product.simple_name,
        "company_name": str(product.company_id), "brand_name": str(product.brand_id),
        "category_name": str(product.category_id), "hsn": str(product.hsn_id) if product.hsn_id else "",
        "hsn_code": product.hsn_code, "packing": product.packing, "unit": product.unit,
        "rate": str(Decimal(product.rate) / 100), "mrp": str(Decimal(product.mrp) / 100),
        "gst_rate": str(product.gst_rate), "scheme_percent": str(product.scheme_percent),
        "active": product.active, "regular": product.regular,
    }


def product_data(product):
    return {
        "id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "simpleName": product.simple_name,
        "company": product.company.name,
        "brand": product.brand.name,
        "category": product.category.name,
        "packing": product.packing,
        "unit": product.unit,
        "active": product.active,
        "regular": product.regular,
        "imageUrl": product.image.url if product.image else product.image_url,
        "source": "uploaded" if product.image else "linked" if product.image_url else "missing",
        "updatedAt": product.updated_at.isoformat(),
        "attributes": attribute_data(product),
    }


@login_required
@staff_only
@require_GET
def workspace(request):
    return render(request, "console/product_images.html")


@staff_only
@require_GET
def product_list(request):
    items = Product.objects.select_related("company", "brand", "category")
    for word in request.GET.get("q", "").strip().split():
        items = items.filter(
            Q(name__icontains=word) | Q(simple_name__icontains=word)
            | Q(sku__icontains=word) | Q(company__name__icontains=word)
            | Q(brand__name__icontains=word) | Q(category__name__icontains=word)
            | Q(packing__icontains=word)
        )
    for field in ("company", "brand", "category"):
        value = request.GET.get(field, "").strip()
        if value:
            items = items.filter(**{f"{field}__name": value})
    if request.GET.get("unit"):
        items = items.filter(unit=request.GET["unit"])
    for field in ("active", "regular"):
        if request.GET.get(field) in ("yes", "no"):
            items = items.filter(**{field: request.GET[field] == "yes"})
    missing = Q(image="") & Q(image_url="")
    image_filter = request.GET.get("image", "")
    if image_filter == "missing":
        items = items.filter(missing)
    elif image_filter == "present":
        items = items.exclude(missing)
    elif image_filter == "uploaded":
        items = items.exclude(image="")
    elif image_filter == "linked":
        items = items.filter(image="").exclude(image_url="")

    sorts = {
        "name": ("name", "id"),
        "sku": ("sku", "id"),
        "updated": ("-updated_at", "id"),
        "newest": ("-created_at", "id"),
        "company": ("company__name", "brand__name", "name", "id"),
    }
    items = items.order_by(*sorts.get(request.GET.get("sort"), sorts["company"]))
    paginator = Paginator(items, 48)
    page = paginator.get_page(request.GET.get("page", 1))
    scope = Product.objects.all()
    brand_scope = scope.filter(company__name=request.GET["company"]) if request.GET.get("company") else scope

    def choices(queryset, field):
        return list(queryset.order_by(field).values_list(field, flat=True).distinct())

    return JsonResponse({
        "products": [product_data(product) for product in page],
        "total": paginator.count,
        "page": page.number,
        "pages": paginator.num_pages,
        "facets": {
            "company": choices(scope, "company__name"),
            "brand": choices(brand_scope, "brand__name"),
            "category": choices(scope, "category__name"),
            "unit": choices(scope, "unit"),
        },
        "lookups": {
            "company_name": list(Company.objects.values("id", "name")),
            "brand_name": list(Brand.objects.values("id", "name")),
            "category_name": list(Category.objects.values("id", "name")),
            "hsn": list(HSN.objects.values("id", "code", "description", "default_gst_rate")),
        },
    })


class WorkspaceImageField(forms.ImageField):
    def to_python(self, data):
        if data and data.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("Choose an image smaller than 10 MB.")
        image = super().to_python(data)
        if image and image.image.width * image.image.height > 40_000_000:
            raise forms.ValidationError("Choose a photo with fewer than 40 million pixels.")
        return image


class ImageUpdateForm(forms.Form):
    action = forms.ChoiceField(choices=[("upload", "Upload"), ("url", "URL"), ("remove", "Remove"), ("keep", "Keep")])
    version = forms.CharField()
    image = WorkspaceImageField(required=False)
    image_url = forms.URLField(required=False, max_length=200, assume_scheme="https")

    def clean(self):
        data = super().clean()
        if data.get("action") == "upload" and not data.get("image"):
            self.add_error("image", "Choose a valid image to upload.")
        if data.get("action") == "url":
            url = data.get("image_url", "")
            if not url.lower().startswith(("http://", "https://")):
                self.add_error("image_url", "Enter a valid HTTP or HTTPS image URL.")
        return data


def optimized_image(upload):
    """Decode and re-encode uploads: orientation, bounded size, no EXIF data."""
    upload.seek(0)
    with Image.open(upload) as original:
        image = ImageOps.exif_transpose(original)
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        transparent = image.mode in ("RGBA", "LA") or "transparency" in image.info
        image = image.convert("RGBA" if transparent else "RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG" if transparent else "JPEG", **({} if transparent else {"quality": 85, "optimize": True}))
    return ContentFile(buffer.getvalue(), name="photo.png" if transparent else "photo.jpg")


class WorkspaceProductForm(ProductForm):
    gst_rate = forms.DecimalField(min_value=0, max_value=100, max_digits=5, decimal_places=2)

    class Meta(ProductForm.Meta):
        fields = [field for field in ProductForm.Meta.fields if field not in ("image", "image_url")] + ["hsn_code"]


ATTRIBUTE_FIELDS = [
    "sku", "name", "simple_name", "company", "brand", "category", "hsn", "hsn_code",
    "packing", "unit", "rate", "mrp", "gst_rate", "scheme_percent", "active", "regular",
]


def _update(request, product_id, allow_attributes=False):
    changes = None
    if allow_attributes and "attributes" in request.POST:
        try:
            changes = json.loads(request.POST["attributes"])
        except (ValueError, TypeError):
            return JsonResponse({"error": "Product details must be a JSON object."}, status=400)
        if not isinstance(changes, dict) or set(changes) - set(WorkspaceProductForm.base_fields):
            return JsonResponse({"error": "The product details contain unsupported fields."}, status=400)
    data = request.POST.copy()
    if allow_attributes:
        data.setdefault("action", "keep")
        if data["action"] == "keep" and not changes:
            return JsonResponse({"error": "No product changes were provided."}, status=400)
    form = ImageUpdateForm(data, request.FILES)
    if not form.is_valid():
        return JsonResponse({"error": "Check the image details.", "errors": form.errors.get_json_data()}, status=400)
    action = form.cleaned_data["action"]
    with transaction.atomic():
        product = get_object_or_404(
            Product.objects.select_for_update(of=("self",)).select_related("company", "brand", "category"),
            pk=product_id,
        )
        if form.cleaned_data["version"] != product.updated_at.isoformat():
            return JsonResponse({"error": "This product changed since you opened it. Close the editor and refresh before saving."}, status=409)
        fields = ["updated_at"]
        if changes is not None:
            details = WorkspaceProductForm({**attribute_data(product), **changes}, instance=product)
            if not details.is_valid():
                return JsonResponse({"error": "Check the product details.", "errors": details.errors.get_json_data()}, status=400)
            product = details.save(commit=False)
            fields.extend(ATTRIBUTE_FIELDS)
        if action == "upload":
            try:
                product.image = optimized_image(form.cleaned_data["image"])
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                return JsonResponse({"error": "This image could not be read. Try a JPEG, PNG or WebP photo."}, status=400)
            product.image_url = ""
        elif action == "url":
            product.image = ""
            product.image_url = form.cleaned_data["image_url"]
        elif action == "remove":
            product.image = ""
            product.image_url = ""
        if action != "keep":
            fields.extend(["image", "image_url"])
        # A competing SKU rename can pass form validation before the unique constraint fires.
        try:
            with transaction.atomic():
                product.save(update_fields=fields)
        except IntegrityError:
            return JsonResponse({"error": "This SKU is already in use.", "errors": {"sku": [{"message": "Choose a unique SKU.", "code": "unique"}]}}, status=400)
    return JsonResponse({"product": product_data(product)})


@staff_only
@require_POST
def update_image(request, product_id):
    return _update(request, product_id)


@staff_only
@require_POST
def update_product(request, product_id):
    return _update(request, product_id, allow_attributes=True)
