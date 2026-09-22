import csv
from decimal import Decimal, InvalidOperation

from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from .models import (
    Brand,
    Category,
    Company,
    DistributorProfile,
    InvoiceSequence,
    Loading,
    Order,
    OrderItem,
    Product,
    HSN,
    Purchase,
    PurchaseItem,
    PurchaseReturn,
    PurchaseReturnItem,
    SalesReturn,
    SalesReturnItem,
    Shop,
    StockLedger,
    Supplier,
    Warehouse,
)

admin.site.register(HSN)


@admin.register(Company, Brand, Category)
class LookupAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display=('__str__','sku','company','brand','rate','active','updated_at'); list_filter=('active','company','brand','category'); search_fields=('name','simple_name','sku','company__name','brand__name'); list_editable=('active',)
    change_list_template='admin/catalogue/product_change_list.html'
    def get_urls(self):
        return [path('import-csv/', self.admin_site.admin_view(self.import_csv), name='catalogue_product_import')] + super().get_urls()
    def import_csv(self, request):
        if request.method == 'POST':
            upload = request.FILES.get('file')
            if not upload:
                messages.error(request, 'Choose a CSV file.')
                return HttpResponseRedirect('../import-csv/')
            try:
                rows = csv.DictReader((line.decode('utf-8-sig') for line in upload.file))
                required = {'sku', 'name', 'company', 'brand', 'category', 'packing', 'unit', 'sale_rate', 'mrp'}
                if not required.issubset(set(rows.fieldnames or [])):
                    raise ValueError('CSV is missing a required column.')
                count = 0
                with transaction.atomic():
                    for row in rows:
                        sku = (row.get('sku') or '').strip()
                        rate = self._decimal(row, 'sale_rate') * 100
                        mrp = self._decimal(row, 'mrp') * 100
                        gst_rate = self._decimal(row, 'gst_rate')
                        scheme_percent = self._decimal(row, 'scheme_percent')
                        if rate < 0 or mrp < 0 or gst_rate < 0 or gst_rate > 100:
                            raise ValueError(f'Row {sku}: prices must be positive and GST must be between 0 and 100.')
                        if scheme_percent < 0 or scheme_percent > 100:
                            raise ValueError(f'Row {sku}: scheme_percent must be between 0 and 100.')
                        Product.objects.update_or_create(
                            sku=sku,
                            defaults={
                                'name': row['name'].strip(),
                                'simple_name': (row.get('simple_name') or '').strip(),
                                'company': Company.objects.get_or_create(name=row['company'].strip())[0],
                                'brand': Brand.objects.get_or_create(name=row['brand'].strip())[0],
                                'category': Category.objects.get_or_create(name=row['category'].strip())[0],
                                'packing': row['packing'].strip(),
                                'unit': row['unit'].strip(),
                                'rate': round(rate),
                                'mrp': round(mrp),
                                'gst_rate': gst_rate,
                                'scheme_percent': scheme_percent,
                                'hsn_code': (row.get('hsn_code') or '').strip(),
                                'image_url': (row.get('image_url') or '').strip(),
                                'active': (row.get('active') or 'true').lower() != 'false',
                            },
                        )
                        count += 1
                messages.success(request, f'{count} products imported or updated.')
            except Exception as exc:
                messages.error(request, f'Import failed: {exc}')
            return HttpResponseRedirect('../')
        return TemplateResponse(request, 'admin/catalogue/product_import.html', {'title':'Import products', 'opts':self.model._meta, 'has_view_permission':True})

    @staticmethod
    def _decimal(row, key):
        try:
            return Decimal(row.get(key) or '0')
        except (InvalidOperation, TypeError):
            raise ValueError(f"Row {row.get('sku') or '?'}: {key} must be a number.")

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}; extra_context['import_url'] = 'import-csv/'
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("store_name", "customer_name", "mobile", "gstin", "active", "updated_at")
    list_filter = ("active", "state")
    search_fields = ("store_name", "customer_name", "mobile", "gstin")


@admin.register(Loading)
class LoadingAdmin(admin.ModelAdmin):
    list_display = ("loading_number", "status", "created_at", "printed_at")
    list_filter = ("status", "created_at")
    search_fields = ("loading_number",)


@admin.register(DistributorProfile)
class DistributorProfileAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "gstin", "invoice_prefix", "updated_at")


@admin.register(InvoiceSequence)
class InvoiceSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "financial_year", "next_number")
    list_editable = ("next_number",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "state", "active")
    list_filter = ("active", "state")
    search_fields = ("name", "code")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "mobile", "gstin", "tds_section", "active")
    list_filter = ("active", "state")
    search_fields = ("name", "mobile", "gstin")


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("purchase_number", "supplier", "warehouse", "status", "grand_total", "created_at")
    list_filter = ("status", "warehouse", "created_at")
    search_fields = ("purchase_number", "supplier_invoice_number", "supplier__name")
    inlines = (PurchaseItemInline,)


@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "warehouse", "product", "movement_type", "quantity_delta", "reference_type")
    list_filter = ("movement_type", "warehouse", "occurred_at")
    search_fields = ("product__sku", "product__name", "reference_id")
    readonly_fields = ("occurred_at",)


@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    list_display = ("return_number", "order", "warehouse", "status", "grand_total", "created_at")
    list_filter = ("status", "warehouse", "created_at")
    search_fields = ("return_number", "order__order_number")
    class SalesReturnItemInline(admin.TabularInline):
        model = SalesReturnItem
        extra = 1
    inlines = (SalesReturnItemInline,)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if obj.status == "posted":
            for item in obj.items.all():
                StockLedger.objects.get_or_create(
                    warehouse=obj.warehouse, product=item.product,
                    movement_type="sales_return", reference_type="sales_return",
                    reference_id=str(obj.id),
                    defaults={"quantity_delta": item.quantity, "unit_cost": item.rate},
                )


@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ("return_number", "purchase", "warehouse", "status", "grand_total", "created_at")
    list_filter = ("status", "warehouse", "created_at")
    search_fields = ("return_number", "purchase__purchase_number")
    class PurchaseReturnItemInline(admin.TabularInline):
        model = PurchaseReturnItem
        extra = 1
    inlines = (PurchaseReturnItemInline,)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if obj.status == "posted":
            for item in obj.items.all():
                StockLedger.objects.get_or_create(
                    warehouse=obj.warehouse, product=item.product,
                    movement_type="purchase_return", reference_type="purchase_return",
                    reference_id=str(obj.id),
                    defaults={"quantity_delta": -item.quantity, "unit_cost": item.rate},
                )
class OrderItemInline(admin.TabularInline):
    model=OrderItem; extra=0; readonly_fields=('product_id_snapshot','sku','name','unit','quantity','rate','line_total')
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display=('order_number','shop_name','shop_mobile','total','status','created_at'); list_filter=('status','created_at'); search_fields=('order_number','client_order_id'); readonly_fields=('client_order_id','order_number','shop','notes','total','created_at'); inlines=(OrderItemInline,); list_editable=('status',)
    def shop_name(self,obj): return obj.shop.get('storeName','')
    def shop_mobile(self,obj): return obj.shop.get('mobile','')
