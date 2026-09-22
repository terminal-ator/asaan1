import json
import uuid

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
