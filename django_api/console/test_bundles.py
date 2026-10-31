from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogue.models import Brand, Category, Company, Product, ProductBundle, ProductBundleItem


class BundleConsoleTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username="bundles", is_staff=True)
        self.product = Product.objects.create(
            sku="BUNDLE-1", name="Soap", company=Company.objects.create(name="Company"),
            brand=Brand.objects.create(name="Brand"), category=Category.objects.create(name="Care"),
            unit="case", packing="Case", rate=10000, mrp=15000,
        )
        self.url = reverse("console-bundle-create")

    def payload(self, **changes):
        return {
            "name": "Starter", "shop_type": "kirana", "active": "on", "description": "Everyday essentials",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-0-product": str(self.product.pk), "items-0-quantity": "2", **changes,
        }

    def test_bundles_require_staff_access(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        user = get_user_model().objects.create_user(username="customer")
        self.client.force_login(user)
        self.assertEqual(self.client.post(self.url, self.payload()).status_code, 302)
        self.assertFalse(ProductBundle.objects.exists())

    def test_create_and_edit_bundle_and_render_tabs(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, self.payload())
        self.assertRedirects(response, reverse("console-bundles"))
        bundle = ProductBundle.objects.get()
        self.assertEqual(bundle.items.get().quantity, 2)
        url = reverse("console-bundle-edit", args=[bundle.pk])
        self.assertContains(self.client.get(url), 'role="tablist"')
        data = self.payload(**{
            "name": "Updated", "items-INITIAL_FORMS": "1",
            "items-0-id": str(bundle.items.get().pk), "items-0-quantity": "4",
        })
        self.assertRedirects(self.client.post(url, data), reverse("console-bundles"))
        bundle.refresh_from_db()
        self.assertEqual(bundle.name, "Updated")
        self.assertEqual(bundle.items.get().quantity, 4)

    def test_invalid_quantities_do_not_create_partial_bundle(self):
        self.client.force_login(self.staff)
        for quantity in ("0", "-1", "100001", "1.5"):
            response = self.client.post(self.url, self.payload(**{"items-0-quantity": quantity}))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["formset"].errors)
        self.assertFalse(ProductBundle.objects.exists())

    def test_duplicate_products_are_rejected(self):
        self.client.force_login(self.staff)
        data = self.payload(**{
            "items-TOTAL_FORMS": "2", "items-1-product": str(self.product.pk), "items-1-quantity": "3",
        })
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["formset"].non_form_errors())
        self.assertFalse(ProductBundle.objects.exists())

    def test_empty_bundle_cannot_be_saved(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, self.payload(**{"items-TOTAL_FORMS": "0"}))
        self.assertContains(response, "Add at least one product")
        self.assertFalse(ProductBundle.objects.exists())

    def test_inactive_products_cannot_be_added(self):
        self.client.force_login(self.staff)
        self.product.active = False
        self.product.save()
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["formset"].errors)
        self.assertFalse(ProductBundle.objects.exists())

    def test_existing_inactive_product_can_be_retained_in_hidden_bundle(self):
        self.client.force_login(self.staff)
        bundle = ProductBundle.objects.create(name="Hidden", shop_type="kirana", active=False)
        item = ProductBundleItem.objects.create(bundle=bundle, product=self.product)
        self.product.active = False
        self.product.save()
        data = self.payload(**{
            "active": "", "items-INITIAL_FORMS": "1", "items-0-id": str(item.pk),
        })
        response = self.client.post(reverse("console-bundle-edit", args=[bundle.pk]), data)
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_deleting_last_item_keeps_existing_bundle_unchanged(self):
        self.client.force_login(self.staff)
        bundle = ProductBundle.objects.create(name="Original", shop_type="kirana")
        item = ProductBundleItem.objects.create(bundle=bundle, product=self.product)
        data = self.payload(**{
            "items-INITIAL_FORMS": "1", "items-0-id": str(item.pk), "items-0-DELETE": "on",
        })
        response = self.client.post(reverse("console-bundle-edit", args=[bundle.pk]), data)
        self.assertContains(response, "Add at least one product")
        bundle.refresh_from_db()
        self.assertEqual(bundle.name, "Original")
        self.assertTrue(bundle.items.exists())
