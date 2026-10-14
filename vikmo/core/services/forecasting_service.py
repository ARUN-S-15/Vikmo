import csv
import math
from pathlib import Path
import pandas as pd
import numpy as np
from django.conf import settings
from ..models import Product
from ..exceptions import NotFoundAPI

BASE_DIR = Path(settings.BASE_DIR)
DATA_DIR = BASE_DIR / "data"
ML_DIR = BASE_DIR / "ml"
FORECAST_FILE = ML_DIR / "forecast.csv"


class ForecastingService:
    _forecast_cache = None
    _lead_times_cache = None
    _sigma_cache = None

    @classmethod
    def _load_forecast(cls):
        if cls._forecast_cache is None:
            forecasts = {}
            if FORECAST_FILE.exists():
                with open(FORECAST_FILE, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sku = row["sku"]
                        week = row["week_start"]
                        units = float(row["forecast_units"])
                        if sku not in forecasts:
                            forecasts[sku] = []
                        forecasts[sku].append({"week_start": week, "forecast_units": units})
            cls._forecast_cache = forecasts
        return cls._forecast_cache

    @classmethod
    def _load_lead_times(cls):
        if cls._lead_times_cache is None:
            lead_map = {}
            lead_file = DATA_DIR / "lead_times.csv"
            if lead_file.exists():
                with open(lead_file, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        lead_map[row["sku"]] = int(row["lead_time_weeks"])
            cls._lead_times_cache = lead_map
        return cls._lead_times_cache

    @classmethod
    def _load_sigmas(cls):
        """Computes sample standard deviation (ddof=1) of units_sold over
        the most recent 12 weeks of sales_history.csv for each SKU.
        """
        if cls._sigma_cache is None:
            sigma_map = {}
            sales_file = DATA_DIR / "sales_history.csv"
            if sales_file.exists():
                df = pd.read_csv(sales_file)
                df["week_start"] = pd.to_datetime(df["week_start"])
                df = df.sort_values(["sku", "week_start"])
                for sku, group in df.groupby("sku"):
                    last12 = group["units_sold"].tail(12)
                    if len(last12) > 1:
                        sigma = float(last12.std(ddof=1))
                    elif len(last12) == 1:
                        sigma = 0.0
                    else:
                        sigma = 0.0
                    sigma_map[sku] = sigma
            cls._sigma_cache = sigma_map
        return cls._sigma_cache

    @classmethod
    def get_forecast_for_sku(cls, sku: str):
        forecasts = cls._load_forecast()
        if sku not in forecasts:
            raise NotFoundAPI(f"No forecast found for SKU '{sku}'.")
        return {
            "sku": sku,
            "forecast": forecasts[sku],
        }

    @classmethod
    def get_reorder_suggestions(cls):
        forecasts = cls._load_forecast()
        lead_times = cls._load_lead_times()
        sigmas = cls._load_sigmas()

        # Query live stocks from database for all forecast SKUs
        sku_list = list(lead_times.keys())
        products = {p.sku: p.stock for p in Product.objects.filter(sku__in=sku_list)}

        results = []
        for sku in sku_list:
            L = lead_times.get(sku, 1)
            sku_forecasts = forecasts.get(sku, [])
            # lead_time_demand is sum of forecast_units for the first L forecast weeks
            lead_forecast_slice = sku_forecasts[:L]
            lead_time_demand = round(sum(item["forecast_units"] for item in lead_forecast_slice), 1)

            sigma = sigmas.get(sku, 0.0)
            safety_stock = math.ceil(1.65 * sigma * math.sqrt(L))
            reorder_point = round(lead_time_demand + safety_stock, 1)
            current_stock = products.get(sku, 0)
            reorder_qty = max(0, math.ceil(reorder_point - current_stock))

            results.append({
                "sku": sku,
                "current_stock": current_stock,
                "lead_time_weeks": L,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "reorder_qty": reorder_qty,
            })

        return {"results": results}
