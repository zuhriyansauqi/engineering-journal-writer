"""Shared HTTP helpers with structured error handling."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

API_TIMEOUT = 30

_rate_limit_remaining: int | None = None
_rate_limit_reset: float | None = None


def check_rate_limit() -> None:
    """Sleep until reset if we know we're nearly out of requests."""
    global _rate_limit_remaining, _rate_limit_reset
    if _rate_limit_remaining is not None and _rate_limit_remaining <= 1 and _rate_limit_reset:
        wait = max(0.0, _rate_limit_reset - time.time()) + 1
        print(f"Rate limit nearly exhausted, waiting {wait:.0f}s until reset.", file=sys.stderr)
        time.sleep(wait)


def update_rate_limit(headers: Message) -> None:
    """Track rate limit state from response headers."""
    global _rate_limit_remaining, _rate_limit_reset
    remaining = headers.get("X-RateLimit-Remaining")
    reset = headers.get("X-RateLimit-Reset")
    if remaining is not None:
        _rate_limit_remaining = int(remaining)
    if reset is not None:
        _rate_limit_reset = int(reset)


def reset_rate_limit_state() -> None:
    """Reset rate limit tracking. For testing."""
    global _rate_limit_remaining, _rate_limit_reset
    _rate_limit_remaining = None
    _rate_limit_reset = None


def set_rate_limit_state(remaining: int | None, reset: float | None) -> None:
    """Set rate limit tracking values. For testing."""
    global _rate_limit_remaining, _rate_limit_reset
    _rate_limit_remaining = remaining
    _rate_limit_reset = reset


class ApiError(Exception):
    """Raised on non-retryable API failures."""

    def __init__(self, status: int, message: str, url: str = "") -> None:
        self.status = status
        self.message = message
        self.url = url
        super().__init__(f"HTTP {status}: {message}")


def api_request(
    url: str,
    method: str = "GET",
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    accept: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any] | str:
    if headers is None:
        headers = {}
    headers.setdefault("User-Agent", "hermes-engineering-journal")
    if accept:
        headers["Accept"] = accept
    if body is not None:
        headers["Content-Type"] = "application/json"

    check_rate_limit()

    for attempt in range(max_retries):
        try:
            data = json.dumps(body).encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                update_rate_limit(resp.headers)
                raw = resp.read().decode()
                if accept == "application/vnd.github.v3.diff":
                    return raw
                result: dict[str, Any] = json.loads(raw) if raw else {}
                return result
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            is_secondary_rate_limit = e.code == 403 and e.headers.get("Retry-After")
            if attempt < max_retries - 1 and (e.code in (429, 502, 503) or is_secondary_rate_limit):
                retry_after = e.headers.get("Retry-After")
                delay = int(retry_after) if retry_after else (attempt + 1) * 2
                print(f"Retrying {url} (HTTP {e.code}, attempt {attempt + 1}/{max_retries})...", file=sys.stderr)
                time.sleep(delay)
                continue
            raise classify_error(e.code, err_body, url) from e
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            raise ApiError(0, f"Network error: {e.reason}", url) from e

    raise ApiError(0, f"Request failed after {max_retries} retries", url)


def classify_error(status: int, body: str, url: str) -> ApiError:
    messages: dict[int, str] = {
        401: "Authentication failed — check your token.",
        403: f"Forbidden — token lacks required permissions or rate limit exceeded. {body}",
        404: f"Not found: {url}",
        422: f"Validation error: {body}",
    }
    return ApiError(status, messages.get(status, f"API error: {body}"), url)
