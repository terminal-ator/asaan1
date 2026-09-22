from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="console-dashboard"),
    path("sales", views.sales_register, name="console-sales-register"),
    path(
        "orders/<uuid:order_id>/status",
        views.update_order_status,
        name="console-order-status",
    ),
    path(
        "orders/<uuid:order_id>",
        views.order_detail,
        name="console-order-detail",
    ),
    path(
        "orders/<uuid:order_id>/invoice",
        views.invoice_detail,
        name="console-invoice-detail",
    ),
    path(
        "orders/<uuid:order_id>/invoice.json",
        views.invoice_json,
        name="console-invoice-json",
    ),
    path(
        "orders/<uuid:order_id>/invoice.csv",
        views.invoice_excel,
        name="console-invoice-excel",
    ),
    path("orders/export.csv", views.export_orders, name="console-orders-export"),
    path(
        "orders/export-items.csv",
        views.export_order_items,
        name="console-order-items-export",
    ),
    path(
        "orders/<uuid:order_id>/slip",
        views.order_slip,
        name="console-order-slip",
    ),
    path(
        "dispatch-summary",
        views.dispatch_summary,
        name="console-dispatch-summary",
    ),
    path(
        "loadings/<uuid:loading_id>",
        views.loading_detail,
        name="console-loading-detail",
    ),
    path("products", views.products, name="console-products"),
    path("inventory", views.inventory, name="console-inventory"),
    path("purchases", views.purchases, name="console-purchase-list"),
    path("masters/suppliers/quick-create", views.quick_create_supplier, name="console-quick-supplier"),
    path("masters/products/quick-create", views.quick_create_product, name="console-quick-product"),
    path("masters/lookups/quick-create", views.quick_create_lookup, name="console-quick-lookup"),
    path("purchases/new", views.purchase_edit, name="console-purchase-new"),
    path("purchases/<uuid:purchase_id>/edit", views.purchase_edit, name="console-purchase-edit"),
    path("returns", views.returns, name="console-returns"),
    path("returns/<str:kind>/new", views.return_edit, name="console-return-new"),
    path("returns/<str:kind>/<uuid:return_id>/edit", views.return_edit, name="console-return-edit"),
    path("returns/<str:kind>/<uuid:return_id>/note", views.return_note, name="console-return-note"),
    path("reports/gst", views.gst_report, name="console-gst-report"),
    path("reports/gst.csv", views.gst_report_csv, name="console-gst-report-csv"),
    path("shops", views.shops, name="console-shops"),
    path("shops/new", views.shop_edit, name="console-shop-new"),
    path("shops/<int:shop_id>/edit", views.shop_edit, name="console-shop-edit"),
    path("shops/<int:shop_id>/delete", views.shop_delete, name="console-shop-delete"),
    path("settings/invoice", views.invoice_settings, name="console-invoice-settings"),
    path("einvoice/upload", views.einvoice_upload, name="console-einvoice-upload"),
    path("einvoice/template.csv", views.einvoice_template, name="console-einvoice-template"),
    path(
        "products/new",
        views.product_edit,
        name="console-product-new",
    ),
    path(
        "products/import",
        views.product_import,
        name="console-product-import",
    ),
    path(
        "products/import/template.csv",
        views.product_import_template,
        name="console-product-import-template",
    ),
    path(
        "products/<uuid:product_id>/edit",
        views.product_edit,
        name="console-product-edit",
    ),
]
