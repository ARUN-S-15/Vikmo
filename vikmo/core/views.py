import json
from decimal import Decimal
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Product, Dealer, Order
from .serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductUpdateSerializer,
    DealerSerializer,
    DealerCreateSerializer,
    OrderSerializer,
)
from .exceptions import (
    NotFoundAPI,
    ValidationErrorAPI,
    DuplicateAPI,
)
from .pagination import DealerDeskPagination
from .services.order_service import OrderService
from .services.supplier_sync_service import SupplierSyncService
from .services.forecasting_service import ForecastingService
from .services.assistant_service import AssistantService


@api_view(["GET"])
def health(request):
    """GET /api/health/ -> 200 {"status": "ok"}"""
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


# ==============================================================================
# Products API
# ==============================================================================

@api_view(["GET", "POST"])
def product_list(request):
    if request.method == "GET":
        qs = Product.objects.all().order_by("sku")

        # Filters
        search = request.query_params.get("search")
        if search:
            search = search.strip()
            qs = qs.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(brand__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category.strip())

        vehicle = request.query_params.get("vehicle")
        if vehicle:
            qs = qs.filter(vehicle_fitment__icontains=vehicle.strip())

        paginator = DealerDeskPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ProductSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        raw_sku = str(request.data.get("sku", "")).strip()
        if raw_sku and Product.objects.filter(sku=raw_sku).exists():
            raise DuplicateAPI(f"Product with SKU '{raw_sku}' already exists.")

        serializer = ProductCreateSerializer(data=request.data)
        if not serializer.is_valid():
            # Check if SKU error is duplicate
            if "sku" in serializer.errors:
                err_text = str(serializer.errors["sku"][0]).lower()
                if "already exists" in err_text or "unique" in err_text:
                    raise DuplicateAPI(f"Product with SKU '{raw_sku}' already exists.")
            first_err = "Validation error"
            details = []
            for field, errs in serializer.errors.items():
                err_text = str(errs[0]) if isinstance(errs, list) else str(errs)
                details.append({"field": field, "error": err_text})
                first_err = f"{field}: {err_text}"
            raise ValidationErrorAPI(first_err, details=details)

        product = serializer.save(stock=0)
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def product_detail(request, sku):
    try:
        product = Product.objects.get(sku__iexact=sku)
    except Product.DoesNotExist:
        raise NotFoundAPI(f"Product with SKU '{sku}' not found.")

    if request.method == "GET":
        return Response(ProductSerializer(product).data, status=status.HTTP_200_OK)

    elif request.method == "PATCH":
        if "sku" in request.data and str(request.data["sku"]).strip().upper() != product.sku.upper():
            raise ValidationErrorAPI("SKU cannot be changed.")

        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        if not serializer.is_valid():
            raise ValidationErrorAPI("Invalid product update data.", details=[{"errors": serializer.errors}])

        product = serializer.save()
        return Response(ProductSerializer(product).data, status=status.HTTP_200_OK)


# ==============================================================================
# Inventory API
# ==============================================================================

@api_view(["PUT"])
def inventory_update(request, sku):
    """PUT /api/inventory/{sku}/ Body {"quantity": 25, "reason": "..."}"""
    try:
        product = Product.objects.get(sku__iexact=sku)
    except Product.DoesNotExist:
        raise NotFoundAPI(f"Product with SKU '{sku}' not found.")

    quantity = request.data.get("quantity")
    if quantity is None or not isinstance(quantity, int) or quantity < 0:
        raise ValidationErrorAPI("quantity must be an integer greater than or equal to 0.")

    product.stock = quantity
    product.save(update_fields=["stock", "updated_at"])

    return Response({"sku": product.sku, "quantity": product.stock}, status=status.HTTP_200_OK)


# ==============================================================================
# Dealers API
# ==============================================================================

