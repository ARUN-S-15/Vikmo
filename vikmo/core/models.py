from decimal import Decimal
from django.db import models
from django.utils import timezone


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, db_index=True)
    brand = models.CharField(max_length=100, db_index=True)
    vehicle_fitment = models.CharField(max_length=255, db_index=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.IntegerField(default=0)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sku"]

    def __str__(self):
        return f"{self.sku} - {self.name}"


class Dealer(models.Model):
    dealer_code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.CharField(max_length=255, blank=True, default="")
    gstin = models.CharField(max_length=50, blank=True, default="")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.dealer_code} - {self.name}"


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(max_length=32, unique=True, db_index=True)
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    line_tax = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]
        unique_together = ("order", "sku")

    def __str__(self):
        return f"{self.order.order_number} - {self.sku} x {self.quantity}"


class DailyOrderSequence(models.Model):
    """Concurrency-safe daily sequence for ORD-YYYYMMDD-NNNN numbering."""
    order_date = models.DateField(unique=True, db_index=True)
    last_sequence = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.order_date}: {self.last_sequence}"


class IdempotencyRecord(models.Model):
    """Guarantees idempotent POST /api/orders/ creation."""
    key = models.CharField(max_length=255, unique=True, db_index=True)
    request_hash = models.CharField(max_length=64)
    response_status = models.IntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.key} ({self.response_status})"


class AssistantSession(models.Model):
    """Carries conversation memory across turns for session_id."""
    session_id = models.CharField(max_length=128, unique=True, db_index=True)
    dealer = models.ForeignKey(Dealer, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.session_id


class AssistantMessage(models.Model):
    """Message turns stored in session context."""
    session = models.ForeignKey(AssistantSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)  # user, assistant, system, tool
    content = models.TextField(blank=True, default="")
    tool_calls = models.JSONField(null=True, blank=True)
    tool_call_id = models.CharField(max_length=128, blank=True, default="")
    name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
