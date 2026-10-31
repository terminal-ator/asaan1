# Asaan

Retailer ordering PWA plus a distributor console.

- **PWA (repository root)** — mobile-first, installable, works offline. Shops set up their details once, browse the catalogue by category (each opens a bottom sheet of its products), review selected products with the **In cart** pill and highlighted rows, like products for a personal shortlist (the **Liked** filter), reorder in one tap (the **Order again** shortcut and the **Usual** list built from their own history), see live **order status**, share an order on WhatsApp, shuffle a random **Discover** list, and submit orders that queue locally until the API is reachable.
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

## Recommended bundles

Staff configure shop-specific starter bundles at **Console → Bundles**
(`/console/bundles`). Choose a shop type, select catalogue products and suggested
quantities, and mark the bundle active. Bundles must contain at least one product;
inactive products and empty bundles are excluded from the PWA.

Shop setup has **Shop details** and **Recommended bundles** tabs. Users can choose
multiple bundles for their shop type or skip them. Their choices feed the
**Recommended** catalogue pill, which shows each product once and supports the
usual search and filters. Users add products to their cart as they browse.
Selections and bundle data are saved on the device for offline use. Existing users
can update them through **Menu → Shop details & bundles**.

Run `cd django_api && .venv/bin/python manage.py migrate` when deploying this
change, then rebuild the PWA. Bundles are curated by staff; none are prefilled.

## Adding products

**Products → Quick add** (`/console/products/quick-add`) puts one product on one screen. **Save & add another** comes back with the company, brand, category, HSN and unit already chosen. SKU is optional (one is generated from the name, but prefer the Marg item code), and GST defaults from the HSN. The full tabbed form is still under **Full form**.

The products list shows **Active** products by default, with **Archived** and **All** tabs.

To restart the catalogue from best sellers only, archive everything and then add or restore products one by one:

```sh
python manage.py archive_products        # reports how many would be archived
python manage.py archive_products --yes  # hides them all from the shop app
```

Nothing is deleted: order history keeps its copies, and **Quick add → Bring back an archived product** restores a product with its SKU, rates and photo. When the PWA syncs, shops' carts drop archived items and reprice the rest.

## Staff phone app

**Asaan Products** (`/console/app/`, or **Products → Phone app**) is an installable app for staff to add and edit products from a phone. Open it in Chrome or Safari and choose *Install app* / *Add to Home Screen*.

- **Live / Need photo / Archived** lists with search. Tap a product to edit it; tap the camera on a row to photograph it straight away. In *Need photo*, the next product's camera is one tap away after each save.
- **+** adds a product. Company, brand, category and HSN are picked from recent chips or a searchable list (new ones can be added there). Units and GST rates are chips. The rate can be typed before or including GST, and the app remembers which you prefer.
- **Save & add similar** saves and opens a copy with everything but the SKU and photo, for pack-size variants.
- While typing a new name, matching archived products are offered for restore.

It needs the internet: its service worker only shows an offline notice, it never caches product data.

## Product photos

Adding a photo is built for a phone: open a product's **Media** tab — or use the **Photo** shortcut in the products list — and tap **Take photo** to open the camera directly, or **Choose from gallery**. The picture is resized on the device before upload (max 1400 px, JPEG), so it saves quickly on mobile data, and the products list shows a thumbnail for each item. Django serves `/media/` while `DEBUG` is on; Caddy serves it in production.

## Bulk editing

Products and Customers each have a **Bulk edit** sheet (`/console/products/bulk`, `/console/shops/bulk`) for updating many rows at once: rates and MRP in rupees, GST %, scheme %, availability, and shop contact/GST details. Each sheet is paginated at 100 rows, filtered by the same search as the list pages, saves all rows together, shows inline errors, flags unsaved changes before leaving, and supports Enter-to-move-down plus Ctrl/⌘+S to save.

## Schemes

A trade scheme takes a percentage off the pre-GST rate. Set one on a single product (**scheme %** on the product form, the bulk sheet, or the optional `scheme_percent` import column), or create a group scheme at **Console → Schemes** (`/console/schemes`) — e.g. "Dia, 3%" — and tick every SKU it covers; search a brand and use **Select shown** to add them all. Group schemes can have start and end dates.

Schemes do not stack: each product gets the single best scheme running today. The API recomputes it when an order arrives, stores it on the order line, and takes it off the line's taxable value, so order totals, slips, the items CSV and the GST report are all net of scheme. The PWA shows the scheme on each product, takes it off the cart lines and shows the saving. Orders placed before this change kept the full rate in their totals. Daily-deal percentages are still shown only, not applied.

## Endpoints

- `GET /api/catalogue` — active products for the PWA.
- `POST /api/orders` — accepts an order snapshot; repeated `clientOrderId` values are idempotent.
- `GET /api/orders/status?ids=…` — console status per `clientOrderId`, for the shop's order list.
- `GET /api/push/key`, `POST /api/push/subscribe`, `POST /api/push/unsubscribe` — web-push registration for order-status notifications.
- `GET /healthz` — liveness probe; returns 503 when the database is unreachable.
- `/admin/` — Django admin, including the Product CSV import action.
- `/console/` — staff console.

Order updates: shops tap **Get order updates** on the Orders screen to allow notifications. When staff change an order's status in the console, every subscribed device for that mobile number gets a web push. This needs `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_ADMIN_EMAIL` in the service environment; without them the button hides and the console simply skips notifying.

## Daily rhythm

- **Order days** — each shop picks weekdays on its console form (Mon–Sun chips). A cron runs the reminder each morning:
  `python manage.py send_order_day_reminders` at 08:30 pushes “Today is your order day” to the shops scheduled for today.
- **Daily deals** — Console → **Deals** assigns one product and an extra trade scheme % to each weekday. The app shows a *Today* deal chip on the product and a **Deals** pill for the weekly list; `python manage.py send_daily_deal` at 09:00 pushes the day's deal to every subscribed device.
- Both commands are safe to run by hand, and the console dashboard has **Order-day reminders** and **Today's deal** buttons that fire them immediately.
- On the server, `/etc/cron.d/asaan-notifications` runs them at 08:30 and 09:00 and appends to `/var/lib/asaan/notifications.log`.

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

1. Build the PWA on your machine and ship it: `deploy/ship.sh <user@host>` (the server never needs Node). Or build on the server with `npm run build` + `python manage.py collectstatic --noinput` if it can pull from git.
2. Copy `deploy/asaan.env.example` to `/etc/asaan/asaan.env` and fill it in.
3. Install `deploy/asaan.service` (gunicorn on `127.0.0.1:8123`, set by `GUNICORN_PORT`) and `deploy/Caddyfile` (serves the PWA, `/static`, `/media` and proxies the API and console, with automatic TLS). On a box where 80/443 are already in use, use `deploy/nginx.conf` instead — see [`deploy/README.md`](deploy/README.md).
4. First run: `SKIP_DEPLOY=1 deploy/ship.sh <user@host>` then `ssh <user@host> "sudo SITE_HOST=asaan.in EMAIL=… SKIP_FRONTEND=1 sh /opt/asaan/deploy/bootstrap.sh"`. Updates afterwards are just `deploy/ship.sh <user@host>`.
5. Back up nightly with `deploy/backup-asaan.sh`; point an uptime check at `/healthz`.
