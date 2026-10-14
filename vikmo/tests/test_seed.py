import os
from decimal import Decimal
from django.test import TestCase
from django.core.management import call_command
from core.models import Product, Dealer, Order, DailyOrderSequence, IdempotencyRecord, AssistantSession


class SeedDataIdempotencyTest(TestCase):
    def test_seed_data_idempotency_and_counts(self):
        # Run seed_data first time
        call_command("seed_data")
        prod_count_1 = Product.objects.count()
        dealer_count_1 = Dealer.objects.count()

        self.assertEqual(prod_count_1, 600, "Initial seed must yield 600 products")
        self.assertEqual(dealer_count_1, 25, "Initial seed must yield 25 dealers")

        # Run seed_data second time
        call_command("seed_data")
        prod_count_2 = Product.objects.count()
        dealer_count_2 = Dealer.objects.count()

        self.assertEqual(prod_count_2, 600, "Second seed run must not create duplicates")
        self.assertEqual(dealer_count_2, 25, "Second seed run must not create duplicates")

        # Verify initial catalogue stock is preserved
        sample_prod = Product.objects.get(sku="BDY-1001")
        self.assertEqual(sample_prod.stock, 24)
        self.assertEqual(sample_prod.price, Decimal("1239.00"))
