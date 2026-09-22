# Ordex

Retailer ordering PWA plus a distributor console.

- **PWA (repository root)** — mobile-first, installable, works offline. Shops set up their details once, browse the catalogue, and submit orders that queue locally until the API is reachable.
- **API and console (`django_api/`)** — Django serves the catalogue and receives orders, and provides the staff console for reviewing orders, printing slips, grouping dispatch loadings, managing products and shops, purchases, returns, inventory, and GST reports.

## Current billing workflow

Bills are raised by hand in Marg ERP. Ordex captures the order and prepares it for billing:

1. A shop submits an order in the PWA. Totals are tentative; prices are recomputed server-side from the catalogue.
2. Staff review it in the console (`/console/`), fix the customer GSTIN, billing address, or place of supply if needed, and print an **order slip** (`/console/orders/<id>/slip`) with prices for billing.
3. The billing desk keys the bill into Marg. Export a day's lines as CSV from the dashboard or the sales register (`Export items CSV`) if that is easier than reading slips.
4. The **Dispatch summary** covers the day's unassigned bills: it lists each bill and a consolidated **pick list** grouped by company and brand, with quantities and how many bills need each SKU.
5. Orders going out together are grouped into a **loading**. The loading page prints the loading sheet, billing slips, or a set of dense **packing slips** — one price-free slip per bill with a tick box per line for the packing table.

In-app invoice numbering, the stock ledger during dispatch, and e-invoice upload are **paused** until auto-billing from Ordex replaces the manual step. The related models and views are kept for that future work but are not linked from the console.

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

## Bulk editing

Products and Customers each have a **Bulk edit** sheet (`/console/products/bulk`, `/console/shops/bulk`) for updating many rows at once: rates and MRP in rupees, GST %, availability, and shop contact/GST details. Each sheet is paginated at 100 rows, filtered by the same search as the list pages, saves all rows together, shows inline errors, flags unsaved changes before leaving, and supports Enter-to-move-down plus Ctrl/⌘+S to save.

## Endpoints

- `GET /api/catalogue` — active products for the PWA.
- `POST /api/orders` — accepts an order snapshot; repeated `clientOrderId` values are idempotent.
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

1. Build the PWA: `npm run build` (outputs `dist/`).
2. Collect Django static files: `python manage.py collectstatic --noinput`.
3. Copy `deploy/ordex.env.example` to `/etc/ordex/ordex.env` and fill it in.
4. Install `deploy/ordex.service` (gunicorn on `127.0.0.1:8081`) and `deploy/nginx.conf` (serves `dist/` and proxies `/api`, `/console`, `/admin`, `/static`, `/media`).
5. Back up the database and uploaded images with `deploy/backup-ordex.sh`.
