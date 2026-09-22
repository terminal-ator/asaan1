# Asaan

Retailer ordering PWA plus a distributor console.

- **PWA (repository root)** — mobile-first, installable, works offline. Shops set up their details once, browse the catalogue, and submit orders that queue locally until the API is reachable.
- **API and console (`django_api/`)** — Django serves the catalogue and receives orders, and provides the staff console for reviewing orders, printing slips, grouping dispatch loadings, managing products and shops, purchases, returns, inventory, and GST reports.

## Current billing workflow

Bills are raised by hand in Marg ERP. Asaan captures the order and prepares it for billing:

1. A shop submits an order in the PWA. Totals are tentative; prices are recomputed server-side from the catalogue.
2. Staff review it in the console (`/console/`), fix the customer GSTIN, billing address, or place of supply if needed, and print an **order slip** (`/console/orders/<id>/slip`) with prices for billing.
3. The billing desk keys the bill into Marg. Export a day's lines as CSV from the dashboard or the sales register (`Export items CSV`) if that is easier than reading slips.
4. The **Dispatch summary** covers the day's unassigned bills: it lists each bill and a consolidated **pick list** grouped by company and brand, with quantities and how many bills need each SKU.
5. Orders going out together are grouped into a **loading**. The loading page prints the loading sheet, billing slips, or a set of dense **packing slips** — one price-free slip per bill with a tick box per line for the packing table.

In-app invoice numbering, the stock ledger during dispatch, and e-invoice upload are **paused** until auto-billing from Asaan replaces the manual step. The related models and views are kept for that future work but are not linked from the console.

## Run locally

Backend:

```sh
cd django_api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 8081
```

Frontend:

```sh
npm install
npm run dev
```

Vite serves the PWA on `http://localhost:5173` and proxies `/api` and `/media` to Django on `127.0.0.1:8081`. Open the console at `http://localhost:8081/console/` after logging in at `/admin/login/`.

Set `VITE_API_URL` only when the PWA and API are on different origins.

## Product photos

Adding a photo is built for a phone: open a product's **Media** tab — or use the **Photo** shortcut in the products list — and tap **Take photo** to open the camera directly, or **Choose from gallery**. The picture is resized on the device before upload (max 1400 px, JPEG), so it saves quickly on mobile data, and the products list shows a thumbnail for each item. Django serves `/media/` while `DEBUG` is on; nginx serves it in production.

## Bulk editing

Products and Customers each have a **Bulk edit** sheet (`/console/products/bulk`, `/console/shops/bulk`) for updating many rows at once: rates and MRP in rupees, GST %, scheme %, availability, and shop contact/GST details. Each sheet is paginated at 100 rows, filtered by the same search as the list pages, saves all rows together, shows inline errors, flags unsaved changes before leaving, and supports Enter-to-move-down plus Ctrl/⌘+S to save.

A product's **scheme %** is a trade scheme shown to shops as a badge in the PWA and printed on order slips, packing slips and the items CSV; the Marg bill remains the final word on whether it applies. Set it on the product form, in the bulk sheet, or with the optional `scheme_percent` import column.

## Endpoints

- `GET /api/catalogue` — active products for the PWA.
- `POST /api/orders` — accepts an order snapshot; repeated `clientOrderId` values are idempotent.
- `GET /healthz` — liveness probe; returns 503 when the database is unreachable.
- `/admin/` — Django admin, including the Product CSV import action.
- `/console/` — staff console.

Prices are integer paise everywhere. `POST /api/orders` body:

```json
{
  "clientOrderId": "018f7fa3-0b4f-7b54-a2d6-07d7cf2bd261",
  "shop": {"storeName": "Gupta General Store", "customerName": "Amit Gupta", "mobile": "9876543210", "gstin": "27ABCDE1234F1Z5", "address": "Main Market"},
  "items": [{"productId": "b2b0c1e0-...", "sku": "SURF-1KG-12", "unit": "case", "quantity": 2}],
  "notes": "Morning delivery preferred"
}
```

The PWA sends the catalogue product's UUID as `productId`. The API validates the unit, recomputes line totals and the order total from the current catalogue rates, and fills the place of supply from the GSTIN prefix.

## Deploy

The full strategy, first-time server setup, backup/restore drill and troubleshooting live in [`deploy/README.md`](deploy/README.md). The short version:

1. Build the PWA and Django static files: `npm run build`, `python manage.py collectstatic --noinput`.
2. Copy `deploy/asaan.env.example` to `/etc/asaan/asaan.env` and fill it in.
3. Install `deploy/asaan.service` (gunicorn on `127.0.0.1:8123`, set by `GUNICORN_PORT`) and `deploy/nginx.conf` (serves `dist/`, `/static/`, `/media/` and proxies the API and console) — see [`deploy/README.md`](deploy/README.md).
4. Deploy and roll back with `deploy/deploy.sh`; back up nightly with `deploy/backup-asaan.sh`. SQLite is the default; set `POSTGRES_DB` and friends in the env file to use PostgreSQL instead.
5. Point an uptime check at `/healthz`.
