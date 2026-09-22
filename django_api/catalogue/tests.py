import json
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import Brand, Category, Company, Order, OrderItem, Product


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

    def test_no_margin_when_mrp_does_not_exceed_the_rate(self):
        self.product.mrp = 7000
        self.assertEqual(self.product.retail_margin, 0)
        self.assertEqual(self.product.retail_margin_percent, Decimal("0.0"))
