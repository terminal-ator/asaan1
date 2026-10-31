# Django backend

Django serves the catalogue and order API and the staff console.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 8081
```

Admin: `/admin/` · Console: `/console/` · API: `/api/catalogue`, `/api/orders`.

The staff **Product workspace** at `/console/products/images` opens from Products.
Choose **Edit product** (or click a product name) to edit full/display names, SKU,
company, brand, category, packing, unit and visibility in the Details tab; sale
rate, MRP, GST, scheme and HSN are in Pricing & tax. Prices are entered in rupees.
Product details and images save together; invalid fields or a duplicate SKU keep
the draft open, and **Save & next** continues in the same editing tab.
It searches product names, SKUs, companies, brands, categories and packing, with
filters for company, brand, category, unit, visibility, regular products and image
status. Upload from a file, camera, drag-and-drop or clipboard; crop, reposition,
rotate, flip and adjust brightness before saving. **Save & next** (Ctrl/Cmd+Enter)
continues through the current view without reloading the page. Each product keeps
one image: an uploaded photo or a direct HTTP(S) URL. Uploads are limited to 10 MB
and 40 megapixels, resized to 1600 px, and stripped of EXIF metadata. Editing a
remote image requires its host to permit CORS access; otherwise upload the file.
Image endpoints require a staff login and reject stale saves if the product has
changed while its editor was open. No database migration or frontend build is
needed for this workspace; deploy Django static assets with `collectstatic`.

## Billing phase

Bills are raised by hand in Marg ERP. The console prepares printable order slips and line-item CSV exports; it does not assign invoice numbers or post dispatch stock. `invoice_detail`, `invoice_json`, `invoice_excel`, and `einvoice_upload` are kept for the future auto-billing phase but are not linked from the console.

The Product admin includes an **Import CSV** action. Existing SKUs are updated and new SKUs are created. It accepts the same columns as the console importer, including `gst_rate`, `scheme_percent` and `hsn_code`. The Order admin supports `Received`, `Processing`, `Completed`, and `Cancelled` states, with filters and inline order items.

## Tests

```sh
python manage.py test
```

`catalogue/tests.py` covers order creation, idempotency, and GSTIN handling; `console/tests.py` covers slips, CSV exports, loading creation, and the paused invoice conversion.
`console/test_product_media.py` covers image-workspace access, combined filters,
pagination, upload validation and resizing, metadata removal, and stale saves.

## Recommended bundles

`/console/bundles` lets staff create and edit bundles in Details and Products &
quantities tabs. Each bundle targets one shop type. Active bundles with active
products are included as `bundles` alongside `shopTypes` in `GET /api/catalogue`.
Product rates remain in the catalogue, so previews use current GST-inclusive
prices. Customers select bundles during setup; their products appear in the
Recommended pill without changing the cart. The order snapshot retains selected
bundle IDs and shop type; the customer record retains shop type.

Migration `0021` adds bundle models and shop type. Apply it with `python manage.py
migrate` before deploying the API. Configure bundles using real catalogue products;
no starter bundle data is created automatically.

Bundle API and console checks: `python manage.py test catalogue.test_bundles
console.test_bundles`. Frontend recommendation checks (Node 22+):
`node --experimental-strip-types --test tests/bundles.test.mjs` from the repository
root.
