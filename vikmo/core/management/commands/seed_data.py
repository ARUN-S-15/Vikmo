import csv
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import (
    Product,
    Dealer,
    Order,
    DailyOrderSequence,
    IdempotencyRecord,
    AssistantSession,
)


class Command(BaseCommand):
    help = "Idempotently loads catalogue.csv and dealers.csv from data/ into PostgreSQL."

    def handle(self, *args, **options):
        data_dir = Path(settings.DATA_DIR)
        catalogue_path = data_dir / "catalogue.csv"
        dealers_path = data_dir / "dealers.csv"

        if not catalogue_path.exists():
            raise CommandError(f"Required data file missing: {catalogue_path}")
        if not dealers_path.exists():
            raise CommandError(f"Required data file missing: {dealers_path}")

        self.stdout.write(f"Seeding data from {data_dir}...")

        with transaction.atomic():
            # Clean up ephemeral test orders, sequences, idempotency records and chat sessions
            Order.objects.all().delete()
            DailyOrderSequence.objects.all().delete()
            IdempotencyRecord.objects.all().delete()
            AssistantSession.objects.all().delete()

            # 1. Seed Products from catalogue.csv
            catalogue_skus = set()
            with open(catalogue_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                required_cols = {"sku", "name", "category", "brand", "vehicle_fitment", "price", "stock"}
                if not required_cols.issubset(set(reader.fieldnames or [])):
                    raise CommandError(f"catalogue.csv missing required columns: {required_cols - set(reader.fieldnames or [])}")

                for row in reader:
                    sku = row["sku"].strip()
                    if not sku:
                        continue
                    catalogue_skus.add(sku)
                    name = row["name"].strip()
                    category = row["category"].strip()
                    brand = row["brand"].strip()
                    vehicle_fitment = row["vehicle_fitment"].strip()
                    price = Decimal(row["price"].strip())
                    stock = int(row["stock"].strip())
                    description = row.get("description", "").strip()

                    Product.objects.update_or_create(
                        sku=sku,
                        defaults={
                            "name": name,
                            "category": category,
                            "brand": brand,
                            "vehicle_fitment": vehicle_fitment,
                            "price": price,
                            "stock": stock,
                            "description": description,
                        },
                    )

            # Remove any transient products created during test runs not in catalogue.csv
            Product.objects.exclude(sku__in=catalogue_skus).delete()

            # 2. Seed Dealers from dealers.csv
            dealers_codes = set()
            with open(dealers_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                required_cols = {"dealer_code", "name"}
                if not required_cols.issubset(set(reader.fieldnames or [])):
                    raise CommandError(f"dealers.csv missing required columns: {required_cols - set(reader.fieldnames or [])}")

                for row in reader:
                    dealer_code = row["dealer_code"].strip()
                    if not dealer_code:
                        continue
                    dealers_codes.add(dealer_code)
                    name = row["name"].strip()
                    city = row.get("city", "").strip()
                    phone = row.get("phone", "").strip()
                    email = row.get("email", "").strip()
                    gstin = row.get("gstin", "").strip()
                    credit_limit_str = row.get("credit_limit", "0.00").strip()
                    credit_limit = Decimal(credit_limit_str) if credit_limit_str else Decimal("0.00")

                    Dealer.objects.update_or_create(
                        dealer_code=dealer_code,
                        defaults={
                            "name": name,
                            "city": city,
                            "phone": phone,
                            "email": email,
                            "gstin": gstin,
                            "credit_limit": credit_limit,
                        },
                    )

            # Remove any transient test dealers created during smoke test runs
            Dealer.objects.exclude(dealer_code__in=dealers_codes).delete()

        total_products = Product.objects.count()
        total_dealers = Dealer.objects.count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed completed successfully! Database now contains {total_products} products and {total_dealers} dealers."
            )
        )
