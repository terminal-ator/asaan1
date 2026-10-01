"""Send notifications to shop devices that subscribed to web push."""

import json
from datetime import date

from django.conf import settings

from .models import DailyDeal, PushSubscription, Shop

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


def send_push(mobile, title, body, url="/"):
    """Best-effort push to every device registered for this mobile. Never raises."""
    if not mobile or webpush is None:
        return 0
    if not (settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY):
        return 0

    payload = json.dumps({"title": title, "body": body, "url": url})
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
        except Exception:  # noqa: BLE001 - a push failure must never break the caller
            continue
    return sent


def send_order_status(order):
    """Tell a shop its order moved forward."""
    mobile = ""
    if order.shop_record_id:
        mobile = order.shop_record.mobile
    if not mobile and isinstance(order.shop, dict):
        mobile = order.shop.get("mobile", "")
    title_template, body_template = STATUS_MESSAGES.get(
        order.status, ("Order {number}", "Status updated.")
    )
    return send_push(
        mobile,
        title_template.format(number=order.order_number),
        body_template,
        "/?orders=1",
    )


def percent_label(percent):
    value = f"{percent.normalize():f}" if hasattr(percent, "normalize") else str(percent)
    return f"{value}%"


def order_day_shops(day=None):
    """Active shops whose order day is the given date (default today)."""
    weekday = (day or date.today()).weekday()
    return [
        shop
        for shop in Shop.objects.filter(active=True)
        if weekday in (shop.order_days or [])
    ]


def send_order_day_reminders(day=None):
    """Morning nudge to shops that order today. Returns (shop count, sent)."""
    shops = order_day_shops(day)
    sent = 0
    for shop in shops:
        sent += send_push(
            shop.mobile,
            "Today is your order day",
            f"{shop.store_name}, place your order for today's delivery.",
            "/",
        )
    return len(shops), sent


def today_deal(day=None):
    weekday = (day or date.today()).weekday()
    return (
        DailyDeal.objects.filter(
            weekday=weekday, active=True, product__active=True
        )
        .select_related("product")
        .first()
    )


def send_daily_deal(day=None):
    """Push today's deal to every subscribed device. Returns (deal, sent)."""
    deal = today_deal(day)
    if not deal:
        return None, 0
    title = f"Today's deal · extra {percent_label(deal.percent)} off"
    body = f"{deal.product} — {deal.note}" if deal.note else str(deal.product)
    sent = 0
    for mobile in (
        PushSubscription.objects.values_list("mobile", flat=True).distinct()
    ):
        sent += send_push(mobile, title, body, "/")
    return deal, sent
