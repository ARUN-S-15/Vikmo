from decimal import Decimal
from unittest.mock import patch, Mock
import requests
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Product
from core.services.supplier_sync_service import SupplierSyncService
from core.exceptions import SupplierUnavailableAPI


class SupplierSyncServiceTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.p1 = Product.objects.create(
            sku="SYNC-01",
            name="Existing Part",
            category="Filters",
            brand="Bosch",
            vehicle_fitment="Universal",
            price=Decimal("100.00"),
            stock=45,
            description="Old description",
        )

    @patch("requests.get")
    def test_sync_success_updates_creates_and_preserves_stock(self, mock_get):
        # Page 1 response: updates SYNC-01 price, creates SYNC-02, rejects invalid item
        resp_p1 = Mock()
        resp_p1.status_code = 200
        resp_p1.json.return_value = {
            "items": [
                {
                    "supplier_sku": "SUP-01",
                    "sku": "SYNC-01",
                    "name": "Existing Part",
                    "category": "Filters",
                    "brand": "Bosch",
                    "vehicle_fitment": "Universal",
                    "description": "Updated description",
                    "price": "120.00",
                    "supplier_stock": 900,
                    "updated_at": "2026-10-08T10:00:00Z",
                },
                {
                    "supplier_sku": "SUP-02",
                    "sku": "SYNC-02",
                    "name": "Brand New Part",
                    "category": "Brakes",
                    "brand": "Brembo",
                    "vehicle_fitment": "Universal",
                    "description": "New",
                    "price": "250.00",
                    "supplier_stock": 50,
                    "updated_at": "2026-10-08T10:00:00Z",
                },
                {
                    "supplier_sku": "SUP-BAD",
                    "sku": "",  # invalid
                    "price": "10.00",
                },
            ],
            "next_cursor": None,
        }
        mock_get.return_value = resp_p1

        result = SupplierSyncService.sync()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(len(result["rejected"]), 1)

        # Verify existing product updated price & description but stock preserved at 45!
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.price, Decimal("120.00"))
        self.assertEqual(self.p1.description, "Updated description")
        self.assertEqual(self.p1.stock, 45, "Local stock must never be modified by supplier sync")

        # Verify newly created product has local stock 0!
        p2 = Product.objects.get(sku="SYNC-02")
        self.assertEqual(p2.stock, 0, "Created product must have initial stock 0")
        self.assertEqual(p2.price, Decimal("250.00"))

    @patch("requests.get")
    def test_sync_outage_fails_and_changes_nothing(self, mock_get):
        # Mock 5 consecutive 503 errors
        resp_fail = Mock()
        resp_fail.status_code = 503
        mock_get.return_value = resp_fail

        with self.assertRaises(SupplierUnavailableAPI):
            SupplierSyncService.sync()

        # Database unchanged
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.price, Decimal("100.00"))
