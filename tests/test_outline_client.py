"""Tests for outline_client module."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import override
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from http_client import ApiError
from outline_client import publish


def _write_journal(tmp: str, title: str = "Test Entry", body: str = "# Content") -> str:
    path = os.path.join(tmp, "journal.json")
    with open(path, "w") as f:
        json.dump({"title": title, "body": body}, f)
    return path


class TestPublishDryRun(unittest.TestCase):
    def test_dry_run_skips_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_journal(tmp)
            result = publish(path, dry_run=True)
        self.assertEqual(result["action"], "dry-run")
        self.assertEqual(result["title"], "Test Entry")
        self.assertEqual(result["body_length"], len("# Content"))


class TestPublishMissingConfig(unittest.TestCase):
    def test_missing_token_raises(self) -> None:
        old_token = os.environ.pop("OUTLINE_API_TOKEN", None)
        old_coll = os.environ.pop("OUTLINE_COLLECTION_ID", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = _write_journal(tmp)
                with self.assertRaises(ApiError) as ctx:
                    publish(path)
                self.assertIn("OUTLINE_API_TOKEN", ctx.exception.message)
        finally:
            if old_token is not None:
                os.environ["OUTLINE_API_TOKEN"] = old_token
            if old_coll is not None:
                os.environ["OUTLINE_COLLECTION_ID"] = old_coll

    def test_missing_collection_raises(self) -> None:
        old_coll = os.environ.pop("OUTLINE_COLLECTION_ID", None)
        os.environ["OUTLINE_API_TOKEN"] = "tok"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = _write_journal(tmp)
                with self.assertRaises(ApiError) as ctx:
                    publish(path)
                self.assertIn("OUTLINE_COLLECTION_ID", ctx.exception.message)
        finally:
            del os.environ["OUTLINE_API_TOKEN"]
            if old_coll is not None:
                os.environ["OUTLINE_COLLECTION_ID"] = old_coll


class TestPublishCreate(unittest.TestCase):
    @override
    def setUp(self) -> None:
        os.environ["OUTLINE_URL"] = "https://outline.test"
        os.environ["OUTLINE_API_TOKEN"] = "tok"
        os.environ["OUTLINE_COLLECTION_ID"] = "col-123"

    @override
    def tearDown(self) -> None:
        os.environ.pop("OUTLINE_URL", None)
        os.environ.pop("OUTLINE_API_TOKEN", None)
        os.environ.pop("OUTLINE_COLLECTION_ID", None)

    @patch("outline_client.api_request")
    def test_creates_new_document(self, mock_req: MagicMock) -> None:
        mock_req.side_effect = [
            {"data": []},
            {"data": {"id": "doc-1", "url": "https://outline.test/doc/doc-1"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_journal(tmp)
            result = publish(path)
        self.assertEqual(result["action"], "created")


class TestPublishUpdate(unittest.TestCase):
    @override
    def setUp(self) -> None:
        os.environ["OUTLINE_URL"] = "https://outline.test"
        os.environ["OUTLINE_API_TOKEN"] = "tok"
        os.environ["OUTLINE_COLLECTION_ID"] = "col-123"

    @override
    def tearDown(self) -> None:
        os.environ.pop("OUTLINE_URL", None)
        os.environ.pop("OUTLINE_API_TOKEN", None)
        os.environ.pop("OUTLINE_COLLECTION_ID", None)

    @patch("outline_client.api_request")
    def test_updates_existing_document(self, mock_req: MagicMock) -> None:
        mock_req.side_effect = [
            {"data": [{"document": {"id": "doc-1", "title": "Test Entry"}}]},
            {"data": {"id": "doc-1", "url": "https://outline.test/doc/doc-1"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_journal(tmp)
            result = publish(path)
        self.assertEqual(result["action"], "updated")


if __name__ == "__main__":
    _ = unittest.main()
