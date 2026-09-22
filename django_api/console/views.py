import csv
import io
import uuid
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.forms import modelformset_factory
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogue.models import (
    Brand,
    Category,
    Company,
    DistributorProfile,
    Loading,
    Order,
    OrderItem,
    Product,
    Purchase,
    PurchaseItem,
    PurchaseReturn,
    SalesReturn,
    StockLedger,
    Shop,
    HSN,
)

from .forms import ProductBulkForm, ProductForm, ShopBulkForm
from .order_forms import OrderBillingForm
from .shop_forms import ShopForm
from .profile_forms import DistributorProfileForm
from .purchase_forms import PurchaseForm, PurchaseItemFormSet
from .return_forms import SalesReturnForm, PurchaseReturnForm, SalesReturnItemFormSet, PurchaseReturnItemFormSet
from .master_forms import QuickProductForm, QuickSupplierForm


@login_required
def dashboard(request):
    orders = Order.objects.prefetch_related("items").all()[:50]
    statuses = ["received", "processing", "completed", "cancelled"]
    counts = {
        status: Order.objects.filter(status=status).count()
        for status in statuses
    }
    return render(
        request,
        "console/dashboard.html",
        {"orders": orders, "counts": counts},
    )


@login_required
def sales_register(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    start = request.GET.get("from", "")
    end = request.GET.get("to", "")
    records = Order.objects.prefetch_related("items").order_by("-created_at")
    if query:
        records = records.filter(Q(order_number__icontains=query) | Q(invoice_number__icontains=query) | Q(customer_gstin__icontains=query))
    if status: records = records.filter(status=status)
    if start: records = records.filter(created_at__date__gte=start)
    if end: records = records.filter(created_at__date__lte=end)
    rows = []
    for order in records[:500]:
        gst = sum(round(item.line_total * item.gst_rate / Decimal("100")) for item in order.items.all())
        rows.append({"order": order, "taxable": order.total, "gst": gst, "grand": order.total + gst})
    return render(request, "console/sales_register.html", {"rows": rows, "query": query, "status": status, "start": start, "end": end, "status_choices": Order.STATUS_CHOICES})


@login_required
@require_POST
def update_order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    status = request.POST.get("status")

    if status in dict(Order.STATUS_CHOICES):
        order.status = status
        order.save(update_fields=["status"])
        messages.success(
            request,
            f"{order.order_number} marked {order.get_status_display().lower()}.",
        )

    return redirect("console-dashboard")


def _order_tax(order):
    return sum(
        round(item.line_total * item.gst_rate / Decimal("100"))
        for item in order.items.all()
    )


def _financial_year(day):
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _excel_rows(upload):
    """Read the first worksheet from .xlsx, or a UTF-8 CSV upload."""
    if upload.name.lower().endswith(".csv"):
        text = io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text))

    with zipfile.ZipFile(upload.file) as workbook:
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root]
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = []
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for row in sheet.findall("x:sheetData/x:row", namespace):
            values = {}
            for cell in row.findall("x:c", namespace):
                reference = cell.attrib.get("r", "A1")
                column = "".join(char for char in reference if char.isalpha())
                value = cell.find("x:v", namespace)
                text = "" if value is None else value.text or ""
                if cell.attrib.get("t") == "s" and text:
                    text = shared[int(text)]
                values[column] = text
            rows.append(values)
        if not rows:
            return []
        columns = sorted(rows[0], key=lambda value: (len(value), value))
        headers = [rows[0].get(column, "").strip() for column in columns]
        return [
            {header: row.get(column, "").strip() for header, column in zip(headers, columns) if header}
            for row in rows[1:]
        ]


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )


    form = OrderBillingForm(request.POST or None, instance=order)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Billing details saved.")
        return redirect("console-order-detail", order_id=order.id)

    tax_total = _order_tax(order)
    return render(
        request,
        "console/order_detail.html",
        {
            "order": order,
            "form": form,
            "tax_total": tax_total,
            "grand_total": order.total + tax_total,
            "shop_gstin": order.shop.get("gstin", ""),
        },
    )


def _slip(order):
    """Per-line GST working plus totals for slips and loading sheets."""
    lines = []
    for item in order.items.all():
        tax = round(item.line_total * item.gst_rate / Decimal("100"))
        lines.append({"item": item, "tax": tax, "total": item.line_total + tax})
    return {
        "order": order,
        "lines": lines,
        "units": sum(line["item"].quantity for line in lines),
        "tax_total": sum(line["tax"] for line in lines),
        "grand_total": sum(line["total"] for line in lines),
    }


