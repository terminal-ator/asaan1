from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
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
