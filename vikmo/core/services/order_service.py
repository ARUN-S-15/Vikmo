from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from ..models import Product, Dealer, Order, OrderItem, DailyOrderSequence, IdempotencyRecord
from ..exceptions import (
    ValidationErrorAPI,
    NotFoundAPI,
    InsufficientStockAPI,
    InvalidTransitionAPI,
    OrderLockedAPI,
    IdempotencyConflictAPI,
)
from ..serializers import OrderSerializer

TAX_RATE = Decimal("0.18")
TWO_DECIMALS = Decimal("0.01")
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def quantize_money(amount: Decimal) -> Decimal:
    return amount.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)


def calculate_line_amounts(unit_price: Decimal, quantity: int):
    line_subtotal = quantize_money(unit_price * quantity)
    line_tax = quantize_money(line_subtotal * TAX_RATE)
    line_total = quantize_money(line_subtotal + line_tax)
    return line_subtotal, line_tax, line_total


def compute_request_hash(data) -> str:
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class OrderService:

    @classmethod
    def get_order_or_404(cls, order_number: str) -> Order:
        try:
            return Order.objects.prefetch_related("items").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundAPI(f"Order '{order_number}' not found.")

    @classmethod
    def create_order(cls, dealer_id, raw_items, idempotency_key=None, raw_body=None):
        # 1. Dealer existence validation
        try:
            dealer = Dealer.objects.get(id=dealer_id)
        except (Dealer.DoesNotExist, ValueError, TypeError):
            raise ValidationErrorAPI("Dealer does not exist.")

        # 2. Items validation
        if not raw_items or not isinstance(raw_items, list) or len(raw_items) == 0:
            raise ValidationErrorAPI("An order must contain at least one item.")

        seen_skus = set()
        validated_items = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValidationErrorAPI("Each item must be an object.")
            sku = item.get("sku")
            quantity = item.get("quantity")
            if not sku or not str(sku).strip():
                raise ValidationErrorAPI("Every item must have a valid SKU.")
            sku = str(sku).strip()
            if sku in seen_skus:
                raise ValidationErrorAPI(f"Duplicate SKU '{sku}' within order.")
            seen_skus.add(sku)

            if quantity is None or not isinstance(quantity, int) or quantity < 1:
                raise ValidationErrorAPI(f"Quantity for SKU '{sku}' must be an integer greater than or equal to 1.")

            validated_items.append({"sku": sku, "quantity": quantity})

        # 3. Product existence validation
        products_by_sku = {p.sku: p for p in Product.objects.filter(sku__in=seen_skus)}
        for item in validated_items:
            sku = item["sku"]
            if sku not in products_by_sku:
                raise ValidationErrorAPI(f"Product with SKU '{sku}' does not exist.")
            item["product"] = products_by_sku[sku]

        request_hash = compute_request_hash(raw_body) if raw_body is not None else ""

        with transaction.atomic():
            # Check Idempotency-Key
            if idempotency_key:
                record = IdempotencyRecord.objects.select_for_update().filter(key=idempotency_key).first()
                if record:
                    if record.request_hash == request_hash:
                        return record.response_body, record.response_status
                    else:
                        raise IdempotencyConflictAPI("Idempotency-Key already used with a different request body.")

            # Concurrency-safe order numbering in Asia/Kolkata
            now_kolkata = timezone.now().astimezone(KOLKATA_TZ)
            today_date = now_kolkata.date()

            seq_obj, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
                order_date=today_date,
                defaults={"last_sequence": 0},
            )
            seq_obj.last_sequence += 1
            seq_obj.save(update_fields=["last_sequence"])

            order_number = f"ORD-{today_date.strftime('%Y%m%d')}-{seq_obj.last_sequence:04d}"

            # Compute totals at current catalogue price
            subtotal = Decimal("0.00")
            tax_total = Decimal("0.00")
            items_to_create = []

            order = Order.objects.create(
                order_number=order_number,
                dealer=dealer,
                status=Order.Status.DRAFT,
                subtotal=subtotal,
                tax_total=tax_total,
                grand_total=Decimal("0.00"),
                created_at=timezone.now(),
            )

            for item in validated_items:
                product = item["product"]
                qty = item["quantity"]
                unit_price = quantize_money(product.price)
                l_subtotal, l_tax, l_total = calculate_line_amounts(unit_price, qty)
                subtotal += l_subtotal
                tax_total += l_tax

                items_to_create.append(
                    OrderItem(
                        order=order,
                        product=product,
                        sku=product.sku,
                        name=product.name,
                        quantity=qty,
                        unit_price=unit_price,
                        line_subtotal=l_subtotal,
                        line_tax=l_tax,
                        line_total=l_total,
                    )
                )

            OrderItem.objects.bulk_create(items_to_create)
            order.subtotal = quantize_money(subtotal)
            order.tax_total = quantize_money(tax_total)
            order.grand_total = quantize_money(subtotal + tax_total)
            order.save(update_fields=["subtotal", "tax_total", "grand_total"])

            response_data = OrderSerializer(order).data
            status_code = 201

            if idempotency_key:
                IdempotencyRecord.objects.create(
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=status_code,
                    response_body=response_data,
                )

            return response_data, status_code

    @classmethod
    def update_draft_order(cls, order_number: str, raw_items):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if not order:
                raise NotFoundAPI(f"Order '{order_number}' not found.")

            if order.status != Order.Status.DRAFT:
                raise OrderLockedAPI("Editing an order is only allowed while DRAFT.")

            if not raw_items or not isinstance(raw_items, list) or len(raw_items) == 0:
                raise ValidationErrorAPI("An order must contain at least one item.")

            seen_skus = set()
            validated_items = []
            for item in raw_items:
                if not isinstance(item, dict):
                    raise ValidationErrorAPI("Each item must be an object.")
                sku = item.get("sku")
                quantity = item.get("quantity")
                if not sku or not str(sku).strip():
                    raise ValidationErrorAPI("Every item must have a valid SKU.")
                sku = str(sku).strip()
                if sku in seen_skus:
                    raise ValidationErrorAPI(f"Duplicate SKU '{sku}' within order.")
                seen_skus.add(sku)

                if quantity is None or not isinstance(quantity, int) or quantity < 1:
                    raise ValidationErrorAPI(f"Quantity for SKU '{sku}' must be an integer greater than or equal to 1.")

                validated_items.append({"sku": sku, "quantity": quantity})

            products_by_sku = {p.sku: p for p in Product.objects.filter(sku__in=seen_skus)}
            for item in validated_items:
                sku = item["sku"]
                if sku not in products_by_sku:
                    raise ValidationErrorAPI(f"Product with SKU '{sku}' does not exist.")
                item["product"] = products_by_sku[sku]

            # Replace items
            order.items.all().delete()

            subtotal = Decimal("0.00")
            tax_total = Decimal("0.00")
            items_to_create = []

            for item in validated_items:
                product = item["product"]
                qty = item["quantity"]
                unit_price = quantize_money(product.price)
                l_subtotal, l_tax, l_total = calculate_line_amounts(unit_price, qty)
                subtotal += l_subtotal
                tax_total += l_tax

                items_to_create.append(
                    OrderItem(
                        order=order,
                        product=product,
                        sku=product.sku,
                        name=product.name,
                        quantity=qty,
                        unit_price=unit_price,
                        line_subtotal=l_subtotal,
                        line_tax=l_tax,
                        line_total=l_total,
                    )
                )

            OrderItem.objects.bulk_create(items_to_create)
            order.subtotal = quantize_money(subtotal)
            order.tax_total = quantize_money(tax_total)
            order.grand_total = quantize_money(subtotal + tax_total)
            order.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])

            return OrderSerializer(order).data

    @classmethod
    def confirm_order(cls, order_number: str):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if not order:
                raise NotFoundAPI(f"Order '{order_number}' not found.")

            if order.status != Order.Status.DRAFT:
                raise InvalidTransitionAPI(f"Cannot confirm order with status '{order.status}'.")

            order_items = list(order.items.select_related("product").all())
            if not order_items:
                raise ValidationErrorAPI("Order has no items to confirm.")

            # Lock products in deterministic alphabetical order by SKU to prevent deadlocks
            skus = sorted([item.sku for item in order_items])
            locked_products = {
                p.sku: p
                for p in Product.objects.select_for_update().filter(sku__in=skus).order_by("sku")
            }

            # All-or-nothing stock check
            short_details = []
            messages = []
            for item in order_items:
                product = locked_products.get(item.sku)
                if not product or product.stock < item.quantity:
                    avail = product.stock if product else 0
                    short_details.append({
                        "sku": item.sku,
                        "requested": item.quantity,
                        "available": avail,
                    })
                    prod_name = product.name if product else item.name
                    messages.append(
                        f"Insufficient stock for {prod_name}. Available: {avail}, Requested: {item.quantity}"
                    )

            if short_details:
                full_message = " ".join(messages)
                raise InsufficientStockAPI(message=full_message, details=short_details)

            # Deduct stock and lock unit price
            subtotal = Decimal("0.00")
            tax_total = Decimal("0.00")

            for item in order_items:
                product = locked_products[item.sku]
                product.stock -= item.quantity
                product.save(update_fields=["stock", "updated_at"])

                # Lock unit price to current catalogue price at confirm time
                unit_price = quantize_money(product.price)
                l_subtotal, l_tax, l_total = calculate_line_amounts(unit_price, item.quantity)
                subtotal += l_subtotal
                tax_total += l_tax

                item.unit_price = unit_price
                item.line_subtotal = l_subtotal
                item.line_tax = l_tax
                item.line_total = l_total
                item.save(update_fields=["unit_price", "line_subtotal", "line_tax", "line_total"])

            order.subtotal = quantize_money(subtotal)
            order.tax_total = quantize_money(tax_total)
            order.grand_total = quantize_money(subtotal + tax_total)
            order.status = Order.Status.CONFIRMED
            order.save(update_fields=["status", "subtotal", "tax_total", "grand_total", "updated_at"])

            return OrderSerializer(order).data

    @classmethod
    def dispatch_order(cls, order_number: str):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if not order:
                raise NotFoundAPI(f"Order '{order_number}' not found.")

            if order.status != Order.Status.CONFIRMED:
                raise InvalidTransitionAPI(f"Cannot dispatch order with status '{order.status}'.")

            order.status = Order.Status.DISPATCHED
            order.save(update_fields=["status", "updated_at"])
            return OrderSerializer(order).data

    @classmethod
    def deliver_order(cls, order_number: str):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if not order:
                raise NotFoundAPI(f"Order '{order_number}' not found.")

            if order.status != Order.Status.DISPATCHED:
                raise InvalidTransitionAPI(f"Cannot deliver order with status '{order.status}'.")

            order.status = Order.Status.DELIVERED
            order.save(update_fields=["status", "updated_at"])
            return OrderSerializer(order).data

    @classmethod
    def cancel_order(cls, order_number: str):
        with transaction.atomic():
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if not order:
                raise NotFoundAPI(f"Order '{order_number}' not found.")

            if order.status not in (Order.Status.DRAFT, Order.Status.CONFIRMED):
                raise InvalidTransitionAPI(f"Cannot cancel order with status '{order.status}'.")

            if order.status == Order.Status.CONFIRMED:
                # Restore stock exactly once
                order_items = list(order.items.all())
                skus = sorted([item.sku for item in order_items])
                locked_products = {
                    p.sku: p
                    for p in Product.objects.select_for_update().filter(sku__in=skus).order_by("sku")
                }
                for item in order_items:
                    product = locked_products.get(item.sku)
                    if product:
                        product.stock += item.quantity
                        product.save(update_fields=["stock", "updated_at"])

            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status", "updated_at"])
            return OrderSerializer(order).data
