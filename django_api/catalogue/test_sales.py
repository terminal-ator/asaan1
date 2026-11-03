import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from catalogue.models import Order, Shop
from catalogue.test_schemes import make_product


class SalesmanModeTests(TestCase):
    def setUp(self):
        self.product = make_product("DIA-S")
        self.salesman = get_user_model().objects.create_user("ravi", first_name="Ravi", is_staff=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.salesman)
        self.shop = Shop.objects.create(store_name="Gupta Stores", mobile="9800000001", customer_name="Amit")
        Shop.objects.create(store_name="Old Shop", mobile="9800000002", active=False)

    def order(self, client_order_id="sales-1", **headers):
        body = {
            "clientOrderId": client_order_id,
            "shop": {"storeName": "Gupta Stores", "mobile": "9800000001"},
            "items": [{"productId": str(self.product.id), "unit": "case", "quantity": 2}],
        }
        return self.client.post("/api/sales/orders", json.dumps(body), content_type="application/json", **headers)

    def csrf(self):
        self.client.get("/api/sales/me")
        return {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def test_staff_only(self):
        anonymous = Client()
        self.assertEqual(anonymous.get("/api/sales/me").status_code, 403)
        self.assertEqual(anonymous.get("/api/sales/shops").status_code, 403)
        shopkeeper = get_user_model().objects.create_user("shopkeeper")
        anonymous.force_login(shopkeeper)
        self.assertEqual(anonymous.get("/api/sales/shops").status_code, 403)

    def test_me_names_the_salesman_and_sets_the_csrf_cookie(self):
        response = self.client.get("/api/sales/me")
        self.assertEqual(response.json(), {"username": "ravi", "name": "Ravi"})
        self.assertIn("csrftoken", response.cookies)

    def test_shop_list_searches_active_shops_recent_first(self):
        fresh = Shop.objects.create(store_name="Agarwal Mart", mobile="9800000003")
        self.order(**self.csrf())
        names = [shop["storeName"] for shop in self.client.get("/api/sales/shops").json()["shops"]]
        self.assertEqual(names, ["Gupta Stores", fresh.store_name])
        found = self.client.get("/api/sales/shops", {"q": "amit"}).json()["shops"]
        self.assertEqual([(shop["storeName"], shop["orderCount"]) for shop in found], [("Gupta Stores", 1)])

    def test_order_records_who_took_it(self):
        response = self.order(**self.csrf())
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(client_order_id="sales-1")
        self.assertEqual((order.taken_by, order.shop_record), (self.salesman, self.shop))

    def test_order_needs_the_csrf_token(self):
        self.assertEqual(self.order().status_code, 403)
        self.assertFalse(Order.objects.exists())

    def test_shop_app_orders_have_no_salesman(self):
        body = {"clientOrderId": "shop-1", "shop": {"storeName": "Gupta Stores", "mobile": "9800000001"}, "items": [{"productId": str(self.product.id), "unit": "case", "quantity": 1}]}
        self.assertEqual(Client().post("/api/orders", json.dumps(body), content_type="application/json").status_code, 201)
        self.assertIsNone(Order.objects.get(client_order_id="shop-1").taken_by)

    def test_history_returns_last_order_and_usual_products(self):
        other = make_product("DIA-L")
        self.order(**self.csrf())
        headers = self.csrf()
        body = {"clientOrderId": "sales-2", "shop": {"storeName": "Gupta Stores", "mobile": "9800000001"}, "items": [{"productId": str(other.id), "unit": "case", "quantity": 1}]}
        self.client.post("/api/sales/orders", json.dumps(body), content_type="application/json", **headers)
        history = self.client.get(f"/api/sales/shops/{self.shop.id}/history").json()
        self.assertEqual(history["lastOrder"]["items"], [{"productId": str(other.id), "unit": "case", "quantity": 1}])
        self.assertEqual(history["usual"], [str(self.product.id), str(other.id)])
        self.assertEqual(self.client.get("/api/sales/shops/999/history").status_code, 404)