def _consolidated_items(orders):
    """Pick-list rows across orders, grouped the way the warehouse walks it."""
    rows = {}
    for order in orders:
        for item in order.items.all():
            key = (item.sku, item.name, item.unit)
            row = rows.setdefault(
                key,
                {
                    "sku": item.sku,
                    "name": item.name,
                    "unit": item.unit,
                    "quantity": 0,
                    "bills": 0,
                    "product_id": item.product_id_snapshot,
                },
            )
            row["quantity"] += item.quantity
            row["bills"] += 1
    products = (
        Product.objects.select_related("company", "brand").in_bulk(
            {row["product_id"] for row in rows.values()}
        )
        if rows
        else {}
    )
    for row in rows.values():
        product = products.get(row.pop("product_id"))
        row["company"] = product.company.name if product else ""
        row["brand"] = product.brand.name if product else ""
    return sorted(
        rows.values(),
        key=lambda row: (row["company"], row["brand"], row["name"]),
    )


@login_required
def order_slip(request, order_id):
    """Printable billing slip. Carries no invoice number: Marg owns those."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )
    profile = DistributorProfile.objects.first() or DistributorProfile()
    return render(
        request,
        "console/order_slip.html",
        {"order": order, "slips": [_slip(order)], "profile": profile},
    )


@login_required
def order_packing_slip(request, order_id):
    """Dense no-prices packing slip for a single bill."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )
    return render(
        request,
        "console/packing_slip.html",
        {"order": order, "slips": [_slip(order)]},
    )


@login_required
def loading_packing_slips(request, loading_id):
    """One dense packing slip per bill in the loading."""
    loading = get_object_or_404(
        Loading.objects.prefetch_related("orders__items"),
        pk=loading_id,
    )
    orders = list(loading.orders.all())
    return render(
        request,
        "console/packing_slips.html",
        {
            "loading": loading,
            "orders": orders,
            "slips": [_slip(order) for order in orders],
        },
    )


@login_required
def invoice_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )

    profile = DistributorProfile.objects.first() or DistributorProfile()
    seller = order.seller_snapshot or {
        "legalName": profile.legal_name, "gstin": profile.gstin,
        "address": profile.address, "state": profile.state,
    }
    invoice_number = order.invoice_number or f"{profile.invoice_prefix}/{_financial_year(order.created_at.date())}/{order.order_number}"
    seller_profile = SimpleNamespace(
        legal_name=seller.get("legalName", profile.legal_name),
        gstin=seller.get("gstin", profile.gstin),
        address=seller.get("address", profile.address),
        state=seller.get("state", profile.state),
    )
    lines = []
    for item in order.items.all():
        tax = round(item.line_total * item.gst_rate / Decimal("100"))
        lines.append({"item": item, "tax": tax, "total": item.line_total + tax})
    tax_total = sum(line["tax"] for line in lines)
    return render(
        request,
        "console/invoice_detail.html",
        {
            "order": order,
            "profile": seller_profile,
            "invoice_number": invoice_number,
            "lines": lines,
            "tax_total": tax_total,
            "grand_total": order.total + tax_total,
        },
    )


@login_required
def invoice_json(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )
    profile = DistributorProfile.objects.first() or DistributorProfile()
    seller = order.seller_snapshot or {
        "legalName": profile.legal_name, "gstin": profile.gstin,
        "address": profile.address, "state": profile.state,
    }
    tax_total = _order_tax(order)
    payload = {
        "schemaVersion": "draft-1.0",
        "documentType": "INV",
        "invoiceNumber": order.invoice_number or "",
        "invoiceDate": str(order.invoice_date or order.created_at.date()),
        "seller": {
            "legalName": seller.get("legalName", ""),
            "gstin": seller.get("gstin", ""),
            "address": seller.get("address", ""),
            "state": seller.get("state", ""),
        },
        "buyer": {
            "storeName": order.shop.get("storeName", ""),
            "mobile": order.shop.get("mobile", ""),
            "gstin": order.customer_gstin or order.shop.get("gstin", ""),
            "address": order.billing_address or order.shop.get("address", ""),
            "placeOfSupply": order.place_of_supply,
        },
        "items": [
            {
                "sku": item.sku,
                "description": item.name,
                "hsnCode": item.hsn_code,
                "quantity": item.quantity,
                "unit": item.unit,
                "ratePaise": item.rate,
                "taxableValuePaise": item.line_total,
                "gstRate": str(item.gst_rate),
                "gstValuePaise": round(item.line_total * item.gst_rate / Decimal("100")),
            }
            for item in order.items.all()
        ],
        "totals": {
            "taxableValuePaise": order.total,
            "gstValuePaise": tax_total,
            "grandTotalPaise": order.total + tax_total,
        },
        "irn": order.irn,
        "ackNumber": order.ack_number,
        "qrCodeData": order.qr_code_data,
    }
    response = JsonResponse(payload, json_dumps_params={"indent": 2})
    filename = (order.invoice_number or order.order_number).replace("/", "-")
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}.json"'
    )
    return response


