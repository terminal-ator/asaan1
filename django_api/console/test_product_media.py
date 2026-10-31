import io
import json
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from catalogue.models import Brand, Category, Company, HSN, Product
from console.product_media import ImageUpdateForm


def photo(size=(80, 40), mode="RGB", exif=None):
    buffer = io.BytesIO()
    image = Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else "white")
    image.save(buffer, format="PNG" if mode == "RGBA" else "JPEG", **({"exif": exif} if exif else {}))
    return SimpleUploadedFile("photo.png" if mode == "RGBA" else "photo.jpg", buffer.getvalue(), content_type="image/png" if mode == "RGBA" else "image/jpeg")


class ProductImageWorkspaceTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        settings = override_settings(MEDIA_ROOT=media)
        settings.enable()
        self.addCleanup(settings.disable)
        self.staff = get_user_model().objects.create_user("media-staff", is_staff=True)
        self.client.force_login(self.staff)
        company = Company.objects.create(name="Acme")
        brand = Brand.objects.create(name="Fresh")
        category = Category.objects.create(name="Snacks")
        self.product = Product.objects.create(
            sku="CRISP-1", name="Original crisps", simple_name="Chips",
            company=company, brand=brand, category=category, packing="12 packs",
            unit="case", rate=10000, mrp=12000, regular=True,
        )
        self.linked = Product.objects.create(
            sku="DRINK-2", name="Orange juice", company=Company.objects.create(name="Other Co"),
            brand=Brand.objects.create(name="Juicy"), category=Category.objects.create(name="Drinks"),
            packing="Bottle", unit="piece", rate=2000, mrp=2500, active=False,
            image_url="https://example.com/juice.jpg",
        )
        self.list_url = reverse("console-product-images-data")
        self.update_url = reverse("console-product-image-update", args=[self.product.id])
        self.details_url = reverse("console-product-quick-edit", args=[self.product.id])

    def update(self, **values):
        return self.client.post(self.update_url, {"version": self.product.updated_at.isoformat(), **values})

    def ids(self, **filters):
        response = self.client.get(self.list_url, filters)
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.json()["products"]}

    def test_workspace_and_product_list_link(self):
        self.assertContains(self.client.get(reverse("console-product-images")), 'id="iw-dialog"')
        self.assertContains(self.client.get(reverse("console-products")), reverse("console-product-images"))

    def test_staff_login_required_for_every_endpoint(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("console-product-images")).status_code, 302)
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.assertEqual(self.client.post(self.update_url).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user("customer"))
        self.assertEqual(self.client.get(reverse("console-product-images")).status_code, 403)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.post(self.update_url).status_code, 403)

    def test_updates_require_post_and_csrf(self):
        self.assertEqual(self.client.get(self.update_url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        response = csrf_client.post(self.update_url, {"action": "remove", "version": self.product.updated_at.isoformat()})
        self.assertEqual(response.status_code, 403)

    def test_search_matches_multiple_words_across_fields(self):
        for query in ["chips", "CRISP", "Acme Fresh", "12 packs", "Snacks"]:
            with self.subTest(query=query):
                self.assertEqual(self.ids(q=query), {str(self.product.id)})
        self.assertEqual(self.ids(q="Acme orange"), set())

    def test_filters_combine_and_include_inactive_products(self):
        self.assertEqual(self.ids(), {str(self.product.id), str(self.linked.id)})
        self.assertEqual(self.ids(company="Acme", brand="Fresh", category="Snacks", unit="case", active="yes", regular="yes", image="missing"), {str(self.product.id)})
        self.assertEqual(self.ids(active="no", regular="no", image="linked"), {str(self.linked.id)})
        self.assertEqual(self.ids(image="present"), {str(self.linked.id)})
        self.assertEqual(self.ids(image="uploaded"), set())

    def test_brands_follow_company_but_facets_keep_full_choices(self):
        data = self.client.get(self.list_url, {"company": "Acme", "q": "absent"}).json()
        self.assertEqual(data["facets"]["brand"], ["Fresh"])
        self.assertEqual(data["facets"]["company"], ["Acme", "Other Co"])
        self.assertEqual(data["facets"]["category"], ["Drinks", "Snacks"])
        self.assertEqual(data["facets"]["unit"], ["case", "piece"])

    def test_pagination_has_no_silent_product_limit(self):
        Product.objects.bulk_create([
            Product(sku=f"BULK-{index}", name=f"Bulk {index:03}", company=self.product.company,
                    brand=self.product.brand, category=self.product.category,
                    packing="Case", rate=100, mrp=200)
            for index in range(52)
        ])
        first = self.client.get(self.list_url, {"sort": "name"}).json()
        second = self.client.get(self.list_url, {"sort": "name", "page": 2}).json()
        self.assertEqual(first["total"], 54)
        self.assertEqual(len(first["products"]), 48)
        self.assertEqual(len(second["products"]), 6)
        self.assertFalse({p["id"] for p in first["products"]} & {p["id"] for p in second["products"]})
        self.assertEqual(self.client.get(self.list_url, {"page": "bad", "sort": "bad"}).status_code, 200)

    def test_upload_resizes_image_and_preserves_product_fields(self):
        self.product.image_url = "https://example.com/old.jpg"
        self.product.save()
        response = self.update(action="upload", image=photo(size=(2400, 1200)))
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.image_url, "")
        self.assertEqual((self.product.name, self.product.rate, self.product.regular), ("Original crisps", 10000, True))
        with Image.open(self.product.image.path) as image:
            self.assertEqual(image.size, (1600, 800))
        self.assertEqual(response.json()["product"]["source"], "uploaded")
        self.assertEqual(self.ids(image="missing"), set())
        self.assertEqual(self.ids(image="uploaded"), {str(self.product.id)})

    def test_upload_applies_exif_orientation_and_removes_metadata(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "Private photo metadata"
        self.assertEqual(self.update(action="upload", image=photo(exif=exif)).status_code, 200)
        self.product.refresh_from_db()
        with Image.open(self.product.image.path) as image:
            self.assertEqual(image.size, (40, 80))
            self.assertEqual(len(image.getexif()), 0)

    def test_png_upload_retains_transparency(self):
        self.assertEqual(self.update(action="upload", image=photo(mode="RGBA")).status_code, 200)
        self.product.refresh_from_db()
        with Image.open(self.product.image.path) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 128)

    def test_url_replaces_uploaded_photo_and_remove_clears_both(self):
        self.product.image.save("existing.jpg", photo(), save=True)
        response = self.update(action="url", image_url="https://example.com/new.jpg")
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)
        self.assertEqual(self.product.image_url, "https://example.com/new.jpg")
        self.assertEqual(self.update(action="remove").status_code, 200)
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)
        self.assertEqual(self.product.image_url, "")

    def test_invalid_updates_do_not_modify_product(self):
        version = self.product.updated_at
        for values in [
            {"action": "upload"},
            {"action": "upload", "image": SimpleUploadedFile("bad.jpg", b"not an image", content_type="image/jpeg")},
            {"action": "url", "image_url": "javascript:alert(1)"},
            {"action": "url", "image_url": "ftp://example.com/photo.jpg"},
            {"action": "unknown"},
        ]:
            with self.subTest(values=values):
                self.assertEqual(self.update(**values).status_code, 400)
                self.product.refresh_from_db()
                self.assertEqual(self.product.updated_at, version)
                self.assertFalse(self.product.image)

    def test_oversized_upload_rejected_before_decode(self):
        upload = SimpleUploadedFile("big.jpg", b"fake", content_type="image/jpeg")
        upload.size = 10 * 1024 * 1024 + 1
        form = ImageUpdateForm({"action": "upload", "version": "v1"}, {"image": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("10 MB", str(form.errors["image"]))

    def test_stale_save_does_not_overwrite_current_image(self):
        old_version = self.product.updated_at.isoformat()
        self.product.image_url = "https://example.com/current.jpg"
        self.product.save()
        response = self.client.post(self.update_url, {"action": "remove", "version": old_version})
        self.assertEqual(response.status_code, 409)
        self.product.refresh_from_db()
        self.assertEqual(self.product.image_url, "https://example.com/current.jpg")

    def edit_details(self, attributes, **values):
        return self.client.post(self.details_url, {
            "version": self.product.updated_at.isoformat(),
            "attributes": json.dumps(attributes), **values,
        })

    def test_partial_name_edit_preserves_image_prices_and_flags(self):
        self.product.image.save("existing.jpg", photo(), save=True)
        filename = self.product.image.name
        response = self.edit_details({"name": "Renamed crisps", "simple_name": "Short name"})
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Renamed crisps")
        self.assertEqual(self.product.simple_name, "Short name")
        self.assertEqual(self.product.image.name, filename)
        self.assertEqual((self.product.rate, self.product.mrp, self.product.active, self.product.regular), (10000, 12000, True, True))
        self.assertEqual(self.ids(q="Short name"), {str(self.product.id)})

    def test_all_attributes_can_be_saved_together_with_a_photo(self):
        hsn = HSN.objects.create(code="1234", default_gst_rate=12)
        response = self.edit_details({
            "sku": "EDITED-1", "name": "Updated product", "simple_name": "",
            "company_name": str(self.linked.company_id), "brand_name": str(self.linked.brand_id),
            "category_name": str(self.linked.category_id), "packing": "24 bottles", "unit": "piece",
            "rate": "123.45", "mrp": "150.99", "gst_rate": "12.50", "scheme_percent": "7.50",
            "hsn": str(hsn.id), "hsn_code": "ignored", "active": False, "regular": False,
        }, action="upload", image=photo())
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual((self.product.rate, self.product.mrp), (12345, 15099))
        self.assertEqual(str(self.product.gst_rate), "12.50")
        self.assertEqual(str(self.product.scheme_percent), "7.50")
        self.assertEqual(self.product.hsn_code, "1234")
        self.assertEqual(self.product.hsn_id, hsn.id)
        self.assertEqual((self.product.company_id, self.product.brand_id, self.product.category_id), (self.linked.company_id, self.linked.brand_id, self.linked.category_id))
        self.assertEqual((self.product.unit, self.product.packing, self.product.sku), ("piece", "24 bottles", "EDITED-1"))
        self.assertFalse(self.product.active)
        self.assertFalse(self.product.regular)
        self.assertTrue(self.product.image)
        self.assertEqual(response.json()["product"]["company"], self.linked.company.name)

    def test_duplicate_sku_and_invalid_values_return_field_errors_without_saving(self):
        for attributes, field in [
            ({"sku": self.linked.sku}, "sku"), ({"name": ""}, "name"),
            ({"rate": "-1"}, "rate"), ({"rate": "12.345"}, "rate"),
            ({"mrp": "-1"}, "mrp"), ({"gst_rate": "101"}, "gst_rate"),
            ({"scheme_percent": "101"}, "scheme_percent"),
            ({"company_name": "99999"}, "company_name"),
        ]:
            with self.subTest(attributes=attributes):
                version = self.product.updated_at
                response = self.edit_details(attributes, action="upload", image=photo())
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
                self.product.refresh_from_db()
                self.assertEqual(self.product.updated_at, version)
                self.assertFalse(self.product.image)

    def test_invalid_image_does_not_save_name_changes(self):
        response = self.edit_details({"name": "Unsaved"}, action="upload", image=SimpleUploadedFile("bad.jpg", b"bad"))
        self.assertEqual(response.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Original crisps")

    def test_stale_details_save_preserves_current_product(self):
        old_version = self.product.updated_at.isoformat()
        self.assertEqual(self.update(action="url", image_url="https://example.com/new.jpg").status_code, 200)
        response = self.client.post(self.details_url, {
            "version": old_version, "attributes": json.dumps({"name": "Stale rename"}),
        })
        self.assertEqual(response.status_code, 409)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Original crisps")
        self.assertEqual(self.product.image_url, "https://example.com/new.jpg")

    def test_hsn_can_be_cleared_or_set_to_a_manual_code(self):
        hsn = HSN.objects.create(code="1234", default_gst_rate=12)
        self.product.hsn = hsn
        self.product.hsn_code = hsn.code
        self.product.save()
        self.assertEqual(self.edit_details({"hsn": "", "hsn_code": "5678"}).status_code, 200)
        self.product.refresh_from_db()
        self.assertIsNone(self.product.hsn)
        self.assertEqual(self.product.hsn_code, "5678")

    def test_editor_lookup_choices_include_unused_master_records(self):
        unused = Company.objects.create(name="Unused company")
        hsn = HSN.objects.create(code="1111", default_gst_rate=18)
        data = self.client.get(self.list_url).json()
        self.assertIn({"id": unused.id, "name": unused.name}, data["lookups"]["company_name"])
        self.assertEqual(data["lookups"]["hsn"][0]["id"], hsn.id)
        attributes = next(row["attributes"] for row in data["products"] if row["id"] == str(self.product.id))
        self.assertEqual(attributes["rate"], "100")
        self.assertEqual(attributes["company_name"], str(self.product.company_id))

    def test_malformed_or_unsupported_attributes_are_rejected(self):
        for value in ["bad json", "[]", '{"image_url":"https://example.com/stealth.jpg"}', '{"updated_at":"now"}']:
            with self.subTest(value=value):
                response = self.client.post(self.details_url, {"version": self.product.updated_at.isoformat(), "attributes": value})
                self.assertEqual(response.status_code, 400)

    def test_quick_edit_requires_staff_post_and_csrf(self):
        self.assertEqual(self.client.get(self.details_url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(self.details_url, {"attributes": '{"name":"Rename"}'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.details_url).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user("nonstaff-editor"))
        self.assertEqual(self.client.post(self.details_url).status_code, 403)
