import json
import uuid

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Order, OrderItem, Product, Shop


# The first two digits of a GSTIN are the state code. Deriving the place of
# supply here saves the billing desk from picking a state for every order.
GST_STATE_CODES = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}


def _place_of_supply(gstin):
    return GST_STATE_CODES.get((gstin or "").strip()[:2], "")


@require_GET
def catalogue(request):
    products = Product.objects.filter(active=True).select_related(
        "company", "brand", "category"
    )
    return JsonResponse(
        {
            "products": [
                {
                    "id": str(product.id),
                    "sku": product.sku,
                    "name": product.name,
                    "simpleName": product.simple_name,
                    "company": product.company.name,
                    "brand": product.brand.name,
                    "category": product.category.name,
                    "hsnCode": product.hsn_code,
                    "packing": product.packing,
                    "unit": product.unit,
                    "rate": product.rate,
                    "mrp": product.mrp,
                    "gstRate": str(product.gst_rate),
                    "schemePercent": str(product.scheme_percent),
                    "imageUrl": product.image.url if product.image else product.image_url,
                    "updatedAt": product.updated_at.isoformat(),
                    "createdAt": product.created_at.isoformat(),
                }
                for product in products
            ]
        }
    )


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@csrf_exempt
@require_POST
def create_order(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("invalid JSON")

    if not isinstance(data, dict):
        return _error("request body must be an object")
    client_order_id = data.get("clientOrderId")
    shop_data = data.get("shop")
    items = data.get("items")
    if not isinstance(client_order_id, str) or not client_order_id.strip():
        return _error("clientOrderId is required")
    if not isinstance(shop_data, dict):
        return _error("shop is required")
    if not isinstance(shop_data.get("storeName"), str) or not shop_data["storeName"].strip():
        return _error("shop.storeName is required")
    if not isinstance(shop_data.get("mobile"), str) or not shop_data["mobile"].strip():
        return _error("shop.mobile is required")
    if not isinstance(items, list) or not items or len(items) > 500:
        return _error("items must contain between 1 and 500 entries")

    try:
        with transaction.atomic():
            existing = Order.objects.filter(client_order_id=client_order_id).first()
            if existing:
                return JsonResponse(
                    {"orderNumber": existing.order_number, "duplicate": True}
                )

            accepted = []
            total = 0
            for item in items:
                if not isinstance(item, dict):
                    return _error("each item must be an object")
                try:
                    product = Product.objects.get(
                        id=item.get("productId") or item.get("id"), active=True
                    )
                    quantity = int(item.get("quantity", 0))
                except (Product.DoesNotExist, ValueError, TypeError):
                    return _error("one or more products or quantities are invalid")
                if quantity <= 0 or quantity > 100_000:
                    return _error("quantity must be between 1 and 100000")
                if item.get("unit") != product.unit:
                    return _error("invalid product unit")
                line_total = quantity * product.rate
                total += line_total
                accepted.append((product, quantity, line_total))

            shop_data = {
                key: value.strip() if isinstance(value, str) else value
                for key, value in shop_data.items()
            }
            shop, _ = Shop.objects.get_or_create(
                mobile=shop_data["mobile"],
                store_name=shop_data["storeName"],
                defaults={
                    "customer_name": shop_data.get("customerName", ""),
                    "gstin": shop_data.get("gstin", ""),
                    "address": shop_data.get("address", ""),
                    "state": shop_data.get("state", "")
                    or _place_of_supply(shop_data.get("gstin", "")),
                    "latitude": shop_data.get("latitude"),
                    "longitude": shop_data.get("longitude"),
                    "location_accuracy": shop_data.get("locationAccuracy"),
                },
            )
            order = Order.objects.create(
                client_order_id=client_order_id,
                order_number="ORD-" + uuid.uuid4().hex[:10].upper(),
                shop=shop_data,
                shop_record=shop,
                notes=data.get("notes", "") if isinstance(data.get("notes", ""), str) else "",
                total=total,
                customer_gstin=shop_data.get("gstin", ""),
                billing_address=shop_data.get("billingAddress")
                or shop_data.get("address", ""),
                place_of_supply=shop_data.get("state", "")
                or _place_of_supply(shop_data.get("gstin", "")),
            )
            OrderItem.objects.bulk_create(
                [
                    OrderItem(
                        order=order,
                        product_id_snapshot=product.id,
                        sku=product.sku,
                        name=product.name,
                        hsn_code=product.hsn_code,
                        unit=product.unit,
                        quantity=quantity,
                        rate=product.rate,
                        gst_rate=product.gst_rate,
                        scheme_percent=product.scheme_percent,
                        line_total=line_total,
                    )
                    for product, quantity, line_total in accepted
                ]
            )
    except IntegrityError:
        existing = Order.objects.filter(client_order_id=client_order_id).first()
        if existing:
            return JsonResponse(
                {"orderNumber": existing.order_number, "duplicate": True}
            )
        return _error("could not save order", status=503)

    return JsonResponse(
        {"orderNumber": order.order_number, "total": total, "duplicate": False},
        status=201,
    )
