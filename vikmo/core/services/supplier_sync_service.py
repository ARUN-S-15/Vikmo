from decimal import Decimal
import re
import time
from datetime import datetime
import requests
from django.conf import settings
from django.db import transaction
from ..models import Product
from ..exceptions import SupplierUnavailableAPI

PRICE_REGEX = re.compile(r"^\d+(\.\d{1,2})?$")
MAX_ATTEMPTS = 5


def parse_iso_datetime(dt_str):
    if not dt_str:
        return datetime.min
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.min


class SupplierSyncService:

    @classmethod
    def sync(cls):
        supplier_url = getattr(settings, "SUPPLIER_API_URL", "http://127.0.0.1:8099").rstrip("/")
        api_key = getattr(settings, "SUPPLIER_API_KEY", "")

        cursor = None
        pages_fetched = 0
        requests_made = 0
        raw_items_collected = []

        # Phase 1: Fetch entire feed with pagination, rate limiting & retry handling
        while True:
            url = f"{supplier_url}/v1/products?limit=20"
            if cursor:
                url += f"&cursor={cursor}"

            headers = {"X-Api-Key": api_key}
            page_success = False
            response_json = None

            for attempt in range(1, MAX_ATTEMPTS + 1):
                requests_made += 1
                try:
                    resp = requests.get(url, headers=headers, timeout=20)
                    if resp.status_code == 200:
                        response_json = resp.json()
                        page_success = True
                        break
                    elif resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait_sec = 1.0
                        if retry_after:
                            try:
                                wait_sec = max(0.5, float(retry_after))
                            except ValueError:
                                wait_sec = 1.0
                        time.sleep(wait_sec)
                        continue
                    elif resp.status_code in (500, 502, 503, 504):
                        time.sleep(min(2.0, 0.3 * (2 ** attempt)))
                        continue
                    elif resp.status_code == 401:
                        # Bad key: fail immediately
                        raise SupplierUnavailableAPI("Invalid or missing supplier API key.")
                    else:
                        time.sleep(0.5)
                        continue
                except requests.RequestException:
                    time.sleep(min(2.0, 0.3 * (2 ** attempt)))
                    continue

            if not page_success or response_json is None:
                raise SupplierUnavailableAPI("Could not fetch the complete feed from the supplier API.")

            pages_fetched += 1
            items = response_json.get("items", [])
            raw_items_collected.extend(items)
            cursor = response_json.get("next_cursor")
            if not cursor:
                break

        # Phase 2: Validate items & separate rejected
        rejected = []
        valid_items_by_sku = {}

        for item in raw_items_collected:
            if not isinstance(item, dict):
                continue
            sku = item.get("sku")
            supplier_sku = item.get("supplier_sku") or sku or "UNKNOWN"
            price_raw = str(item.get("price", "")).strip() if item.get("price") is not None else ""

            if not sku or not str(sku).strip():
                rejected.append({"supplier_sku": supplier_sku, "reason": "missing or empty sku"})
                continue

            sku = str(sku).strip()

            if not price_raw or not PRICE_REGEX.match(price_raw):
                rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
                continue

            try:
                price_dec = Decimal(price_raw)
                if price_dec <= Decimal("0.00"):
                    rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
                    continue
            except Exception:
                rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
                continue

            # Deduplicate by latest updated_at
            item_dt = parse_iso_datetime(item.get("updated_at"))
            if sku not in valid_items_by_sku:
                valid_items_by_sku[sku] = (item_dt, item, price_dec)
            else:
                existing_dt, _, _ = valid_items_by_sku[sku]
                if item_dt > existing_dt:
                    valid_items_by_sku[sku] = (item_dt, item, price_dec)

        # Phase 3: Transactional application to database
        created_count = 0
        updated_count = 0
        unchanged_count = 0

        with transaction.atomic():
            existing_products = {
                p.sku: p
                for p in Product.objects.select_for_update().filter(sku__in=valid_items_by_sku.keys())
            }

            for sku, (_, item_data, price_dec) in valid_items_by_sku.items():
                name = str(item_data.get("name", "")).strip()
                category = str(item_data.get("category", "")).strip()
                brand = str(item_data.get("brand", "")).strip()
                vehicle_fitment = str(item_data.get("vehicle_fitment", "")).strip()
                description = str(item_data.get("description", "")).strip()

                if sku not in existing_products:
                    # Create new product with local stock 0
                    Product.objects.create(
                        sku=sku,
                        name=name,
                        category=category,
                        brand=brand,
                        vehicle_fitment=vehicle_fitment,
                        price=price_dec,
                        stock=0,
                        description=description,
                    )
                    created_count += 1
                else:
                    existing = existing_products[sku]
                    differs = (
                        existing.name != name
                        or existing.category != category
                        or existing.brand != brand
                        or existing.vehicle_fitment != vehicle_fitment
                        or existing.description != description
                        or existing.price != price_dec
                    )
                    if differs:
                        existing.name = name
                        existing.category = category
                        existing.brand = brand
                        existing.vehicle_fitment = vehicle_fitment
                        existing.description = description
                        existing.price = price_dec
                        existing.save(update_fields=[
                            "name", "category", "brand", "vehicle_fitment",
                            "description", "price", "updated_at"
                        ])
                        updated_count += 1
                    else:
                        unchanged_count += 1

        return {
            "created": created_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "rejected": rejected,
            "pages_fetched": pages_fetched,
            "requests_made": requests_made,
        }
