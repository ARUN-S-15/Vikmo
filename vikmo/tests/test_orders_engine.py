from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Product, Dealer, Order, OrderItem


class OrdersEngineLifecycleTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(
            dealer_code="DLR-ORD-01",
            name="Ordering Dealer",
            credit_limit=Decimal("100000.00"),
        )
        self.p1 = Product.objects.create(
            sku="TST-BRK",
            name="Performance Brake Pads",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="Duke 390",
            price=Decimal("1000.00"),
            stock=10,
        )
        self.p2 = Product.objects.create(
            sku="TST-CHN",
            name="Chain Kit",
            category="Drivetrain",
            brand="D.I.D",
            vehicle_fitment="Duke 390",
            price=Decimal("2500.55"),
            stock=5,
        )

    def test_draft_order_creation_and_gst_calculation(self):
        # 1 unit of p1: subtotal 1000.00, 18% tax 180.00, total 1180.00
        # 2 units of p2: subtotal 5001.10, 18% tax 900.198 -> 900.20 (ROUND_HALF_UP), total 5901.30
        payload = {
            "dealer_id": self.dealer.id,
            "items": [
                {"sku": "TST-BRK", "quantity": 1},
                {"sku": "TST-CHN", "quantity": 2},
            ],
        }
        resp = self.client.post("/api/orders/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.data

        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["subtotal"], "6001.10")
        self.assertEqual(data["tax_total"], "1080.20")
        self.assertEqual(data["grand_total"], "7081.30")

        # Verify stock is NOT deducted on DRAFT creation
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.stock, 10)
        self.assertEqual(self.p2.stock, 5)

    def test_idempotency_key_replay_and_conflict(self):
        payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-BRK", "quantity": 1}],
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "KEY-ABC-123"}

        # First request
        resp1 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertEqual(resp1.status_code, 201)
        order_no_1 = resp1.data["order_number"]

        # Duplicate request with same key and same body returns original order
        resp2 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertIn(resp2.status_code, [200, 201])
        self.assertEqual(resp2.data["order_number"], order_no_1)
        self.assertEqual(Order.objects.count(), 1, "Only 1 order must exist")

        # Reusing same key with DIFFERENT body -> 409 IDEMPOTENCY_CONFLICT
        different_payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-BRK", "quantity": 2}],
        }
        conflict_resp = self.client.post("/api/orders/", different_payload, format="json", **headers)
        self.assertEqual(conflict_resp.status_code, 409)
        self.assertEqual(conflict_resp.data["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_insufficient_stock_on_confirm(self):
        # Create order requesting 15 units when stock is only 10
        payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-BRK", "quantity": 15}],
        }
        resp = self.client.post("/api/orders/", payload, format="json")
        order_no = resp.data["order_number"]

        confirm_resp = self.client.post(f"/api/orders/{order_no}/confirm/")
        self.assertEqual(confirm_resp.status_code, 409)
        self.assertEqual(confirm_resp.data["error"]["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(len(confirm_resp.data["error"]["details"]), 1)
        self.assertEqual(confirm_resp.data["error"]["details"][0]["sku"], "TST-BRK")
        self.assertEqual(confirm_resp.data["error"]["details"][0]["requested"], 15)
        self.assertEqual(confirm_resp.data["error"]["details"][0]["available"], 10)

        # Stock unchanged
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock, 10)

    def test_full_lifecycle_and_stock_restoration_on_cancel(self):
        # 1. Create order
        payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-BRK", "quantity": 3}],
        }
        resp = self.client.post("/api/orders/", payload, format="json")
        order_no = resp.data["order_number"]

        # 2. Confirm order -> stock decreases from 10 to 7
        conf_resp = self.client.post(f"/api/orders/{order_no}/confirm/")
        self.assertEqual(conf_resp.status_code, 200)
        self.assertEqual(conf_resp.data["status"], "CONFIRMED")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock, 7)

        # 3. Price lock: catalogue price change must NOT affect confirmed order
        self.p1.price = Decimal("2000.00")
        self.p1.save()
        order_detail = self.client.get(f"/api/orders/{order_no}/").data
        self.assertEqual(order_detail["items"][0]["unit_price"], "1000.00")

        # 4. Cancel confirmed order -> stock restored to 10 exactly once
        cancel_resp = self.client.post(f"/api/orders/{order_no}/cancel/")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.data["status"], "CANCELLED")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock, 10)

        # 5. Invalid transition: cannot confirm a cancelled order
        inv_resp = self.client.post(f"/api/orders/{order_no}/confirm/")
        self.assertEqual(inv_resp.status_code, 409)
        self.assertEqual(inv_resp.data["error"]["code"], "INVALID_TRANSITION")