@login_required
def invoice_excel(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items"),
        pk=order_id,
    )
    profile = DistributorProfile.objects.first() or DistributorProfile()
    seller = order.seller_snapshot or {
        "legalName": profile.legal_name, "gstin": profile.gstin,
        "address": profile.address, "state": profile.state,
    }
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = (order.invoice_number or order.order_number).replace("/", "-")
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}-offline-tool.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "invoice_number", "invoice_date", "seller_name", "seller_gstin",
            "seller_address", "seller_state", "buyer_store_name", "buyer_mobile",
            "buyer_gstin", "buyer_address", "place_of_supply", "sku", "description",
            "hsn_code", "quantity", "unit", "rate_paise", "taxable_value_paise",
            "gst_rate", "gst_value_paise", "irn", "ack_number", "qr_code_data",
        ]
    )
    for item in order.items.all():
        writer.writerow(
            [
                order.invoice_number,
                order.invoice_date or order.created_at.date(),
                seller.get("legalName", ""),
                seller.get("gstin", ""),
                seller.get("address", ""),
                seller.get("state", ""),
                order.shop.get("storeName", ""),
                order.shop.get("mobile", ""),
                order.customer_gstin or order.shop.get("gstin", ""),
                order.billing_address or order.shop.get("address", ""),
                order.place_of_supply,
                item.sku,
                item.name,
                item.hsn_code,
                item.quantity,
                item.unit,
                item.rate,
                item.line_total,
                item.gst_rate,
                round(item.line_total * item.gst_rate / Decimal("100")),
                order.irn,
                order.ack_number,
                order.qr_code_data,
            ]
        )
    return response


def _parse_ack_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime(1899, 12, 30) + timedelta(days=float(value))
        except ValueError:
            parsed = datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
    if parsed.tzinfo is None:
        parsed = timezone.make_aware(parsed)
    return parsed


@login_required
def einvoice_template(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="asaan-einvoice-portal-template.csv"'
    )
    csv.writer(response).writerow(
        ["invoice_number", "irn", "ack_number", "ack_date", "qr_code_data"]
    )
    return response


@login_required
def einvoice_upload(request):
    if request.method == "GET":
        return render(request, "console/einvoice_upload.html")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Choose a CSV or Excel file.")
        return redirect("console-einvoice-upload")
    try:
        rows = _excel_rows(upload)
        required = {"invoice_number", "irn", "ack_number", "ack_date", "qr_code_data"}
        headers = set(rows[0]) if rows else set()
        missing = required - headers
        if missing:
            raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
        updated = 0
        with transaction.atomic():
            for line_number, row in enumerate(rows, start=2):
                number = row.get("invoice_number", "").strip()
                order = Order.objects.select_for_update().filter(invoice_number=number).first()
                if not order:
                    raise ValueError(f"Row {line_number}: invoice {number} was not found.")
                order.irn = row.get("irn", "").strip()
                order.ack_number = row.get("ack_number", "").strip()
                order.ack_date = _parse_ack_date(row.get("ack_date", "").strip())
                order.qr_code_data = row.get("qr_code_data", "").strip()
                order.einvoice_uploaded_at = timezone.now()
                order.save(update_fields=["irn", "ack_number", "ack_date", "qr_code_data", "einvoice_uploaded_at"])
                updated += 1
        messages.success(request, f"{updated} e-invoice records updated.")
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as exc:
        messages.error(request, f"Upload failed: {exc}")
    return redirect("console-einvoice-upload")


@login_required
def export_orders(request):
    status = request.GET.get("status", "").strip()
    orders = Order.objects.select_related("loading").prefetch_related("items").all()
    if status in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="asaan-orders.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "order_number",
            "created_at",
            "status",
            "store_name",
            "mobile",
            "gstin",
            "billing_address",
            "place_of_supply",
            "invoice_number",
            "invoice_date",
            "loading_number",
            "taxable_total_paise",
            "gst_total_paise",
            "grand_total_paise",
        ]
    )
    for order in orders:
        tax_total = _order_tax(order)
        writer.writerow(
            [
                order.order_number,
                order.created_at.isoformat(),
                order.get_status_display(),
                order.shop.get("storeName", ""),
                order.shop.get("mobile", ""),
                order.customer_gstin or order.shop.get("gstin", ""),
                order.billing_address,
                order.place_of_supply,
                order.invoice_number,
                order.invoice_date or "",
                order.loading.loading_number if order.loading_id else "",
                order.total,
                tax_total,
                order.total + tax_total,
            ]
        )
    return response


@login_required
def export_order_items(request):
    """Flat line-level CSV, one row per SKU, for keying the day's bills into Marg."""
    status = request.GET.get("status", "").strip()
    start = request.GET.get("from", "").strip()
    end = request.GET.get("to", "").strip()
    orders = Order.objects.prefetch_related("items").all()
    if status in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status)
    if start:
        orders = orders.filter(created_at__date__gte=start)
    if end:
        orders = orders.filter(created_at__date__lte=end)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="asaan-order-items.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "order_number",
            "created_at",
            "status",
            "store_name",
            "mobile",
            "customer_gstin",
            "billing_address",
            "place_of_supply",
            "sku",
            "product_name",
            "hsn_code",
            "unit",
            "quantity",
            "rate_paise",
            "line_total_paise",
            "gst_rate",
            "scheme_percent",
            "gst_value_paise",
        ]
    )
    for order in orders:
        buyer_gstin = order.customer_gstin or order.shop.get("gstin", "")
        buyer_address = order.billing_address or order.shop.get("address", "")
        for item in order.items.all():
            writer.writerow(
                [
                    order.order_number,
                    order.created_at.isoformat(),
                    order.get_status_display(),
                    order.shop.get("storeName", ""),
                    order.shop.get("mobile", ""),
                    buyer_gstin,
                    buyer_address,
                    order.place_of_supply,
                    item.sku,
                    item.name,
                    item.hsn_code,
                    item.unit,
                    item.quantity,
                    item.rate,
                    item.line_total,
                    item.gst_rate,
                    item.scheme_percent,
                    round(item.line_total * item.gst_rate / Decimal("100")),
                ]
            )
    return response


