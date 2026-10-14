import concurrent.futures
from decimal import Decimal
from django.test import TransactionTestCase
from django.db import connection
from core.models import Product, Dealer, Order
from core.services.order_service import OrderService
from core.exceptions import InsufficientStockAPI


class ConcurrencyOversellPreventionTest(TransactionTestCase):
    """TransactionTestCase enables real database transaction testing and concurrency."""

    def setUp(self):
        self.dealer1 = Dealer.objects.create(
            dealer_code="DLR-CONC-01",
            name="Concurrent Dealer 1",
            credit_limit=Decimal("50000.00"),
        )
        self.dealer2 = Dealer.objects.create(
            dealer_code="DLR-CONC-02",
            name="Concurrent Dealer 2",
            credit_limit=Decimal("50000.00"),
        )
        # Create product with exactly 5 units in stock
        self.product = Product.objects.create(
            sku="CONC-SKU-01",
            name="Limited Edition Brake Rotor",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="Universal",
            price=Decimal("5000.00"),
            stock=5,
        )

    def test_concurrent_confirms_prevent_overselling(self):
        # Create two draft orders, each requesting 4 units (total 8 units, but only 5 available)
        order1_data, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            raw_items=[{"sku": "CONC-SKU-01", "quantity": 4}],
        )
        order2_data, _ = OrderService.create_order(
            dealer_id=self.dealer2.id,
            raw_items=[{"sku": "CONC-SKU-01", "quantity": 4}],
        )

        ord1_num = order1_data["order_number"]
        ord2_num = order2_data["order_number"]

        results = []

        def attempt_confirm(order_number):
            # Close connection so thread gets its own PostgreSQL connection
            connection.close()
            try:
                OrderService.confirm_order(order_number)
                return ("SUCCESS", order_number)
            except InsufficientStockAPI as e:
                return ("SHORTAGE", order_number, e.details)
            except Exception as e:
                return ("ERROR", type(e).__name__, str(e))
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_confirm, ord1_num)
            f2 = executor.submit(attempt_confirm, ord2_num)
            results = [f1.result(), f2.result()]

        statuses = [r[0] for r in results]
        self.assertIn("SUCCESS", statuses, "One order must succeed")
        self.assertIn("SHORTAGE", statuses, "One order must be rejected with INSUFFICIENT_STOCK")

        # Verify final stock in database is exactly 1 (5 - 4 = 1) and never negative
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1, "Stock must never be oversold; remaining stock must be 1")
