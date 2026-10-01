import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import (
    Brand,
    Category,
    Company,
    DailyDeal,
    Order,
    OrderItem,
    Product,
    PushSubscription,
    Shop,
)
from .push import send_daily_deal, send_order_day_reminders, send_order_status


class OrderApiTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="TEST-001",
            name="Test product",
            company=Company.objects.create(name="Test company"),
            brand=Brand.objects.create(name="Test brand"),
            category=Category.objects.create(name="Test category"),
            packing="Case",
            unit="case",
            rate=10000,
            mrp=12000,
        )

    def payload(self, quantity=2):
        return {
            "clientOrderId": str(uuid.uuid4()),
            "shop": {"storeName": "Test shop", "mobile": "9999999999"},
            "items": [
                {
                    "productId": str(self.product.id),
                    "unit": "case",
                    "quantity": quantity,
                }
            ],
        }

    def test_invalid_quantity_is_a_bad_request_without_writing(self):
        response = self.client.post(
            "/api/orders",
            data=json.dumps(self.payload("not-a-number")),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_and_items_are_created_atomically(self):
        response = self.client.post(
            "/api/orders",
            data=json.dumps(self.payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_repeating_client_order_id_is_idempotent(self):
        payload = self.payload()
        first = self.client.post(
            "/api/orders", data=json.dumps(payload), content_type="application/json"
        )
        second = self.client.post(
            "/api/orders", data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(Order.objects.count(), 1)

    def test_gstin_fills_customer_gstin_and_place_of_supply(self):
        payload = self.payload()
        payload["shop"] = {
            "storeName": "Test shop",
            "mobile": "9999999999",
            "gstin": "27abcde1234f1z5",
        }
        response = self.client.post(
            "/api/orders", data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(order.customer_gstin, "27abcde1234f1z5")
        self.assertEqual(order.place_of_supply, "Maharashtra")
        self.assertEqual(order.shop_record.gstin, "27abcde1234f1z5")

    def test_catalogue_includes_scheme_percent(self):
        self.product.scheme_percent = "10.00"
        self.product.save(update_fields=["scheme_percent"])
        response = self.client.get("/api/catalogue")
        self.assertEqual(response.json()["products"][0]["schemePercent"], "10.00")

    def test_catalogue_includes_the_tax_inclusive_rate(self):
        self.product.gst_rate = "18.00"
        self.product.save(update_fields=["gst_rate"])
        response = self.client.get("/api/catalogue")
        product = response.json()["products"][0]
        self.assertEqual(product["rate"], 10000)
        self.assertEqual(product["rateInclusive"], 11800)

    def test_catalogue_includes_the_regular_flag(self):
        self.product.regular = True
        self.product.save(update_fields=["regular"])
        response = self.client.get("/api/catalogue")
        self.assertTrue(response.json()["products"][0]["regular"])

    def test_order_snapshots_the_scheme(self):
        self.product.scheme_percent = "7.50"
        self.product.save(update_fields=["scheme_percent"])
        response = self.client.post(
            "/api/orders", data=json.dumps(self.payload()), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(str(OrderItem.objects.get().scheme_percent), "7.50")

    def test_shop_name_and_mobile_are_required(self):
        for shop in (
            {"storeName": "   ", "mobile": "9999999999"},
            {"storeName": "Test shop", "mobile": "   "},
            {"storeName": "", "mobile": "9999999999"},
            {"storeName": "Test shop", "mobile": ""},
        ):
            payload = {**self.payload(), "shop": shop}
            response = self.client.post(
                "/api/orders", data=json.dumps(payload), content_type="application/json"
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_health_endpoint_reports_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class OrderStatusApiTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            client_order_id="status-1",
            order_number="ORD-STATUS-1",
            shop={"storeName": "Shop", "mobile": "9999999999"},
            total=100,
            status="processing",
        )

    def test_status_endpoint_returns_console_status(self):
        response = self.client.get("/api/orders/status?ids=status-1,missing")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["orders"],
            [
                {
                    "clientOrderId": "status-1",
                    "orderNumber": "ORD-STATUS-1",
                    "status": "processing",
                }
            ],
        )

    def test_push_key_is_empty_until_configured(self):
        self.assertEqual(self.client.get("/api/push/key").json()["key"], "")
        with override_settings(VAPID_PUBLIC_KEY="BC-test-key"):
            self.assertEqual(
                self.client.get("/api/push/key").json()["key"], "BC-test-key"
            )

    def test_push_subscription_is_stored_and_removed(self):
        body = {
            "mobile": "9999999999",
            "subscription": {
                "endpoint": "https://push.example/abc",
                "keys": {"p256dh": "key", "auth": "secret"},
            },
        }
        response = self.client.post(
            "/api/push/subscribe",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.mobile, "9999999999")

        response = self.client.post(
            "/api/push/unsubscribe",
            data=json.dumps({"endpoint": "https://push.example/abc"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(VAPID_PRIVATE_KEY="private", VAPID_PUBLIC_KEY="public")
    @patch("catalogue.push.webpush")
    def test_status_push_reaches_subscribed_devices(self, webpush):
        PushSubscription.objects.create(
            mobile="9999999999",
            endpoint="https://push.example/abc",
            keys={"p256dh": "key", "auth": "secret"},
        )
        self.assertEqual(send_order_status(self.order), 1)
        webpush.assert_called_once()

    @override_settings(VAPID_PRIVATE_KEY="private", VAPID_PUBLIC_KEY="public")
    @patch("catalogue.push.webpush")
    def test_gone_subscription_is_deleted(self, webpush):
        from pywebpush import WebPushException

        class Gone:
            status_code = 410

        webpush.side_effect = WebPushException("gone", response=Gone())
        PushSubscription.objects.create(
            mobile="9999999999",
            endpoint="https://push.example/abc",
            keys={"p256dh": "key", "auth": "secret"},
        )
        send_order_status(self.order)
        self.assertFalse(PushSubscription.objects.exists())


class NotificationPushTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Deal Co")
        self.brand = Brand.objects.create(name="Deal Brand")
        self.category = Category.objects.create(name="Deal Cat")
        self.product = Product.objects.create(
            sku="DEAL-1",
            name="Deal item",
            company=self.company,
            brand=self.brand,
            category=self.category,
            packing="Box",
            unit="box",
            rate=1000,
            mrp=1200,
        )
        self.today = date.today().weekday()

    def test_catalogue_includes_daily_deals(self):
        DailyDeal.objects.create(
            weekday=self.today, product=self.product, percent="8.00", note="Today only"
        )
        response = self.client.get("/api/catalogue")
        deals = response.json()["deals"]
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["weekday"], self.today)
        self.assertEqual(deals[0]["productId"], str(self.product.id))
        self.assertEqual(deals[0]["percent"], "8.00")

    @override_settings(VAPID_PRIVATE_KEY="private", VAPID_PUBLIC_KEY="public")
    @patch("catalogue.push.webpush")
    def test_order_day_reminder_only_reaches_todays_shops(self, webpush):
        Shop.objects.create(
            store_name="Today shop", mobile="9000000001", order_days=[self.today]
        )
        Shop.objects.create(
            store_name="Other shop",
            mobile="9000000002",
            order_days=[(self.today + 1) % 7],
        )
        PushSubscription.objects.create(
            mobile="9000000001",
            endpoint="https://push.example/a",
            keys={"p256dh": "k", "auth": "s"},
        )
        PushSubscription.objects.create(
            mobile="9000000002",
            endpoint="https://push.example/b",
            keys={"p256dh": "k", "auth": "s"},
        )
        shops, sent = send_order_day_reminders()
        self.assertEqual(shops, 1)
        self.assertEqual(sent, 1)
        self.assertEqual(webpush.call_count, 1)
        payload = json.loads(webpush.call_args.kwargs["data"])
        self.assertEqual(payload["title"], "Today is your order day")
        self.assertIn("Today shop", payload["body"])

    @override_settings(VAPID_PRIVATE_KEY="private", VAPID_PUBLIC_KEY="public")
    @patch("catalogue.push.webpush")
    def test_daily_deal_push_reaches_subscribers(self, webpush):
        DailyDeal.objects.create(weekday=self.today, product=self.product, percent="8.00")
        PushSubscription.objects.create(
            mobile="9000000001",
            endpoint="https://push.example/a",
            keys={"p256dh": "k", "auth": "s"},
        )
        deal, sent = send_daily_deal()
        self.assertIsNotNone(deal)
        self.assertEqual(sent, 1)
        payload = json.loads(webpush.call_args.kwargs["data"])
        self.assertIn("Deal item", payload["body"])
        self.assertIn("8%", payload["title"])


class AdminProductImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin", password="secret", email="admin@example.com"
        )
        self.client.force_login(self.user)

    def import_csv(self, body):
        upload = SimpleUploadedFile("items.csv", body.encode(), content_type="text/csv")
        return self.client.post("/admin/catalogue/product/import-csv/", {"file": upload})

    def test_import_reads_scheme_gst_and_hsn(self):
        response = self.import_csv(
            "sku,name,company,brand,category,packing,unit,sale_rate,mrp,gst_rate,scheme_percent,hsn_code\n"
            "ADM-1,Admin item,Co,Brand,Cat,Box of 12,box,10.00,12.00,18,7.5,3402\n"
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(sku="ADM-1")
        self.assertEqual(product.rate, 1000)
        self.assertEqual(str(product.gst_rate), "18.00")
        self.assertEqual(str(product.scheme_percent), "7.50")
        self.assertEqual(product.hsn_code, "3402")

    def test_import_rejects_a_scheme_above_100(self):
        response = self.import_csv(
            "sku,name,company,brand,category,packing,unit,sale_rate,mrp,scheme_percent\n"
            "ADM-2,Bad scheme,Co,Brand,Cat,Box,box,10.00,12.00,150\n"
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(sku="ADM-2").exists())

    def test_import_reads_the_regular_flag(self):
        response = self.import_csv(
            "sku,name,company,brand,category,packing,unit,sale_rate,mrp,regular\n"
            "ADM-3,Best seller,Co,Brand,Cat,Box,box,10.00,12.00,yes\n"
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.get(sku="ADM-3").regular)

    def test_reimport_without_the_regular_column_keeps_the_flag(self):
        company = Company.objects.create(name="Keep Co")
        brand = Brand.objects.create(name="Keep Brand")
        category = Category.objects.create(name="Keep Cat")
        product = Product.objects.create(
            sku="ADM-4",
            name="Kept item",
            company=company,
            brand=brand,
            category=category,
            packing="Box",
            unit="box",
            rate=1000,
            mrp=1200,
            regular=True,
        )
        response = self.import_csv(
            "sku,name,company,brand,category,packing,unit,sale_rate,mrp\n"
            "ADM-4,Kept item,Keep Co,Keep Brand,Keep Cat,Box,box,10.00,12.00\n"
        )
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertTrue(product.regular)


class ProductMarginTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="M-1",
            name="Margin item",
            company=Company.objects.create(name="Margin Co"),
            brand=Brand.objects.create(name="Margin Brand"),
            category=Category.objects.create(name="Margin Cat"),
            packing="Box",
            unit="box",
            rate=8000,
            mrp=10000,
        )

    def test_retail_margin_per_unit_and_percent_of_mrp(self):
        self.assertEqual(self.product.retail_margin, 2000)
        self.assertEqual(self.product.retail_margin_percent, Decimal("20.0"))

    def test_margin_does_not_count_gst_as_profit(self):
        self.product.gst_rate = Decimal("18.00")
        # ₹100 MRP - (₹80 + 18% GST = ₹94.40) = ₹5.60, not ₹20.
        self.assertEqual(self.product.rate_inclusive, 9440)
        self.assertEqual(self.product.retail_margin, 560)
        self.assertEqual(self.product.retail_margin_percent, Decimal("5.6"))

    def test_no_margin_when_mrp_does_not_exceed_the_rate(self):
        self.product.mrp = 7000
        self.assertEqual(self.product.retail_margin, 0)
        self.assertEqual(self.product.retail_margin_percent, Decimal("0.0"))