@login_required
def dispatch_summary(request):
    eligible = Order.objects.prefetch_related("items").filter(
        status__in=["received", "processing"], loading__isnull=True
    )
    if request.method == "POST":
        selected_ids = request.POST.getlist("order_ids")
        if not selected_ids:
            messages.error(request, "Select at least one bill for the loading.")
            return redirect("console-dispatch-summary")
        with transaction.atomic():
            selected = list(
                Order.objects.select_for_update().filter(
                    id__in=selected_ids,
                    status__in=["received", "processing"],
                )
            )
            if len(selected) != len(set(selected_ids)) or any(
                order.loading_id for order in selected
            ):
                messages.error(
                    request,
                    "One or more selected bills already belongs to a loading.",
                )
                return redirect("console-dispatch-summary")
            if request.POST.get("action") == "convert":
                # Invoice conversion and stock posting are paused: bills are
                # raised by hand in Marg. Loading sheets remain available.
                messages.error(
                    request,
                    "Invoice conversion is paused while billing happens in Marg.",
                )
                return redirect("console-dispatch-summary")
            loading = Loading.objects.create(
                loading_number=f"LOAD-{uuid.uuid4().hex[:8].upper()}"
            )
            Order.objects.filter(id__in=[order.id for order in selected]).update(
                loading=loading
            )
        messages.success(request, f"{loading.loading_number} created with {len(selected)} bills.")
        return redirect("console-loading-detail", loading_id=loading.id)

    orders = eligible
    pick_list = _consolidated_items(orders)

    return render(
        request,
        "console/dispatch_summary.html",
        {
            "orders": orders,
            "pick_list": pick_list,
            "pick_units": sum(row["quantity"] for row in pick_list),
            "generated_at": date.today(),
        },
    )


@login_required
def loading_detail(request, loading_id):
    loading = get_object_or_404(
        Loading.objects.prefetch_related("orders__items"),
        pk=loading_id,
    )
    orders = list(loading.orders.all())
    profile = DistributorProfile.objects.first() or DistributorProfile()
    return render(
        request,
        "console/loading_detail.html",
        {
            "loading": loading,
            "orders": orders,
            "items": _consolidated_items(orders),
            "profile": profile,
            "slips": [_slip(order) for order in orders],
        },
    )


@login_required
def products(request):
    query = request.GET.get("q", "").strip()
    items = Product.objects.all()

    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(simple_name__icontains=query)
            | Q(sku__icontains=query)
            | Q(company__name__icontains=query)
            | Q(brand__name__icontains=query)
        )

    return render(
        request,
        "console/products.html",
        {"products": items[:200], "query": query},
    )


ProductBulkFormSet = modelformset_factory(Product, form=ProductBulkForm, extra=0)
ShopBulkFormSet = modelformset_factory(Shop, form=ShopBulkForm, extra=0)
SHEET_SIZE = 100


def _sheet_page(request, queryset):
    """The same page of rows for GET and for the POST that saves the sheet."""
    number = request.POST.get("page") or request.GET.get("page") or 1
    return Paginator(queryset, SHEET_SIZE).get_page(number)


@login_required
def product_bulk(request):
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    products = Product.objects.select_related("company", "brand").order_by(
        "company__name", "brand__name", "name"
    )
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(simple_name__icontains=query)
            | Q(sku__icontains=query)
            | Q(company__name__icontains=query)
            | Q(brand__name__icontains=query)
        )
    page = _sheet_page(request, products)
    formset = ProductBulkFormSet(request.POST or None, queryset=page.object_list)
    if request.method == "POST" and formset.is_valid():
        updated = len(formset.save())
        messages.success(
            request,
            f"{updated} product{'s' if updated != 1 else ''} updated.",
        )
        return redirect(
            f"{reverse('console-product-bulk')}?q={quote(query)}&page={page.number}"
        )
    return render(
        request,
        "console/product_bulk.html",
        {"formset": formset, "page": page, "query": query},
    )


@login_required
def inventory(request):
    rows = (
        StockLedger.objects.values(
            "warehouse__name",
            "product__sku",
            "product__name",
            "product__unit",
        )
        .annotate(on_hand=Sum("quantity_delta"))
        .order_by("warehouse__name", "product__name")
    )
    return render(request, "console/inventory.html", {"stock": rows})


