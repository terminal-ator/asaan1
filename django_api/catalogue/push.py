"""Send order-status notifications to shop devices that subscribed."""

import json

from django.conf import settings

from .models import PushSubscription

try:  # importable without the dependency so tests and dev machines run anyway
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover
    webpush = None
    WebPushException = Exception

STATUS_MESSAGES = {
    "received": ("Order {number} received", "We have your order and will start soon."),
    "processing": ("Order {number} is being prepared", "We are packing your order now."),
    "completed": ("Order {number} is ready", "Your order is completed. Thank you!"),
    "cancelled": ("Order {number} was cancelled", "Please contact us if this is unexpected."),
}


def send_order_status(order):
    """Best-effort push to the shop's devices. Never raises."""
    if not (settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY):
        return 0
    mobile = ""
    if order.shop_record_id:
        mobile = order.shop_record.mobile
    if not mobile and isinstance(order.shop, dict):
        mobile = order.shop.get("mobile", "")
    if not mobile:
        return 0

    title_template, body_template = STATUS_MESSAGES.get(
        order.status, ("Order {number}", "Status updated.")
    )
    payload = json.dumps(
        {
            "title": title_template.format(number=order.order_number),
            "body": body_template,
            "url": "/?orders=1",
        }
    )

    if webpush is None:  # pragma: no cover
        return 0

    sent = 0
    for subscription in PushSubscription.objects.filter(mobile=mobile):
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": subscription.keys,
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={
                    "sub": f"mailto:{settings.VAPID_ADMIN_EMAIL or 'admin@asaan.in'}"
                },
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                subscription.delete()
    return sent