@api_view(["GET", "POST"])
def dealer_list(request):
    if request.method == "GET":
        qs = Dealer.objects.all().order_by("id")
        paginator = DealerDeskPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = DealerSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        serializer = DealerCreateSerializer(data=request.data)
        if not serializer.is_valid():
            if "dealer_code" in serializer.errors:
                err_text = str(serializer.errors["dealer_code"][0])
                if "already exists" in err_text.lower() or "unique" in err_text.lower():
                    raise DuplicateAPI("dealer_code already exists.")
            raise ValidationErrorAPI("dealer_code and name are required.")

        dealer = serializer.save()
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def dealer_detail(request, pk):
    try:
        dealer = Dealer.objects.get(id=pk)
    except Dealer.DoesNotExist:
        raise NotFoundAPI(f"Dealer with id '{pk}' not found.")
    return Response(DealerSerializer(dealer).data, status=status.HTTP_200_OK)


# ==============================================================================
# Orders API
# ==============================================================================

@api_view(["GET", "POST"])
def order_list(request):
    if request.method == "GET":
        qs = Order.objects.prefetch_related("items").all().order_by("-created_at", "-id")

        dealer_id = request.query_params.get("dealer_id")
        if dealer_id:
            qs = qs.filter(dealer_id=dealer_id)

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param.strip().upper())

        paginator = DealerDeskPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        dealer_id = request.data.get("dealer_id")
        items = request.data.get("items")
        idempotency_key = request.headers.get("Idempotency-Key")

        response_data, status_code = OrderService.create_order(
            dealer_id=dealer_id,
            raw_items=items,
            idempotency_key=idempotency_key,
            raw_body=request.data,
        )
        return Response(response_data, status=status_code)


@api_view(["GET", "PUT"])
def order_detail(request, order_number):
    if request.method == "GET":
        order = OrderService.get_order_or_404(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    elif request.method == "PUT":
        items = request.data.get("items")
        order_data = OrderService.update_draft_order(order_number=order_number, raw_items=items)
        return Response(order_data, status=status.HTTP_200_OK)


@api_view(["POST"])
def order_confirm(request, order_number):
    order_data = OrderService.confirm_order(order_number)
    return Response(order_data, status=status.HTTP_200_OK)


@api_view(["POST"])
def order_dispatch(request, order_number):
    order_data = OrderService.dispatch_order(order_number)
    return Response(order_data, status=status.HTTP_200_OK)


@api_view(["POST"])
def order_deliver(request, order_number):
    order_data = OrderService.deliver_order(order_number)
    return Response(order_data, status=status.HTTP_200_OK)


@api_view(["POST"])
def order_cancel(request, order_number):
    order_data = OrderService.cancel_order(order_number)
    return Response(order_data, status=status.HTTP_200_OK)


# ==============================================================================
# Supplier Sync API
# ==============================================================================

@api_view(["POST"])
def supplier_sync(request):
    result = SupplierSyncService.sync()
    return Response(result, status=status.HTTP_200_OK)


# ==============================================================================
# Dealer Assistant API
# ==============================================================================

@api_view(["POST"])
def assistant_chat(request):
    session_id = request.data.get("session_id")
    dealer_id = request.data.get("dealer_id")
    message = request.data.get("message")

    if not session_id or not str(session_id).strip():
        raise ValidationErrorAPI("session_id is required.")
    if not message or not str(message).strip():
        raise ValidationErrorAPI("message is required.")

    result = AssistantService.chat(
        session_id=str(session_id).strip(),
        dealer_id=dealer_id,
        user_message=str(message).strip(),
    )
    return Response(result, status=status.HTTP_200_OK)


# ==============================================================================
# Forecasting & Reorder API
# ==============================================================================

@api_view(["GET"])
def forecast_detail(request, sku):
    result = ForecastingService.get_forecast_for_sku(sku)
    return Response(result, status=status.HTTP_200_OK)


@api_view(["GET"])
def reorder_suggestions(request):
    result = ForecastingService.get_reorder_suggestions()
    return Response(result, status=status.HTTP_200_OK)


def frontend_index(request):
    """Serve the single-page application dashboard."""
    return render(request, "index.html")

