import csv
import io
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogue.models import Brand, Category, Company, Order, OrderItem, Product, Shop
from console.views import _consolidated_items


class ConsoleOrderFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staff", password="secret", is_staff=True
        )
        company = Company.objects.create(name="Test company")
        brand = Brand.objects.create(name="Test brand")
        category = Category.objects.create(name="Test category")
        self.product = Product.objects.create(
            sku="SKU-1",
            name="Test product",
            company=company,
            brand=brand,
            category=category,
            packing="Case",
            unit="case",
            rate=10000,
            mrp=12000,
            gst_rate=18,
        )
        self.order = Order.objects.create(
            client_order_id=str(uuid.uuid4()),
            order_number="ORD-TEST-1",
            shop={
                "storeName": "Test shop",
                "mobile": "9999999999",
                "address": "Main market",
                "gstin": "27ABCDE1234F1Z5",
            },
            total=20000,
            customer_gstin="27ABCDE1234F1Z5",
            place_of_supply="Maharashtra",
            billing_address="Main market",
        )
        OrderItem.objects.create(
            order=self.order,
            product_id_snapshot=self.product.id,
            sku="SKU-1",
            name="Test product",
            unit="case",
            quantity=2,
            rate=10000,
            gst_rate=18,
            line_total=20000,
        )

    def test_console_requires_login(self):
        response = self.client.get(
            reverse("console-order-slip", args=[self.order.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_console_nav_has_account_menu(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("console-dashboard"))
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Clear cache", content)
        self.assertIn(reverse("logout"), content)
        self.assertIn("Log out", content)

    def test_logout_ends_the_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/admin/login/"))
        self.assertEqual(
            self.client.get(reverse("console-dashboard")).status_code, 302
        )

    def test_shop_form_requires_name_and_mobile(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("console-shop-new"),
            {"store_name": "   ", "mobile": "", "active": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertFalse(Shop.objects.exists())

    def test_order_slip_shows_rupees_without_invoice_number(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("console-order-slip", args=[self.order.id])
        )
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("ORD-TEST-1", content)
        self.assertIn("Test product", content)
        self.assertIn("200.00", content)  # 20000 paise line total
        self.assertNotIn("Tax invoice", content)

    def test_order_items_export_has_one_row_per_line(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("console-order-items-export"))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][:2], ["order_number", "created_at"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "ORD-TEST-1")
        self.assertEqual(rows[1][8], "SKU-1")
        self.assertEqual(rows[1][12], "2")  # quantity
        self.assertEqual(rows[1][13], "10000")  # rate in paise

    def test_order_items_export_respects_date_filters(self):
        self.client.force_login(self.user)
        old = self.client.get(
            reverse("console-order-items-export"),
            {"to": "2000-01-01"},
        )
        today = self.client.get(
            reverse("console-order-items-export"),
            {"from": "2000-01-01"},
        )
        self.assertEqual(len(old.content.decode().strip().splitlines()), 1)
        self.assertEqual(len(today.content.decode().strip().splitlines()), 2)

    def test_convert_to_invoices_is_paused(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("console-dispatch-summary"),
            {"order_ids": [str(self.order.id)], "action": "convert"},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.invoice_number, "")
        self.assertIsNone(self.order.loading_id)

    def test_creating_a_loading_groups_the_selected_bills(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("console-dispatch-summary"),
            {"order_ids": [str(self.order.id)], "action": "loading"},
        )
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.loading_id)

    def test_console_pages_render(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("console-dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("console-sales-register")).status_code, 200)
        self.assertEqual(self.client.get(reverse("console-gst-report")).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("console-order-detail", args=[self.order.id])
            ).status_code,
            200,
        )

    def test_loading_page_includes_order_slips(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("console-dispatch-summary"),
            {"order_ids": [str(self.order.id)], "action": "loading"},
        )
        self.order.refresh_from_db()
        response = self.client.get(
            reverse("console-loading-detail", args=[self.order.loading_id])
        )
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Consolidated items to load", content)
        self.assertIn("Order slip", content)
        self.assertIn("ORD-TEST-1", content)

    def test_slips_render_for_orders_without_gstin_or_address_keys(self):
        # Orders placed before the GSTIN field exist in the database without
        # those keys in the shop snapshot; every slip must still render.
        old_order = Order.objects.create(
            client_order_id=str(uuid.uuid4()),
            order_number="ORD-TEST-3",
            shop={"storeName": "Old shop", "mobile": "7777777777"},
            total=10000,
        )
        OrderItem.objects.create(
            order=old_order,
            product_id_snapshot=self.product.id,
            sku="SKU-1",
            name="Test product",
            unit="case",
            quantity=1,
            rate=10000,
            gst_rate=18,
            line_total=10000,
        )
        self.client.force_login(self.user)
        for url in (
            reverse("console-order-slip", args=[old_order.id]),
            reverse("console-order-packing-slip", args=[old_order.id]),
            reverse("console-order-detail", args=[old_order.id]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(
            reverse("console-dispatch-summary"),
            {"order_ids": [str(old_order.id)], "action": "loading"},
        )
        old_order.refresh_from_db()
        self.assertEqual(
            self.client.get(
                reverse("console-loading-detail", args=[old_order.loading_id])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("console-loading-packing-slips", args=[old_order.loading_id])
            ).status_code,
            200,
        )

    def test_pick_list_consolidates_quantities_and_bills(self):
        second = Order.objects.create(
            client_order_id=str(uuid.uuid4()),
            order_number="ORD-TEST-2",
            shop={"storeName": "Second shop", "mobile": "8888888888"},
            total=30000,
        )
        OrderItem.objects.create(
            order=second,
            product_id_snapshot=self.product.id,
            sku="SKU-1",
            name="Test product",
            unit="case",
            quantity=3,
            rate=10000,
            gst_rate=18,
            line_total=30000,
        )
        rows = _consolidated_items([self.order, second])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], 5)
        self.assertEqual(rows[0]["bills"], 2)
        self.assertEqual(rows[0]["company"], "Test company")

    def test_dispatch_summary_includes_pick_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("console-dispatch-summary"))
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pick list", content)
        self.assertIn("SKU-1", content)
        self.assertIn("Test company", content)

    def test_single_packing_slip_is_dense_and_has_no_prices(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("console-order-packing-slip", args=[self.order.id])
        )
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Packing slip", content)
        self.assertIn("ORD-TEST-1", content)
        self.assertIn("2 case", content)
        self.assertNotIn("₹", content)

    def test_loading_packing_slips_cover_every_bill(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("console-dispatch-summary"),
            {"order_ids": [str(self.order.id)], "action": "loading"},
        )
        self.order.refresh_from_db()
        response = self.client.get(
            reverse("console-loading-packing-slips", args=[self.order.loading_id])
        )
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Packing slip", content)
        self.assertIn("Test shop", content)
        self.assertIn("ORD-TEST-1", content)
