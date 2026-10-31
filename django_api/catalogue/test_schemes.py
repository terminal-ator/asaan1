import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from catalogue.models import Brand, Category, Company, OrderItem, Product, Scheme
from catalogue.schemes import discounted_total, effective_schemes


def make_product(sku, **fields):
    defaults = dict(
        name=sku, company=Company.objects.get_or_create(name="HUL")[0],
        brand=Brand.objects.get_or_create(name="Dia")[0],
        category=Category.objects.get_or_create(name="Care")[0],
        packing="Case of 12", unit="case", rate=10000, mrp=15000,
    )
    return Product.objects.create(sku=sku, **{**defaults, **fields})


class SchemeTests(TestCase):
    def setUp(self):
        self.small = make_product("DIA-S")
        self.large = make_product("DIA-L", scheme_percent=Decimal("5"))
        self.other = make_product("OTHER")
        self.scheme = Scheme.objects.create(name="Dia", percent=Decimal("3"))
        self.scheme.products.set([self.small, self.large])

    def test_best_running_scheme_wins_without_stacking(self):
        best = effective_schemes([self.small, self.large, self.other])
        self.assertEqual(best[self.small.id], (Decimal("3"), "Dia"))
        self.assertEqual(best[self.large.id], (Decimal("5"), ""))
        self.assertEqual(best[self.other.id], (Decimal("0"), ""))

    def test_inactive_and_out_of_date_schemes_are_ignored(self):
        today = timezone.localdate()
        for changes in [{"active": False}, {"starts_on": today + timedelta(days=1)}, {"ends_on": today - timedelta(days=1)}]:
            Scheme.objects.filter(pk=self.scheme.pk).update(**{"active": True, "starts_on": None, "ends_on": None, **changes})
            self.assertEqual(effective_schemes([self.small])[self.small.id][0], Decimal("0"))

    def test_catalogue_reports_the_effective_scheme(self):
        payload = self.client.get("/api/catalogue").json()
        small = next(p for p in payload["products"] if p["sku"] == "DIA-S")
        self.assertEqual((small["schemePercent"], small["schemeName"]), ("3.00", "Dia"))

    def test_order_total_takes_the_scheme_off_the_taxable_value(self):
        body = {
            "clientOrderId": "scheme-order",
            "shop": {"storeName": "Gupta", "mobile": "9876543210"},
            "items": [
                {"productId": str(self.small.id), "unit": "case", "quantity": 3},
                {"productId": str(self.other.id), "unit": "case", "quantity": 1},
            ],
        }
        response = self.client.post("/api/orders", json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        # 3 × ₹100 less 3% = ₹291, plus ₹100 with no scheme.
        self.assertEqual(response.json()["total"], 29100 + 10000)
        line = OrderItem.objects.get(sku="DIA-S")
        self.assertEqual((line.scheme_percent, line.line_total), (Decimal("3.00"), 29100))

    def test_discount_rounds_half_up_to_the_paisa(self):
        self.assertEqual(discounted_total(1, 1050, Decimal("5")), 998)  # 997.5


class ArchiveProductsCommandTests(TestCase):
    def test_dry_run_by_default_then_archives(self):
        make_product("A")
        make_product("B")
        out = StringIO()
        call_command("archive_products", stdout=out)
        self.assertIn("2 active product(s) would be archived", out.getvalue())
        self.assertEqual(Product.objects.filter(active=True).count(), 2)
        call_command("archive_products", "--yes", stdout=StringIO())
        self.assertFalse(Product.objects.filter(active=True).exists())
