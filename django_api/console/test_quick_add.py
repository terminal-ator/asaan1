from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogue.models import HSN, Brand, Category, Company, Product, Scheme


class QuickAddTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="staff", is_staff=True))
        self.company = Company.objects.create(name="HUL")
        self.brand = Brand.objects.create(name="Dia")
        self.category = Category.objects.create(name="Care")
        self.hsn = HSN.objects.create(code="3401", default_gst_rate="18")
        self.url = reverse("console-product-quick-add")

    def payload(self, **changes):
        return {
            "name": "Dia Soap 100g", "company_name": self.company.pk, "brand_name": self.brand.pk,
            "category_name": self.category.pk, "packing": "Case of 48", "unit": "case",
            "rate": "1200.00", "mrp": "1680.00", "hsn": self.hsn.pk, "gst_rate": "", "sku": "",
            "next": "another", **changes,
        }

    def test_save_and_add_another_carries_masters_and_fills_defaults(self):
        response = self.client.post(self.url, self.payload())
        product = Product.objects.get()
        self.assertEqual(product.sku, "DIA-SOAP-100G")
        self.assertEqual(product.rate, 120000)
        self.assertEqual(str(product.gst_rate), "18.00")
        self.assertTrue(product.active)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"brand_name={self.brand.pk}", response["Location"])
        page = self.client.get(response["Location"])
        self.assertContains(page, "carried over")
        self.assertContains(page, f'<option value="{self.brand.pk}" selected>')

    def test_generated_skus_stay_unique_and_save_returns_to_list(self):
        self.client.post(self.url, self.payload())
        response = self.client.post(self.url, self.payload(next="done"))
        self.assertRedirects(response, reverse("console-products"))
        self.assertEqual(set(Product.objects.values_list("sku", flat=True)), {"DIA-SOAP-100G", "DIA-SOAP-100G-2"})

    def test_archived_sku_points_to_restore_and_restore_reactivates(self):
        self.client.post(self.url, self.payload(sku="M-1"))
        product = Product.objects.get()
        Product.objects.update(active=False)
        response = self.client.post(self.url, self.payload(sku="M-1"))
        self.assertContains(response, "archived product")
        self.assertContains(self.client.get(self.url, {"find": "dia"}), "Restore")
        self.client.post(reverse("console-product-restore", args=[product.pk]), {"find": "dia"})
        product.refresh_from_db()
        self.assertTrue(product.active)

    def test_products_list_defaults_to_active(self):
        self.client.post(self.url, self.payload(name="Live soap"))
        self.client.post(self.url, self.payload(name="Old soap"))
        Product.objects.filter(name="Old soap").update(active=False)
        self.client.get(reverse("console-products"))  # use up the "Added …" messages
        listing = self.client.get(reverse("console-products"))
        self.assertContains(listing, "Live soap")
        self.assertNotContains(listing, "Old soap")
        self.assertContains(self.client.get(reverse("console-products"), {"status": "archived"}), "Old soap")


class SchemeConsoleTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="staff", is_staff=True))
        common = dict(company=Company.objects.create(name="HUL"), brand=Brand.objects.create(name="Dia"),
                      category=Category.objects.create(name="Care"), packing="Case", unit="case", rate=100, mrp=150)
        self.products = [Product.objects.create(sku=f"DIA-{n}", name=f"Dia {n}", **common) for n in range(3)]

    def test_create_scheme_for_many_skus(self):
        response = self.client.post(reverse("console-scheme-create"), {
            "name": "Dia 3%", "percent": "3", "active": "on",
            "products": [str(product.pk) for product in self.products],
        })
        self.assertRedirects(response, reverse("console-schemes"))
        scheme = Scheme.objects.get()
        self.assertEqual(scheme.products.count(), 3)
        self.assertContains(self.client.get(reverse("console-schemes")), "Running")
        self.assertContains(self.client.get(reverse("console-scheme-edit", args=[scheme.pk])), 'role="tablist"')

    def test_active_scheme_needs_products_and_valid_dates(self):
        response = self.client.post(reverse("console-scheme-create"), {
            "name": "Empty", "percent": "3", "active": "on", "starts_on": "2026-11-05", "ends_on": "2026-11-01",
        })
        self.assertContains(response, "Pick at least one product")
        self.assertContains(response, "on or after the start date")
        self.assertFalse(Scheme.objects.exists())


class DuplicateProductTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="staff", is_staff=True))
        hsn = HSN.objects.create(code="3401", default_gst_rate="18")
        self.source = Product.objects.create(
            sku="DIA-100", name="Dia Soap 100g", simple_name="Dia 100g",
            company=Company.objects.create(name="HUL"), brand=Brand.objects.create(name="Dia"),
            category=Category.objects.create(name="Care"), hsn=hsn, hsn_code="3401",
            packing="Case of 48", unit="case", rate=120000, mrp=168000,
            gst_rate="18", scheme_percent="2.5", regular=True, image_url="https://example.com/dia.jpg",
        )
        self.url = reverse("console-product-quick-add")

    def test_duplicate_prefills_everything_but_sku_and_photo(self):
        page = self.client.get(self.url, {"from": self.source.pk})
        self.assertContains(page, "Duplicating")
        form = page.context["form"]
        self.assertEqual(form["name"].value(), "Dia Soap 100g")
        self.assertEqual(form["rate"].value(), 1200)
        self.assertEqual(str(form["scheme_percent"].value()), "2.50")
        self.assertIn(form["sku"].value(), (None, ""))
        self.assertNotContains(page, "example.com/dia.jpg")

    def test_saving_the_duplicate_creates_a_second_product(self):
        data = {
            "name": "Dia Soap 125g", "simple_name": "Dia 125g", "company_name": self.source.company_id,
            "brand_name": self.source.brand_id, "category_name": self.source.category_id,
            "packing": "Case of 36", "unit": "case", "rate": "1400", "mrp": "1950",
            "hsn": self.source.hsn_id, "gst_rate": "18", "scheme_percent": "2.5", "sku": "", "regular": "on", "next": "done",
        }
        self.assertRedirects(self.client.post(self.url, data), reverse("console-products"))
        copy = Product.objects.get(name="Dia Soap 125g")
        self.assertEqual((copy.sku, str(copy.scheme_percent), copy.image_url), ("DIA-SOAP-125G", "2.50", ""))
        self.assertContains(self.client.get(reverse("console-products")), f"?from={self.source.pk}")

    def test_bad_source_falls_back_to_a_blank_form(self):
        page = self.client.get(self.url, {"from": "not-a-uuid"})
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Duplicating")
