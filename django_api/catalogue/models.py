import uuid
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class HSN(models.Model):
    code = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=255, blank=True)
    default_gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.default_gst_rate}%)"


class Loading(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("printed", "Printed"),
        ("dispatched", "Dispatched"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loading_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.loading_number


class Shop(models.Model):
    store_name = models.CharField(max_length=200)
    customer_name = models.CharField(max_length=150, blank=True)
    mobile = models.CharField(max_length=30)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_accuracy = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["store_name", "mobile"]

    def __str__(self):
        return f"{self.store_name} ({self.mobile})"


class Warehouse(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, unique=True)
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=30, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(default="")
    pincode = models.CharField(max_length=10, default="")
    state = models.CharField(max_length=100, default="")
    email = models.EmailField(blank=True)
    pan = models.CharField(max_length=10, blank=True)
    tds_section = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Purchase(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchases")
    supplier_snapshot = models.JSONField(default=dict, blank=True)
    warehouse_snapshot = models.JSONField(default=dict, blank=True)
    supplier_invoice_number = models.CharField(max_length=100, blank=True)
    supplier_invoice_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    taxable_total = models.BigIntegerField(default=0)
    gst_total = models.BigIntegerField(default=0)
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tds_total = models.BigIntegerField(default=0)
    grand_total = models.BigIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.purchase_number


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("Product", on_delete=models.PROTECT, related_name="purchase_items")
    product_snapshot = models.JSONField(default=dict, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.BigIntegerField()
    hsn_code = models.CharField(max_length=20, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.BigIntegerField()


class StockLedger(models.Model):
    MOVEMENT_TYPES = [
        ("opening", "Opening"),
        ("purchase", "Purchase"),
        ("sale", "Sale"),
        ("sales_return", "Sales return"),
        ("purchase_return", "Purchase return"),
        ("adjustment", "Adjustment"),
    ]
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_movements")
    product = models.ForeignKey("Product", on_delete=models.PROTECT, related_name="stock_movements")
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.BigIntegerField(default=0)
    reference_type = models.CharField(max_length=30, blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]


class SalesReturn(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_number = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey("Order", on_delete=models.PROTECT, related_name="sales_returns")
    source_snapshot = models.JSONField(default=dict, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="sales_returns")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    taxable_total = models.BigIntegerField(default=0)
    gst_total = models.BigIntegerField(default=0)
    grand_total = models.BigIntegerField(default=0)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SalesReturnItem(models.Model):
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("Product", on_delete=models.PROTECT)
    product_snapshot = models.JSONField(default=dict, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.BigIntegerField()
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.BigIntegerField()


class PurchaseReturn(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_number = models.CharField(max_length=50, unique=True)
    purchase = models.ForeignKey("Purchase", on_delete=models.PROTECT, related_name="purchase_returns")
    source_snapshot = models.JSONField(default=dict, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchase_returns")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    taxable_total = models.BigIntegerField(default=0)
    gst_total = models.BigIntegerField(default=0)
    grand_total = models.BigIntegerField(default=0)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PurchaseReturnItem(models.Model):
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("Product", on_delete=models.PROTECT)
    product_snapshot = models.JSONField(default=dict, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.BigIntegerField()
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.BigIntegerField()


class DistributorProfile(models.Model):
    legal_name = models.CharField(max_length=200, default="Asaan Distributor")
    gstin = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    invoice_prefix = models.CharField(max_length=10, default="INV")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.legal_name


class InvoiceSequence(models.Model):
    prefix = models.CharField(max_length=10)
    financial_year = models.CharField(max_length=9)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "financial_year"],
                name="unique_invoice_sequence_year",
            )
        ]

    def __str__(self):
        return f"{self.prefix}/{self.financial_year}"


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    simple_name = models.CharField(max_length=255, blank=True)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    hsn = models.ForeignKey(HSN, on_delete=models.PROTECT, null=True, blank=True, related_name="products")
    hsn_code = models.CharField(max_length=20, blank=True)
    packing = models.CharField(max_length=150)
    unit = models.CharField(max_length=50, default="case")
    rate = models.BigIntegerField()
    mrp = models.BigIntegerField()
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    scheme_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Trade scheme shown to shops, e.g. 10 for 10% off. Applied on the Marg bill.",
    )
    image = models.ImageField(upload_to="products/", blank=True)
    image_url = models.URLField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company__name", "brand__name", "name"]

    def __str__(self):
        return self.simple_name or self.name

    @property
    def retail_margin(self):
        """What the shop makes per unit when it sells at MRP."""
        return max(0, self.mrp - self.rate)

    @property
    def retail_margin_percent(self):
        if not self.mrp:
            return Decimal("0")
        return round(Decimal(self.retail_margin) / Decimal(self.mrp) * 100, 1)


class Order(models.Model):
    STATUS_CHOICES = [
        ("received", "Received"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_order_id = models.CharField(max_length=100, unique=True)
    order_number = models.CharField(max_length=50, unique=True)
    shop = models.JSONField()
    seller_snapshot = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    total = models.BigIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="received",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    customer_gstin = models.CharField(max_length=15, blank=True)
    billing_address = models.TextField(blank=True)
    place_of_supply = models.CharField(max_length=100, blank=True)
    invoice_number = models.CharField(max_length=50, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    irn = models.CharField(max_length=100, blank=True)
    ack_number = models.CharField(max_length=50, blank=True)
    ack_date = models.DateTimeField(null=True, blank=True)
    qr_code_data = models.TextField(blank=True)
    einvoice_uploaded_at = models.DateTimeField(null=True, blank=True)
    loading = models.ForeignKey(
        Loading,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    shop_record = models.ForeignKey(
        Shop,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    class Meta:
        ordering = ["-created_at"]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product_id_snapshot = models.UUIDField()
    sku = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    hsn_code = models.CharField(max_length=20, blank=True)
    unit = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    rate = models.BigIntegerField()
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    scheme_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.BigIntegerField()
