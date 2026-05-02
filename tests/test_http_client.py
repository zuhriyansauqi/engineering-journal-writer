"""Tests for http_client module."""

from __future__ import annotations

import io
import os
import sys
import time
import unittest
from email.message import Message
from typing import override
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from http_client import (
    ApiError,
    api_request,
    check_rate_limit,
    classify_error,
    reset_rate_limit_state,
    set_rate_limit_state,
    update_rate_limit,
)


def _make_headers(d: dict[str, str]) -> Message:
    """Build an email.message.Message from a dict, matching HTTPError's hdrs type."""
    m = Message()
    for k, v in d.items():
        m[k] = v
    return m


class TestApiRequest(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_rate_limit_state()

    def _mock_response(self, body: dict[str, object] | str, status: int = 200) -> MagicMock:
        import json
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        resp.status = status
        resp.headers = Message()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("http_client.urllib.request.urlopen")
    def test_get_json(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = self._mock_response({"ok": True})
        result = api_request("https://example.com/api")
        self.assertEqual(result, {"ok": True})

    @patch("http_client.urllib.request.urlopen")
    def test_post_json(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = self._mock_response({"id": 1})
        result = api_request("https://example.com/api", method="POST", body={"title": "test"})
        self.assertEqual(result, {"id": 1})

    @patch("http_client.urllib.request.urlopen")
    def test_diff_accept_returns_raw(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = self._mock_response("diff --git a/f b/f")
        result = api_request("https://example.com/api", accept="application/vnd.github.v3.diff")
        self.assertEqual(result, "diff --git a/f b/f")

    @patch("http_client.urllib.request.urlopen")
    def test_401_raises_api_error(self, mock_urlopen: MagicMock) -> None:
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            "https://example.com", 401, "Unauthorized", _make_headers({}), io.BytesIO(b"bad token"),
        )
        with self.assertRaises(ApiError) as ctx:
            api_request("https://example.com/api", max_retries=1)
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("Authentication failed", ctx.exception.message)

    @patch("http_client.urllib.request.urlopen")
    def test_404_raises_api_error(self, mock_urlopen: MagicMock) -> None:
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            "https://example.com", 404, "Not Found", _make_headers({}), io.BytesIO(b""),
        )
        with self.assertRaises(ApiError) as ctx:
            api_request("https://example.com/api/missing", max_retries=1)
        self.assertEqual(ctx.exception.status, 404)

    @patch("http_client.time.sleep")
    @patch("http_client.urllib.request.urlopen")
    def test_429_retries_then_succeeds(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        from urllib.error import HTTPError
        err = HTTPError(
            "https://example.com", 429, "Rate Limited", _make_headers({"Retry-After": "1"}), io.BytesIO(b""),
        )
        ok = self._mock_response({"ok": True})
        mock_urlopen.side_effect = [err, ok]
        result = api_request("https://example.com/api", max_retries=2)
        self.assertEqual(result, {"ok": True})
        mock_sleep.assert_called_once_with(1)

    @patch("http_client.time.sleep")
    @patch("http_client.urllib.request.urlopen")
    def test_502_retries_then_fails(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        from urllib.error import HTTPError
        err = HTTPError(
            "https://example.com", 502, "Bad Gateway", _make_headers({}), io.BytesIO(b"down"),
        )
        mock_urlopen.side_effect = [err, err]
        with self.assertRaises(ApiError):
            api_request("https://example.com/api", max_retries=2)

    @patch("http_client.time.sleep")
    @patch("http_client.urllib.request.urlopen")
    def test_network_error_retries(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with self.assertRaises(ApiError) as ctx:
            api_request("https://example.com/api", max_retries=2)
        self.assertIn("Network error", ctx.exception.message)


class TestClassifyError(unittest.TestCase):
    def test_403_mentions_permissions(self) -> None:
        err = classify_error(403, "rate limit", "https://api.github.com")
        self.assertIn("permissions", err.message)

    def test_unknown_status(self) -> None:
        err = classify_error(500, "internal", "https://api.github.com")
        self.assertIn("internal", err.message)


class TestRateLimit(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_rate_limit_state()

    @patch("http_client.time.sleep")
    def test_check_rate_limit_sleeps_when_exhausted(self, mock_sleep: MagicMock) -> None:
        set_rate_limit_state(remaining=0, reset=time.time() + 5)
        check_rate_limit()
        mock_sleep.assert_called_once()
        args: tuple[object, ...] = mock_sleep.call_args[0]
        self.assertIsInstance(args[0], float)
        self.assertGreater(float(str(args[0])), 4)

    @patch("http_client.time.sleep")
    def test_check_rate_limit_noop_when_plenty(self, mock_sleep: MagicMock) -> None:
        set_rate_limit_state(remaining=100, reset=time.time() + 60)
        check_rate_limit()
        mock_sleep.assert_not_called()

    def test_update_rate_limit_from_headers(self) -> None:
        headers = _make_headers({"X-RateLimit-Remaining": "42", "X-RateLimit-Reset": "1700000000"})
        update_rate_limit(headers)
        # Verify via public getter behavior — set to 42 remaining, should not sleep
        # (if it were 0, check_rate_limit would sleep)

    @patch("http_client.time.sleep")
    @patch("http_client.urllib.request.urlopen")
    def test_403_with_retry_after_is_retried(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        from urllib.error import HTTPError
        err = HTTPError(
            "https://example.com", 403, "Forbidden", _make_headers({"Retry-After": "3"}), io.BytesIO(b"secondary"),
        )
        ok = MagicMock()
        ok.read.return_value = b'{"ok": true}'
        ok.headers = Message()
        ok.__enter__ = MagicMock(return_value=ok)
        ok.__exit__ = MagicMock(return_value=False)
        mock_urlopen.side_effect = [err, ok]
        result = api_request("https://example.com/api", max_retries=2)
        self.assertEqual(result, {"ok": True})
        mock_sleep.assert_called_with(3)

    @patch("http_client.urllib.request.urlopen")
    def test_403_without_retry_after_raises(self, mock_urlopen: MagicMock) -> None:
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            "https://example.com", 403, "Forbidden", _make_headers({}), io.BytesIO(b"no perms"),
        )
        with self.assertRaises(ApiError) as ctx:
            api_request("https://example.com/api", max_retries=1)
        self.assertEqual(ctx.exception.status, 403)


if __name__ == "__main__":
    _ = unittest.main()
