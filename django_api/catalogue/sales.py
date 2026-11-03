"""Salesman mode: staff use the shop app to take orders on a shop's behalf.

These endpoints use the console sign-in (session cookie), so unlike the shop
app's anonymous order endpoint they are CSRF protected.
"""
from functools import wraps

from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Shop
from .views import place_order


def salesman_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_active and user.is_staff):
            return JsonResponse({"error": "Sign in with a staff account to take orders for shops."}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def shop_data(shop):
    return {
        "id": shop.id,
        "storeName": shop.store_name,
        "customerName": shop.customer_name,
        "mobile": shop.mobile,
        "shopType": shop.shop_type,
        "gstin": shop.gstin,
        "address": shop.address,
        "state": shop.state,
        "orderCount": shop.order_count,
        "lastOrderAt": shop.last_order_at.isoformat() if shop.last_order_at else None,
    }


@require_GET
@ensure_csrf_cookie
@salesman_only
def me(request):
    user = request.user
    return JsonResponse({"username": user.get_username(), "name": user.get_full_name() or user.get_username()})


@require_GET
@salesman_only
def shops(request):
    items = Shop.objects.filter(active=True).annotate(order_count=Count("orders"), last_order_at=Max("orders__created_at"))
    for word in request.GET.get("q", "").strip().split():
        items = items.filter(
            Q(store_name__icontains=word) | Q(customer_name__icontains=word)
            | Q(mobile__icontains=word) | Q(address__icontains=word)
        )
    # Shops ordered from most recently, then the rest by name.
    items = items.order_by(F("last_order_at").desc(nulls_last=True), "store_name")[:60]
    return JsonResponse({"shops": [shop_data(shop) for shop in items]})


@require_POST
@salesman_only
def create_order(request):
    return place_order(request.body, taken_by=request.user)


@require_GET
@salesman_only
def shop_history(request, shop_id):
    """The shop's last order and what it usually buys, from every device it ordered on."""
    shop = Shop.objects.filter(pk=shop_id, active=True).first()
    if not shop:
        return JsonResponse({"error": "That shop is no longer active."}, status=404)
    orders = list(shop.orders.exclude(status="cancelled").prefetch_related("items")[:20])
    bought = {}
    for order in orders:
        for item in order.items.all():
            key = str(item.product_id_snapshot)
            bought[key] = bought.get(key, 0) + item.quantity
    last = orders[0] if orders else None
    return JsonResponse({
        "lastOrder": {
            "orderNumber": last.order_number,
            "createdAt": last.created_at.isoformat(),
            "items": [
                {"productId": str(item.product_id_snapshot), "unit": item.unit, "quantity": item.quantity}
                for item in last.items.all()
            ],
        } if last else None,
        "usual": sorted(bought, key=bought.get, reverse=True)[:8],
    })
