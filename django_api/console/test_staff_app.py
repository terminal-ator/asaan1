from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal
from io import BytesIO
from PIL import Image

from catalogue.models import Brand, Category, Company, HSN, Product


def photo():
    buffer = BytesIO()
    Image.new("RGB", (40, 30), "orange").save(buffer, format="JPEG")
    return SimpleUploadedFile("shelf.jpg", buffer.getvalue(), content_type="image/jpeg")


class StaffAppTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.company = Company.objects.create(name="HUL")
        self.brand = Brand.objects.create(name="Dia")
        self.category = Category.objects.create(name="Soaps")
        self.hsn = HSN.objects.create(code="3401", default_gst_rate="18")

    def payload(self, **changes):
        return {
            "name": "Dia Soap 100g", "company_name": self.company.pk, "brand_name": self.brand.pk,
            "category_name": self.category.pk, "packing": "Case of 48", "unit": "case",
            "rate": "1000", "mrp": "1500", "hsn": self.hsn.pk, "gst_rate": "", "sku": "", **changes,
        }

    def test_app_shell_is_staff_only_and_installable(self):
        self.assertEqual(self.client.get(reverse("console-staff-app")).status_code, 302)
        self.client.force_login(self.staff)
        page = self.client.get(reverse("console-staff-app"))
        self.assertContains(page, 'rel="manifest"')
        manifest = self.client.get(reverse("console-staff-manifest")).json()
        self.assertEqual((manifest["scope"], manifest["start_url"], manifest["display"]), ("/console/app/", "/console/app/", "standalone"))
        worker = self.client.get(reverse("console-staff-sw"))
        self.assertEqual(worker["Service-Worker-Allowed"], "/console/app/")

    def test_create_with_photo_in_one_request(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("console-staff-create"), {**self.payload(), "regular": "on", "image": photo()})
        self.assertEqual(response.status_code, 201)
        product = Product.objects.get()
        self.assertTrue(product.image.name.startswith("products/"))
        self.assertTrue(product.regular)
        self.assertEqual(str(product.gst_rate), "18.00")
        self.assertEqual(response.json()["product"]["attributes"]["sku"], "DIA-SOAP-100G")

    def test_errors_and_archived_sku_come_back_as_json(self):
        self.client.force_login(self.staff)
        invalid = self.client.post(reverse("console-staff-create"), self.payload(name="", rate="abc"))
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("name", invalid.json()["errors"])
        self.client.post(reverse("console-staff-create"), self.payload(sku="M-1"))
        Product.objects.update(active=False)
        archived = self.client.post(reverse("console-staff-create"), self.payload(sku="M-1"))
        self.assertEqual(archived.status_code, 409)
        self.assertEqual(archived.json()["archived"]["sku"], "M-1")

    def test_non_staff_get_json_errors(self):
        self.assertEqual(self.client.post(reverse("console-staff-create"), self.payload()).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user(username="shop"))
        self.assertEqual(self.client.post(reverse("console-staff-create"), self.payload()).status_code, 403)

    def test_create_keeps_a_copied_scheme_percent(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("console-staff-create"), self.payload(scheme_percent="3"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(str(Product.objects.get().scheme_percent), "3.00")
        blank = self.client.post(reverse("console-staff-create"), self.payload(name="Dia Soap 125g", scheme_percent=""))
        self.assertEqual(blank.status_code, 201)

    def test_creating_a_master_reuses_one_with_the_same_name_in_any_case(self):
        self.client.force_login(self.staff)
        url = reverse("console-quick-lookup")
        existing = self.client.post(url, {"kind": "company", "name": "hul"}).json()
        self.assertEqual((existing["id"], existing["label"]), (self.company.pk, "HUL"))
        added = self.client.post(url, {"kind": "brand", "name": "Pears"}).json()
        self.assertEqual(Brand.objects.get(pk=added["id"]).name, "Pears")
        hsn = self.client.post(url, {"kind": "hsn", "name": "3401", "default_gst_rate": "5"}).json()
        self.assertEqual((hsn["id"], hsn["gstRate"]), (self.hsn.pk, "18.00"))
        self.assertEqual(Company.objects.count(), 1)

    def test_rename_masters_and_guard_against_duplicates(self):
        self.client.force_login(self.staff)
        url = lambda kind, pk: reverse("console-staff-master", args=[kind, pk])
        renamed = self.client.post(url("brand", self.brand.pk), {"name": "Dia Beauty"})
        self.assertEqual(renamed.json()["name"], "Dia Beauty")
        Brand.objects.create(name="Pears")
        clash = self.client.post(url("brand", self.brand.pk), {"name": "pears"})
        self.assertEqual(clash.status_code, 400)
        self.assertIn("already exists", clash.json()["error"])
        self.assertEqual(self.client.post(url("category", self.category.pk), {"name": "  "}).status_code, 400)
        self.assertEqual(self.client.post(url("company", 9999), {"name": "X"}).status_code, 404)
        self.assertEqual(self.client.post(url("supplier", 1), {"name": "X"}).status_code, 400)

    def test_hsn_edit_updates_product_codes_but_not_their_gst(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("console-staff-create"), self.payload())
        response = self.client.post(reverse("console-staff-master", args=["hsn", self.hsn.pk]), {"name": "34011190", "default_gst_rate": "5"})
        self.assertEqual(response.json()["code"], "34011190")
        product = Product.objects.get()
        self.assertEqual((product.hsn_code, str(product.gst_rate)), ("34011190", "18.00"))
        bad = self.client.post(reverse("console-staff-master", args=["hsn", self.hsn.pk]), {"name": "3401", "default_gst_rate": "120"})
        self.assertEqual(bad.status_code, 400)

    def test_master_edits_need_staff(self):
        url = reverse("console-staff-master", args=["brand", self.brand.pk])
        self.assertEqual(self.client.post(url, {"name": "X"}).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user(username="shop"))
        self.assertEqual(self.client.post(url, {"name": "X"}).status_code, 403)
        self.assertEqual(Brand.objects.get(pk=self.brand.pk).name, "Dia")

    def test_markup_is_stored_and_offered_when_duplicating(self):
        self.client.force_login(self.staff)
        # MRP 100 at 15% markup: shops pay 86.96 incl. GST, 73.69 before 18% GST.
        response = self.client.post(reverse("console-staff-create"), self.payload(mrp="100", rate="73.69", markup_percent="15"))
        self.assertEqual(response.status_code, 201)
        product = Product.objects.get()
        self.assertEqual((str(product.markup_percent), product.rate), ("15.00", 7369))
        self.assertEqual(response.json()["product"]["attributes"]["markup_percent"], "15.00")
        page = self.client.get(reverse("console-product-quick-add"), {"from": product.pk})
        self.assertEqual(str(page.context["form"]["markup_percent"].value()), "15.00")

    def test_products_without_a_stored_markup_imply_one(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("console-staff-create"), self.payload(mrp="1180", rate="800"))
        product = Product.objects.get()
        self.assertIsNone(product.markup_percent)
        # 800 + 18% GST = 944; 1180 / 944 = +25%.
        self.assertEqual(product.implied_markup_percent, Decimal("25.00"))
        self.assertEqual(self.client.post(reverse("console-staff-create"), self.payload(name="Bad", markup_percent="-5")).status_code, 400)
