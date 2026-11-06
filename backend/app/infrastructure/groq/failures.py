"""Classify provider failures without recording messages, bodies or credentials."""

import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from groq import APIConnectionError, APITimeoutError

from app.agents.ports import ProviderFailure


def provider_failure(error) -> ProviderFailure:
    """Only connection failures and known temporary statuses merit retries."""
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    headers = response.headers if response is not None else {}
    retryable = False
    kind = "http"
    if isinstance(error, APITimeoutError) or status == 408:
        code, kind, retryable = "provider_timeout", "timeout", True
    elif isinstance(error, APIConnectionError):
        code, kind, retryable = "provider_connection_error", "connection", True
    elif status in {401, 403}:
        code = "provider_auth_error"
    elif status == 404:
        code = "provider_model_unavailable"
    elif status == 413:
        code = "request_too_large"
    elif status == 409 or (status is not None and status >= 500):
        code, retryable = "provider_unavailable", True
    elif status is not None:
        code = "provider_invalid_request"
    else:
        code, kind = "provider_api_error", "api"
    details = {"failure_type": kind}
    if status is not None:
        details["http_status"] = status
    request_id = headers.get("x-request-id", "")
    if (
        re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id)
        and not request_id.startswith("gsk_")
    ):
        details["request_id"] = request_id
    if headers.get("x-should-retry") == "false":
        retryable = False
    return ProviderFailure(code, details, retryable)


def provider_retry_delay(error, retry_number: int) -> int:
    """Respect Retry-After seconds or HTTP dates within the bounded retry policy."""
    response = getattr(error, "response", None)
    raw = response.headers.get("retry-after") if response is not None else None
    try:
        seconds = float(raw) if raw is not None else 0
    except ValueError:
        try:
            deadline = parsedate_to_datetime(raw)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 0
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0
    return max(2 ** retry_number, math.ceil(seconds))
