from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler
from django.http import Http404


class DealerDeskAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "VALIDATION_ERROR"
    default_message = "A validation error occurred."
    details = []

    def __init__(self, message=None, details=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.error_code = code
        self.message = message or self.default_message
        self.details = details if details is not None else []
        super().__init__(self.message)


class ValidationErrorAPI(DealerDeskAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "VALIDATION_ERROR"


class NotFoundAPI(DealerDeskAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    default_message = "Resource not found."


class DuplicateAPI(DealerDeskAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "DUPLICATE"
    default_message = "Resource already exists."


class InsufficientStockAPI(DealerDeskAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "INSUFFICIENT_STOCK"
    default_message = "Insufficient stock to complete order confirmation."


class InvalidTransitionAPI(DealerDeskAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "INVALID_TRANSITION"
    default_message = "Status change not allowed from the current status."


class OrderLockedAPI(DealerDeskAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "ORDER_LOCKED"
    default_message = "Editing an order is only allowed while DRAFT."


class IdempotencyConflictAPI(DealerDeskAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "IDEMPOTENCY_CONFLICT"
    default_message = "Idempotency key reused with a different request body."


class SupplierUnavailableAPI(DealerDeskAPIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "SUPPLIER_UNAVAILABLE"
    default_message = "Supplier API could not be synchronized."


def dealerdesk_exception_handler(exc, context):
    """Formats all exceptions into the contract shape:
    {"error": {"code": "...", "message": "...", "details": []}}
    """
    if isinstance(exc, DealerDeskAPIException):
        return Response(
            {
                "error": {
                    "code": exc.error_code,
                    "message": str(exc.message),
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, Http404):
        return Response(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(exc) if str(exc) else "Not found.",
                    "details": [],
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    response = exception_handler(exc, context)
    if response is not None:
        # Determine code based on HTTP status
        code = "VALIDATION_ERROR"
        if response.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
        elif response.status_code == status.HTTP_409_CONFLICT:
            code = "CONFLICT"

        # Flatten message from response.data
        msg = "Request error."
        details = []
        if isinstance(response.data, dict):
            if "detail" in response.data:
                msg = str(response.data["detail"])
            else:
                msg_parts = []
                for field, errs in response.data.items():
                    err_str = ", ".join(str(e) for e in errs) if isinstance(errs, list) else str(errs)
                    msg_parts.append(f"{field}: {err_str}")
                    details.append({"field": field, "error": err_str})
                if msg_parts:
                    msg = "; ".join(msg_parts)
        elif isinstance(response.data, list):
            msg = "; ".join(str(e) for e in response.data)

        return Response(
            {
                "error": {
                    "code": code,
                    "message": msg,
                    "details": details,
                }
            },
            status=response.status_code,
        )

    # For uncaught errors, do not expose internal tracebacks to clients
    return Response(
        {
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "details": [],
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
