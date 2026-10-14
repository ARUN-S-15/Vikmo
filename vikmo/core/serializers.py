from decimal import Decimal
import re
from rest_framework import serializers
from .models import Product, Dealer, Order, OrderItem
from .exceptions import DuplicateAPI, ValidationErrorAPI

PRICE_DECIMAL_REGEX = re.compile(r"^\d+(\.\d{1,2})?$")


def format_money(val) -> str:
    if val is None:
        return "0.00"
    if isinstance(val, (int, float, str)):
        val = Decimal(str(val))
    return f"{val.quantize(Decimal('0.01')):.2f}"


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    stock = serializers.IntegerField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]

    def get_price(self, obj):
        return format_money(obj.price)


class ProductCreateSerializer(serializers.ModelSerializer):
    price = serializers.CharField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_sku(self, value):
        if not value or not str(value).strip():
            raise ValidationErrorAPI("SKU cannot be empty.")
        sku = str(value).strip()
        if Product.objects.filter(sku=sku).exists():
            raise DuplicateAPI(f"Product with SKU '{sku}' already exists.")
        return sku

    def validate_price(self, value):
        try:
            val_str = str(value).strip()
            if not PRICE_DECIMAL_REGEX.match(val_str):
                raise ValidationErrorAPI("Price must be a positive number with at most 2 decimal places.")
            dec = Decimal(val_str)
            if dec <= Decimal("0.00"):
                raise ValidationErrorAPI("Price must be greater than zero.")
            return dec
        except Exception as e:
            if isinstance(e, ValidationErrorAPI):
                raise
            raise ValidationErrorAPI("Invalid price format.")


class ProductUpdateSerializer(serializers.ModelSerializer):
    price = serializers.CharField(required=False)

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_price(self, value):
        try:
            val_str = str(value).strip()
            if not PRICE_DECIMAL_REGEX.match(val_str):
                raise ValidationErrorAPI("Price must be a positive number with at most 2 decimal places.")
            dec = Decimal(val_str)
            if dec <= Decimal("0.00"):
                raise ValidationErrorAPI("Price must be greater than zero.")
            return dec
        except Exception as e:
            if isinstance(e, ValidationErrorAPI):
                raise
            raise ValidationErrorAPI("Invalid price format.")


class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]

    def get_credit_limit(self, obj):
        return format_money(obj.credit_limit)


class DealerCreateSerializer(serializers.ModelSerializer):
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal("0.00"))

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]
        read_only_fields = ["id"]

    def validate_dealer_code(self, value):
        if not value or not str(value).strip():
            raise ValidationErrorAPI("dealer_code cannot be empty.")
        code = str(value).strip()
        if Dealer.objects.filter(dealer_code=code).exists():
            raise DuplicateAPI(f"Dealer with dealer_code '{code}' already exists.")
        return code


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def get_unit_price(self, obj):
        return format_money(obj.unit_price)

    def get_line_subtotal(self, obj):
        return format_money(obj.line_subtotal)

    def get_line_tax(self, obj):
        return format_money(obj.line_tax)

    def get_line_total(self, obj):
        return format_money(obj.line_total)


class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(source="dealer.id")
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]

    def get_subtotal(self, obj):
        return format_money(obj.subtotal)

    def get_tax_total(self, obj):
        return format_money(obj.tax_total)

    def get_grand_total(self, obj):
        return format_money(obj.grand_total)

    def get_created_at(self, obj):
        return obj.created_at.isoformat()

    def get_updated_at(self, obj):
        return obj.updated_at.isoformat()
