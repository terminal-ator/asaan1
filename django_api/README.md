# Django backend

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 8081
```

Admin: `/admin/` · API: `/api/catalogue`, `/api/orders`.

The Product admin includes an **Import CSV** action. Existing SKUs are updated and new SKUs are created. The Order admin supports `Received`, `Processing`, `Completed`, and `Cancelled` states, with filters and inline order items.
