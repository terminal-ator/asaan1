from django.urls import path

from . import views
from . import product_media
from . import quick_add
from . import staff_app
from . import bundle_views
from . import scheme_views


urlpatterns = [
    path("bundles", bundle_views.bundles, name="console-bundles"),
    path("bundles/new", bundle_views.bundle_edit, name="console-bundle-create"),
    path("bundles/<int:bundle_id>", bundle_views.bundle_edit, name="console-bundle-edit"),
    path("", views.dashboard, name="console-dashboard"),
    path("schemes", scheme_views.schemes, name="console-schemes"),
    path("schemes/new", scheme_views.scheme_edit, name="console-scheme-create"),
    path("schemes/<int:scheme_id>", scheme_views.scheme_edit, name="console-scheme-edit"),
    path("deals", views.deals, name="console-deals"),
    path("deals/send", views.send_deal, name="console-send-deal"),
    path("reminders/send", views.send_reminders, name="console-send-reminders"),
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
        "orders/<uuid:order_id>/packing-slip",
        views.order_packing_slip,
        name="console-order-packing-slip",
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
    path(
        "loadings/<uuid:loading_id>/packing-slips",
        views.loading_packing_slips,
        name="console-loading-packing-slips",
    ),
    path("products", views.products, name="console-products"),
    path("app/", staff_app.app, name="console-staff-app"),
    path("app/manifest.webmanifest", staff_app.manifest, name="console-staff-manifest"),
    path("app/sw.js", staff_app.service_worker, name="console-staff-sw"),
    path("app/products", staff_app.create_product, name="console-staff-create"),
    path("app/masters/<str:kind>/<int:master_id>", staff_app.update_master, name="console-staff-master"),
    path("products/quick-add", quick_add.product_quick_add, name="console-product-quick-add"),
    path("products/<uuid:product_id>/restore", quick_add.product_restore, name="console-product-restore"),
    path("products/images", product_media.workspace, name="console-product-images"),
    path("products/images/data", product_media.product_list, name="console-product-images-data"),
    path("products/<uuid:product_id>/image", product_media.update_image, name="console-product-image-update"),
    path("products/<uuid:product_id>/quick-edit", product_media.update_product, name="console-product-quick-edit"),
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
    path("shops/bulk", views.shop_bulk, name="console-shop-bulk"),
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
        "products/bulk",
        views.product_bulk,
        name="console-product-bulk",
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
