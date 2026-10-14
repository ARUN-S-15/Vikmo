from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Product, Dealer


class ProductsAndDealersAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(
            dealer_code="DLR-TEST-01",
            name="Test Dealer",
            city="Bengaluru",
            credit_limit=Decimal("50000.00"),
        )
        self.product = Product.objects.create(
            sku="TST-1001",
            name="Test Brake Pad",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="Pulsar 150",
            price=Decimal("1500.50"),
            stock=20,
            description="Test brake pad description",
        )

    def test_products_list_and_filters(self):
        resp = self.client.get("/api/products/?search=Brembo")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.data)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["sku"], "TST-1001")
        self.assertEqual(resp.data["results"][0]["price"], "1500.50")

    def test_product_create_and_duplicate(self):
        payload = {
            "sku": "TST-1002",
            "name": "New Clutch Plate",
            "category": "Transmission",
            "brand": "Exedy",
            "vehicle_fitment": "Duke 390",
            "price": "2499.00",
            "description": "High performance clutch",
        }
        resp = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["stock"], 0, "Created product must have initial stock 0")
        self.assertEqual(resp.data["price"], "2499.00")

        # Duplicate SKU -> 409 DUPLICATE
        dup_resp = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(dup_resp.status_code, 409)
        self.assertEqual(dup_resp.data["error"]["code"], "DUPLICATE")

    def test_product_price_validation(self):
        bad_price_payload = {
            "sku": "TST-9999",
            "name": "Bad Price Part",
            "category": "Engine",
            "brand": "Generic",
            "vehicle_fitment": "Universal",
            "price": "100.555",  # 3 decimals
        }
        resp = self.client.post("/api/products/", bad_price_payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"]["code"], "VALIDATION_ERROR")

    def test_inventory_update(self):
        resp = self.client.put("/api/inventory/TST-1001/", {"quantity": 85, "reason": "stock count"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["quantity"], 85)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 85)

        # Negative inventory -> 400
        bad_resp = self.client.put("/api/inventory/TST-1001/", {"quantity": -5}, format="json")
        self.assertEqual(bad_resp.status_code, 400)
        self.assertEqual(bad_resp.data["error"]["code"], "VALIDATION_ERROR")

    def test_dealers_duplicate_and_list(self):
        resp = self.client.get("/api/dealers/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)

        dup_payload = {"dealer_code": "DLR-TEST-01", "name": "Duplicate Dealer"}
        dup_resp = self.client.post("/api/dealers/", dup_payload, format="json")
        self.assertEqual(dup_resp.status_code, 409)
        self.assertEqual(dup_resp.data["error"]["code"], "DUPLICATE")
