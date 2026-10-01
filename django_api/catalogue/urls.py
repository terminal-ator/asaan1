from django.urls import path

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
]