@login_required
def purchases(request):
    records = Purchase.objects.select_related("supplier", "warehouse").all()[:200]
    return render(request, "console/purchases.html", {"purchases": records})


@login_required
def returns(request):
    return render(request, "console/returns.html", {
        "sales_returns": SalesReturn.objects.select_related("order", "warehouse")[:100],
        "purchase_returns": PurchaseReturn.objects.select_related("purchase", "warehouse")[:100],
    })


@login_required
def return_note(request, kind, return_id):
    model = SalesReturn if kind == "sales" else PurchaseReturn
    record = get_object_or_404(model.objects.prefetch_related("items"), pk=return_id)
    return render(request, "console/return_note.html", {"record": record, "kind": kind})


@login_required
def gst_report(request):
    start = request.GET.get("from", "")
    end = request.GET.get("to", "")
    # Invoicing is paused while bills are raised in Marg, so non-cancelled
    # orders stand in for issued invoices.
    orders = Order.objects.exclude(status="cancelled")
    purchases_qs = Purchase.objects.filter(status="posted")
    if start:
        orders = orders.filter(created_at__date__gte=start)
        purchases_qs = purchases_qs.filter(created_at__date__gte=start)
    if end:
        orders = orders.filter(created_at__date__lte=end)
        purchases_qs = purchases_qs.filter(created_at__date__lte=end)
    sales = list(orders.values("order_number", "total"))
    purchases = list(purchases_qs.values("purchase_number", "taxable_total", "gst_total"))
    sales_taxable = sum(row["total"] for row in sales)
    sales_gst = sum(round(item.line_total * item.gst_rate / Decimal("100")) for item in OrderItem.objects.filter(order__in=orders))
    hsn_rows, rate_rows = {}, {}
    for item in OrderItem.objects.filter(order__in=orders):
        key = item.hsn_code or "Unspecified"; rate = str(item.gst_rate)
        gst = round(item.line_total * item.gst_rate / Decimal("100"))
        for bucket, bucket_key in ((hsn_rows, key), (rate_rows, rate)):
            row = bucket.setdefault(bucket_key, {"key": bucket_key, "taxable": 0, "gst": 0})
            row["taxable"] += item.line_total; row["gst"] += gst
    for item in PurchaseItem.objects.filter(purchase__in=purchases_qs):
        key = item.hsn_code or "Unspecified"; rate = str(item.gst_rate)
        gst = round(item.line_total * item.gst_rate / Decimal("100"))
        for bucket, bucket_key in ((hsn_rows, key), (rate_rows, rate)):
            row = bucket.setdefault(bucket_key, {"key": bucket_key, "taxable": 0, "gst": 0})
            row["taxable"] += item.line_total; row["gst"] += gst
    context = {"sales_count": len(sales), "sales_taxable": Decimal(sales_taxable) / 100, "sales_gst": Decimal(sales_gst) / 100, "purchase_count": len(purchases), "purchase_taxable": Decimal(sum(row["taxable_total"] for row in purchases)) / 100, "purchase_gst": Decimal(sum(row["gst_total"] for row in purchases)) / 100, "sales_return_total": Decimal(sum(x.taxable_total for x in SalesReturn.objects.filter(status="posted"))) / 100, "purchase_return_total": Decimal(sum(x.taxable_total for x in PurchaseReturn.objects.filter(status="posted"))) / 100, "hsn_rows": [{**r, "taxable": Decimal(r["taxable"]) / 100, "gst": Decimal(r["gst"]) / 100} for r in sorted(hsn_rows.values(), key=lambda x: x["key"])], "rate_rows": [{**r, "taxable": Decimal(r["taxable"]) / 100, "gst": Decimal(r["gst"]) / 100} for r in sorted(rate_rows.values(), key=lambda x: Decimal(x["key"]))], "start": start, "end": end}
    response = render(request, "console/gst_report.html", context)
    response.context_data = context
    return response


