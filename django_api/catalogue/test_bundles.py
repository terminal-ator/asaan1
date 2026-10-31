import json
import uuid

from django.test import TestCase

from .models import Brand, Category, Company, Order, Product, ProductBundle, ProductBundleItem, Shop


class BundleApiTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="BUNDLE-1", name="Soap", company=Company.objects.create(name="Company"),
            brand=Brand.objects.create(name="Brand"), category=Category.objects.create(name="Care"),
            unit="case", packing="Case", rate=10000, mrp=15000, gst_rate=18,
        )
        self.bundle = ProductBundle.objects.create(name="Everyday care", shop_type="kirana")
        ProductBundleItem.objects.create(bundle=self.bundle, product=self.product, quantity=2)

    def test_catalogue_supplies_shop_types_and_configured_products(self):
        payload = self.client.get("/api/catalogue").json()
        self.assertIn({"id": "kirana", "name": "Kirana / general store"}, payload["shopTypes"])
        self.assertEqual(payload["bundles"], [{
            "id": str(self.bundle.pk), "name": "Everyday care", "shopType": "kirana",
            "description": "", "items": [{"productId": str(self.product.pk), "quantity": 2}],
        }])
        self.assertEqual(payload["products"][0]["rateInclusive"], 11800)

    def test_hidden_and_empty_bundles_are_excluded(self):
        self.bundle.active = False
        self.bundle.save()
        ProductBundle.objects.create(name="Empty", shop_type="cosmetics")
        self.assertEqual(self.client.get("/api/catalogue").json()["bundles"], [])

    def test_inactive_products_are_excluded_and_empty_bundle_disappears(self):
        inactive = Product.objects.create(
            sku="BUNDLE-2", name="Inactive", company=self.product.company,
            brand=self.product.brand, category=self.product.category, unit="case",
            rate=100, mrp=200, active=False,
        )
        ProductBundleItem.objects.create(bundle=self.bundle, product=inactive)
        bundle = self.client.get("/api/catalogue").json()["bundles"][0]
        self.assertEqual(len(bundle["items"]), 1)
        self.product.active = False
        self.product.save()
        self.assertEqual(self.client.get("/api/catalogue").json()["bundles"], [])

    def order_payload(self, **shop_fields):
        return {
            "clientOrderId": str(uuid.uuid4()),
            "shop": {"storeName": "Shop", "mobile": "9999999999", **shop_fields},
            "items": [{"productId": str(self.product.pk), "unit": "case", "quantity": 1}],
        }

    def test_order_retains_shop_type_and_selected_bundle_snapshot(self):
        data = self.order_payload(shopType="kirana", bundleIds=[str(self.bundle.pk)])
        response = self.client.post("/api/orders", json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Shop.objects.get().shop_type, "kirana")
        self.assertEqual(Order.objects.get().shop["bundleIds"], [str(self.bundle.pk)])

    def test_existing_shop_type_updates_on_next_order(self):
        shop = Shop.objects.create(store_name="Shop", mobile="9999999999", shop_type="kirana")
        data = self.order_payload(shopType="supermarket")
        self.client.post("/api/orders", json.dumps(data), content_type="application/json")
        shop.refresh_from_db()
        self.assertEqual(shop.shop_type, "supermarket")

    def test_unknown_shop_type_is_rejected_without_writing(self):
        for shop_type in ("unknown", 123, ["kirana"]):
            data = self.order_payload(shopType=shop_type)
            response = self.client.post("/api/orders", json.dumps(data), content_type="application/json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Shop.objects.exists())
