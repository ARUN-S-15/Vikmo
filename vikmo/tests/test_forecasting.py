import csv
import math
from pathlib import Path
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from django.conf import settings
from core.models import Product


class ForecastingAndReorderTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ml_file = Path(settings.BASE_DIR) / "ml" / "forecast.csv"

    def test_forecast_file_integrity(self):
        self.assertTrue(self.ml_file.exists(), "ml/forecast.csv must exist")
        with open(self.ml_file, mode="r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 160, "forecast.csv must contain exactly 160 rows (40 SKUs x 4 weeks)")
            self.assertEqual(list(reader[0].keys())[:3], ["sku", "week_start", "forecast_units"])
            expected_weeks = {"2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"}
            actual_weeks = {r["week_start"] for r in reader}
            self.assertEqual(actual_weeks, expected_weeks)
            for r in reader:
                val = float(r["forecast_units"])
                self.assertGreaterEqual(val, 0.0, "forecast_units must be non-negative")

    def test_forecast_sku_endpoint(self):
        # Read first SKU from forecast
        with open(self.ml_file, mode="r", encoding="utf-8") as f:
            first_sku = next(csv.DictReader(f))["sku"]

        resp = self.client.get(f"/api/forecast/{first_sku}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["sku"], first_sku)
        self.assertEqual(len(resp.data["forecast"]), 4)

        # Non-forecast SKU -> 404
        not_found_resp = self.client.get("/api/forecast/UNKNOWN-SKU/")
        self.assertEqual(not_found_resp.status_code, 404)
        self.assertEqual(not_found_resp.data["error"]["code"], "NOT_FOUND")

    def test_reorder_suggestions_formula(self):
        # Seed test product in database with live stock 20
        test_sku = "FIL-1016"  # Lead time = 3 weeks from lead_times.csv
        Product.objects.create(
            sku=test_sku,
            name="Oil Filter",
            category="Filters",
            brand="Bosch",
            vehicle_fitment="Universal",
            price=Decimal("450.00"),
            stock=20,
        )

        resp = self.client.get("/api/reorder-suggestions/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.data)
        self.assertEqual(len(resp.data["results"]), 40)

        item = next(x for x in resp.data["results"] if x["sku"] == test_sku)
        self.assertEqual(item["current_stock"], 20)
        self.assertEqual(item["lead_time_weeks"], 3)
        self.assertIn("lead_time_demand", item)
        self.assertIn("safety_stock", item)
        self.assertIn("reorder_point", item)
        self.assertIn("reorder_qty", item)

        # Verify formula: reorder_point = lead_time_demand + safety_stock
        expected_rop = round(item["lead_time_demand"] + item["safety_stock"], 1)
        self.assertAlmostEqual(item["reorder_point"], expected_rop, delta=0.2)
        # reorder_qty = max(0, ceil(reorder_point - current_stock))
        expected_qty = max(0, math.ceil(item["reorder_point"] - item["current_stock"]))
        self.assertEqual(item["reorder_qty"], expected_qty)
