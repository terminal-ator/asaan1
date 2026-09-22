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

## Billing phase

Bills are raised by hand in Marg ERP. The console prepares printable order slips and line-item CSV exports; it does not assign invoice numbers or post dispatch stock. `invoice_detail`, `invoice_json`, `invoice_excel`, and `einvoice_upload` are kept for the future auto-billing phase but are not linked from the console.

The Product admin includes an **Import CSV** action. Existing SKUs are updated and new SKUs are created. The Order admin supports `Received`, `Processing`, `Completed`, and `Cancelled` states, with filters and inline order items.

## Tests

```sh
python manage.py test
```

`catalogue/tests.py` covers order creation, idempotency, and GSTIN handling; `console/tests.py` covers slips, CSV exports, loading creation, and the paused invoice conversion.
