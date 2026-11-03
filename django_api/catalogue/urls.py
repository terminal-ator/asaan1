from django.urls import path

from . import sales

from .views import (
    catalogue,
    create_order,
    order_status,
    push_key,
    push_subscribe,
    push_unsubscribe,
)

urlpatterns = [
    path("catalogue", catalogue),
    path("orders", create_order),
    path("orders/status", order_status),
    path("push/key", push_key),
    path("push/subscribe", push_subscribe),
    path("push/unsubscribe", push_unsubscribe),
    path("sales/me", sales.me),
    path("sales/shops", sales.shops),
    path("sales/shops/<int:shop_id>/history", sales.shop_history),
    path("sales/orders", sales.create_order),
]
