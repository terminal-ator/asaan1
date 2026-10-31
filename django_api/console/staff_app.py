"""Asaan Staff: an installable phone app for adding and editing products.

It reuses the product workspace endpoints for listing, editing and photos, and
adds a create endpoint that takes the photo in the same request.
"""

from decimal import Decimal, InvalidOperation

from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from catalogue.models import HSN, Brand, Category, Company, Product
from .product_media import ImageUpdateForm, optimized_image, product_data, staff_only
from .quick_add import ProductQuickAddForm

APP_SCOPE = "/console/app/"

# Network only: product data must always be live. The worker exists so phones
# offer "Install app", and to show a clear message when the network drops.
SERVICE_WORKER = """
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font-family:system-ui;padding:32px;color:#1c1b19;background:#f6f5f1">' +
    '<h1 style="font-size:20px">You are offline</h1><p>Asaan Products needs the internet to save changes. ' +
    'Reconnect and pull down to reload.</p></body>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
  )))
})
"""


@staff_member_required
@require_GET
def app(request):
    return render(request, "console/staff_app.html")


@require_GET
def manifest(request):
    icon = static("console/staff-icon.svg")
    return JsonResponse(
        {
            "id": APP_SCOPE,
            "name": "Asaan Products",
            "short_name": "Products",
            "description": "Add and edit the Asaan catalogue from your phone.",
            "start_url": APP_SCOPE,
            "scope": APP_SCOPE,
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#f6f5f1",
            "theme_color": "#33459e",
            "icons": [{"src": icon, "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
        },
        content_type="application/manifest+json",
    )


@require_GET
def service_worker(request):
    response = HttpResponse(SERVICE_WORKER, content_type="text/javascript")
    response["Service-Worker-Allowed"] = APP_SCOPE
    response["Cache-Control"] = "no-cache"
    return response


@staff_only
@require_POST
def create_product(request):
    sku = request.POST.get("sku", "").strip()
    archived = (
        Product.objects.filter(sku=sku, active=False).select_related("company", "brand", "category").first()
        if sku else None
    )
    if archived:
        return JsonResponse({
            "error": f"SKU {sku} belongs to an archived product. Restore it instead of adding it again.",
            "archived": product_data(archived),
        }, status=409)

    form = ProductQuickAddForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Check the product details.", "errors": form.errors.get_json_data()}, status=400)

    photo = None
    if request.FILES.get("image"):
        image_form = ImageUpdateForm({"action": "upload", "version": "new"}, request.FILES)
        if not image_form.is_valid():
            return JsonResponse({"error": "Check the photo.", "errors": image_form.errors.get_json_data()}, status=400)
        try:
            photo = optimized_image(image_form.cleaned_data["image"])
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            return JsonResponse({"error": "This photo could not be read. Try a JPEG, PNG or WebP photo."}, status=400)

    with transaction.atomic():
        product = form.save(commit=False)
        if photo:
            product.image = photo
        product.save()
    product = Product.objects.select_related("company", "brand", "category").get(pk=product.pk)
    return JsonResponse({"product": product_data(product)}, status=201)


MASTERS = {"company": Company, "brand": Brand, "category": Category}


@staff_only
@require_POST
def update_master(request, kind, master_id):
    """Rename a company, brand or category, or correct an HSN code and its default GST."""
    name = request.POST.get("name", "").strip()
    if kind in MASTERS:
        model = MASTERS[kind]
        obj = model.objects.filter(pk=master_id).first()
        if obj is None:
            return JsonResponse({"error": f"That {kind} no longer exists."}, status=404)
        if not name:
            return JsonResponse({"error": "Enter a name."}, status=400)
        if len(name) > model._meta.get_field("name").max_length:
            return JsonResponse({"error": "That name is too long."}, status=400)
        if model.objects.filter(name__iexact=name).exclude(pk=obj.pk).exists():
            return JsonResponse({"error": f"“{name}” already exists. Pick it from the list instead."}, status=400)
        obj.name = name
        obj.save(update_fields=["name"])
        return JsonResponse({"id": obj.pk, "name": obj.name})

    if kind == "hsn":
        obj = HSN.objects.filter(pk=master_id).first()
        if obj is None:
            return JsonResponse({"error": "That HSN no longer exists."}, status=404)
        if not name:
            return JsonResponse({"error": "Enter the HSN code."}, status=400)
        if len(name) > HSN._meta.get_field("code").max_length:
            return JsonResponse({"error": "That HSN code is too long."}, status=400)
        try:
            rate = Decimal(request.POST.get("default_gst_rate", obj.default_gst_rate))
        except InvalidOperation:
            return JsonResponse({"error": "GST must be a number."}, status=400)
        if not Decimal("0") <= rate <= Decimal("100"):
            return JsonResponse({"error": "GST must be between 0 and 100."}, status=400)
        if HSN.objects.filter(code__iexact=name).exclude(pk=obj.pk).exists():
            return JsonResponse({"error": f"HSN {name} already exists. Pick it from the list instead."}, status=400)
        with transaction.atomic():
            obj.code = name
            obj.default_gst_rate = rate
            obj.save(update_fields=["code", "default_gst_rate"])
            # Products keep a copy of the code for slips and exports; keep it in step.
            # Their GST % is left alone: a new default applies to products saved later.
            Product.objects.filter(hsn=obj).update(hsn_code=obj.code)
        return JsonResponse({"id": obj.pk, "code": obj.code, "description": obj.description, "default_gst_rate": str(obj.default_gst_rate)})

    return JsonResponse({"error": "Unsupported master."}, status=400)