@login_required
def gst_report_csv(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="gst-summary.csv"'
    writer = csv.writer(response)
    writer.writerow(["Report", "Taxable (₹)", "GST (₹)"])
    report = gst_report(request)
    context = report.context_data
    for row in context.get("hsn_rows", []): writer.writerow([f"HSN {row['key']}", row["taxable"], row["gst"]])
    for row in context.get("rate_rows", []): writer.writerow([f"GST rate {row['key']}%", row["taxable"], row["gst"]])
    return response


@login_required
def return_edit(request, kind, return_id=None):
    sales = kind == "sales"
    model = SalesReturn if sales else PurchaseReturn
    instance = get_object_or_404(model, pk=return_id) if return_id else model()
    if instance.pk and instance.status == "posted":
        messages.info(request, "Posted returns are read-only.")
        return redirect("console-returns")
    parent_form = SalesReturnForm if sales else PurchaseReturnForm
    formset_class = SalesReturnItemFormSet if sales else PurchaseReturnItemFormSet
    form = parent_form(request.POST or None, instance=instance)
    formset = formset_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        rows = [f for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not rows:
            messages.error(request, "Add at least one return item.")
        else:
            source_items = (form.cleaned_data.get("order").items.all() if sales else form.cleaned_data.get("purchase").items.all())
            allowed = {}
            for source in source_items:
                source_product_id = source.product_id_snapshot if sales else source.product_id
                allowed[source_product_id] = allowed.get(source_product_id, Decimal("0")) + source.quantity
            requested = {}
            for row in rows:
                product_id = row.cleaned_data["product"].id
                requested[product_id] = requested.get(product_id, Decimal("0")) + row.cleaned_data["quantity"]
            if any(requested.get(product_id, 0) > quantity for product_id, quantity in allowed.items()) or any(product_id not in allowed for product_id in requested):
                messages.error(request, "Return quantity cannot exceed the quantity on the source document.")
                return render(request, "console/return_form.html", {"form": form, "formset": formset, "kind": kind, "record": instance})
            action = request.POST.get("action", "draft")
            with transaction.atomic():
                obj = form.save(commit=False)
                if not obj.return_number:
                    obj.return_number = ("SR-" if sales else "PR-") + uuid.uuid4().hex[:10].upper()
                taxable = sum(round(f.cleaned_data["quantity"] * f.cleaned_data["rate"]) for f in rows)
                gst = sum(round(round(f.cleaned_data["quantity"] * f.cleaned_data["rate"]) * f.cleaned_data["gst_rate"] / Decimal("100")) for f in rows)
                obj.taxable_total, obj.gst_total, obj.grand_total = taxable, gst, taxable + gst
                if action == "posted": obj.status = "posted"
                if action == "posted":
                    source = obj.order if sales else obj.purchase
                    obj.source_snapshot = {
                        "number": source.order_number if sales else source.purchase_number,
                        "date": str(source.created_at.date()),
                    }
                obj.save()
                formset.instance = obj
                formset.save(commit=False)
                for item_form in rows:
                    item = item_form.save(commit=False)
                    item.line_total = round(item.quantity * item.rate)
                    if action == "posted":
                        item.product_snapshot = {
                            "sku": item.product.sku, "name": item.product.name,
                            "hsnCode": item.product.hsn_code, "unit": item.product.unit,
                            "gstRate": str(item.product.gst_rate),
                        }
                    item.save()
                    if action == "posted":
                        StockLedger.objects.get_or_create(
                            warehouse=obj.warehouse, product=item.product,
                            movement_type="sales_return" if sales else "purchase_return",
                            reference_type="sales_return" if sales else "purchase_return",
                            reference_id=str(obj.id),
                            defaults={"quantity_delta": item.quantity if sales else -item.quantity, "unit_cost": item.rate},
                        )
                for deleted in formset.deleted_objects: deleted.delete()
            messages.success(request, f"{obj.return_number} saved.")
            return redirect("console-returns")
    return render(request, "console/return_form.html", {"form": form, "formset": formset, "kind": kind, "record": instance})


def _purchase_tax_summary(purchase):
    hsn = {}
    rates = {}
    for item in purchase.items.all():
        taxable = item.line_total
        gst = round(taxable * item.gst_rate / Decimal("100"))
        hsn_key = item.hsn_code or "Unspecified"
        hsn_row = hsn.setdefault(hsn_key, {"taxable": 0, "gst": 0})
        hsn_row["taxable"] += taxable
        hsn_row["gst"] += gst
        rate_key = str(item.gst_rate)
        rate_row = rates.setdefault(rate_key, {"rate": item.gst_rate, "taxable": 0, "gst": 0})
        rate_row["taxable"] += taxable
        rate_row["gst"] += gst
    return sorted(
        [{"hsn": key, **value} for key, value in hsn.items()],
        key=lambda row: row["hsn"],
    ), sorted(rates.values(), key=lambda row: row["rate"])


@login_required
@require_POST
def quick_create_supplier(request):
    form = QuickSupplierForm(request.POST)
    if form.is_valid():
        supplier = form.save()
        return JsonResponse({"id": supplier.id, "name": supplier.name})
    return JsonResponse({"errors": form.errors.get_json_data()}, status=400)


@login_required
@require_POST
def quick_create_product(request):
    form = QuickProductForm(request.POST)
    if form.is_valid():
        product = form.save()
        return JsonResponse({
            "id": str(product.id),
            "label": str(product),
            "sku": product.sku,
        })
    return JsonResponse({"errors": form.errors.get_json_data()}, status=400)


@login_required
@require_POST
def quick_create_lookup(request):
    kind = request.POST.get("kind")
    name = request.POST.get("name", "").strip()
    model_map = {"company": Company, "brand": Brand, "category": Category}
    if kind in model_map:
        if not name:
            return JsonResponse({"error": "Name is required."}, status=400)
        obj, _ = model_map[kind].objects.get_or_create(name=name)
        return JsonResponse({"id": obj.id, "label": obj.name})
    if kind == "hsn":
        if not name:
            return JsonResponse({"error": "HSN code is required."}, status=400)
        try:
            rate = Decimal(request.POST.get("default_gst_rate", "0"))
        except InvalidOperation:
            return JsonResponse({"error": "GST rate must be numeric."}, status=400)
        obj, _ = HSN.objects.get_or_create(code=name, defaults={"default_gst_rate": rate})
        return JsonResponse({"id": obj.id, "label": str(obj), "gstRate": str(obj.default_gst_rate)})
    return JsonResponse({"error": "Unsupported master."}, status=400)


@login_required
def purchase_edit(request, purchase_id=None):
    purchase = (
        get_object_or_404(Purchase, pk=purchase_id) if purchase_id else Purchase()
    )
    if purchase.pk and purchase.status == "posted":
        messages.info(request, "Posted purchases are read-only.")
        return redirect("console-purchase-list")

    form = PurchaseForm(request.POST or None, instance=purchase)
    formset = PurchaseItemFormSet(request.POST or None, instance=purchase)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        item_forms = [item_form for item_form in formset.forms if item_form.cleaned_data and not item_form.cleaned_data.get("DELETE")]
        if not item_forms:
            messages.error(request, "Add at least one purchase item.")
        else:
            action = request.POST.get("action", "draft")
            with transaction.atomic():
                purchase = form.save(commit=False)
                if not purchase.purchase_number:
                    purchase.purchase_number = "PUR-" + uuid.uuid4().hex[:10].upper()
                taxable_total = 0
                gst_total = 0
                for item_form in item_forms:
                    data = item_form.cleaned_data
                    line_total = data.get("taxable_total")
                    if line_total is None:
                        line_total = round(data["quantity"] * data["rate"])
                    taxable_total += line_total
                    gst_total += round(line_total * data["gst_rate"] / Decimal("100"))
                purchase.taxable_total = taxable_total
                purchase.gst_total = gst_total
                purchase.tds_total = round(taxable_total * purchase.tds_rate / Decimal("100"))
                purchase.grand_total = taxable_total + gst_total - purchase.tds_total
                if action == "posted":
                    supplier = purchase.supplier
                    warehouse = purchase.warehouse
                    purchase.supplier_snapshot = {
                        "name": supplier.name, "mobile": supplier.mobile,
                        "gstin": supplier.gstin, "address": supplier.address,
                        "pincode": supplier.pincode, "state": supplier.state,
                        "email": supplier.email, "pan": supplier.pan,
                    }
                    purchase.warehouse_snapshot = {
                        "name": warehouse.name, "code": warehouse.code,
                        "address": warehouse.address, "state": warehouse.state,
                    }
                    purchase.status = "posted"
                    purchase.posted_at = timezone.now()
                purchase.save()
                formset.instance = purchase
                # Populate deleted_objects while saving the non-deleted rows below.
                formset.save(commit=False)
                for item_form in item_forms:
                    data = item_form.cleaned_data
                    item = item_form.save(commit=False)
                    item.hsn_code = item.product.hsn_code
                    if action == "posted":
                        item.product_snapshot = {
                            "sku": item.product.sku, "name": item.product.name,
                            "simpleName": item.product.simple_name,
                            "hsnCode": item.product.hsn_code, "unit": item.product.unit,
                            "packing": item.product.packing, "gstRate": str(item.product.gst_rate),
                        }
                    item.line_total = data.get("taxable_total")
                    if item.line_total is None:
                        item.line_total = round(item.quantity * item.rate)
                    item.save()
                    if action == "posted":
                        StockLedger.objects.create(
                            warehouse=purchase.warehouse,
                            product=item.product,
                            movement_type="purchase",
                            quantity_delta=item.quantity,
                            unit_cost=item.rate,
                            reference_type="purchase",
                            reference_id=str(purchase.id),
                        )
                for item in formset.deleted_objects:
                    item.delete()
            messages.success(request, f"{purchase.purchase_number} saved.")
            return redirect("console-purchase-list")

    return render(
        request,
        "console/purchase_form.html",
        {
            "form": form,
            "formset": formset,
            "purchase": purchase,
            "hsn_tax_summary": _purchase_tax_summary(purchase)[0],
            "rate_tax_summary": _purchase_tax_summary(purchase)[1],
        },
    )


@login_required
def shops(request):
    query = request.GET.get("q", "").strip()
    records = Shop.objects.all()
    if query:
        records = records.filter(
            Q(store_name__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(mobile__icontains=query)
            | Q(gstin__icontains=query)
        )
    return render(request, "console/shops.html", {"shops": records[:200], "query": query})


@login_required
def shop_bulk(request):
    query = (request.POST.get("q") or request.GET.get("q") or "").strip()
    shops = Shop.objects.order_by("store_name", "mobile")
    if query:
        shops = shops.filter(
            Q(store_name__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(mobile__icontains=query)
            | Q(gstin__icontains=query)
        )
    page = _sheet_page(request, shops)
    formset = ShopBulkFormSet(request.POST or None, queryset=page.object_list)
    if request.method == "POST" and formset.is_valid():
        updated = len(formset.save())
        messages.success(
            request,
            f"{updated} shop{'s' if updated != 1 else ''} updated.",
        )
        return redirect(
            f"{reverse('console-shop-bulk')}?q={quote(query)}&page={page.number}"
        )
    return render(
        request,
        "console/shop_bulk.html",
        {"formset": formset, "page": page, "query": query},
    )


@login_required
def shop_edit(request, shop_id=None):
    shop = get_object_or_404(Shop, pk=shop_id) if shop_id else None
    form = ShopForm(request.POST or None, instance=shop)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Shop saved.")
        return redirect("console-shops")
    return render(request, "console/shop_form.html", {"form": form, "shop": shop})


@login_required
@require_POST
def shop_delete(request, shop_id):
    shop = get_object_or_404(Shop, pk=shop_id)
    shop.active = False
    shop.save(update_fields=["active", "updated_at"])
    messages.success(request, "Shop deactivated.")
    return redirect("console-shops")


@login_required
def invoice_settings(request):
    profile = DistributorProfile.objects.first()
    form = DistributorProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Invoice profile saved.")
        return redirect("console-invoice-settings")
    return render(request, "console/invoice_settings.html", {"form": form})


@login_required
def product_edit(request, product_id=None):
    product = get_object_or_404(Product, pk=product_id) if product_id else None
    form = ProductForm(
        request.POST or None,
        request.FILES or None,
        instance=product,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product saved.")
        return redirect("console-products")

    return render(
        request,
        "console/product_form.html",
        {"form": form, "product": product},
    )


@login_required
def product_import_template(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="asaan-product-import-template.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "sku",
            "name",
            "simple_name",
            "company",
            "brand",
            "category",
            "hsn_code",
            "packing",
            "unit",
            "sale_rate",
            "mrp",
            "gst_rate",
            "scheme_percent",
            "image_url",
            "active",
        ]
    )
    return response


@login_required
def product_import(request):
    if request.method == "GET":
        return render(request, "console/product_import.html")

    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Choose a CSV file to import.")
        return redirect("console-product-import")

    required = {
        "sku",
        "name",
        "company",
        "brand",
        "category",
        "packing",
        "unit",
        "sale_rate",
        "mrp",
    }

    try:
        text = io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        headers = {
            header.strip()
            for header in (reader.fieldnames or [])
            if header
        }
        missing = required - headers

        if missing:
            raise ValueError(
                "Missing required columns: " + ", ".join(sorted(missing))
            )

        imported = 0
        with transaction.atomic():
            for row_number, row in enumerate(reader, start=2):
                row = {
                    key.strip(): (value or "").strip()
                    for key, value in row.items()
                    if key
                }

                if not row.get("sku"):
                    raise ValueError(f"Row {row_number}: SKU is required.")
                empty_fields = [
                    field
                    for field in required - {"sku"}
                    if not row.get(field)
                ]
                if empty_fields:
                    raise ValueError(
                        f"Row {row_number}: missing "
                        + ", ".join(sorted(empty_fields))
                        + "."
                    )

                try:
                    sale_rate = round(Decimal(row["sale_rate"]) * 100)
                    mrp = round(Decimal(row["mrp"]) * 100)
                    gst_rate = Decimal(row.get("gst_rate") or "0")
                    scheme_percent = Decimal(row.get("scheme_percent") or "0")
                except (InvalidOperation, TypeError):
                    raise ValueError(
                        f"Row {row_number}: sale_rate and mrp must be numbers."
                    )

                if sale_rate < 0 or mrp < 0 or gst_rate < 0 or gst_rate > 100:
                    raise ValueError(
                        f"Row {row_number}: prices must be positive and GST must be between 0 and 100."
                    )
                if scheme_percent < 0 or scheme_percent > 100:
                    raise ValueError(
                        f"Row {row_number}: scheme_percent must be between 0 and 100."
                    )

                Product.objects.update_or_create(
                    sku=row["sku"],
                    defaults={
                        "name": row["name"],
                        "simple_name": row.get("simple_name", ""),
                        "company": Company.objects.get_or_create(
                            name=row["company"]
                        )[0],
                        "brand": Brand.objects.get_or_create(
                            name=row["brand"]
                        )[0],
                        "category": Category.objects.get_or_create(
                            name=row["category"]
                        )[0],
                        "hsn_code": row.get("hsn_code", ""),
                        "packing": row["packing"],
                        "unit": row["unit"] or "case",
                        "rate": sale_rate,
                        "mrp": mrp,
                        "gst_rate": gst_rate,
                        "scheme_percent": scheme_percent,
                        "image_url": row.get("image_url", ""),
                        "active": row.get("active", "true").lower()
                        not in {"false", "0", "no"},
                    },
                )
                imported += 1

        messages.success(request, f"{imported} products imported or updated.")
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        messages.error(request, f"Import failed: {exc}")
    finally:
        try:
            text.detach()
        except (UnboundLocalError, AttributeError, ValueError):
            pass

    return redirect("console-products")
