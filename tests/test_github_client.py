"""Tests for github_client module."""

from __future__ import annotations

import os
import sys
import unittest
from typing import override
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from github_client import (
    fetch_all,
    fetch_associated_pr,
    fetch_commit,
    get_github_token,
    reset_token_cache,
)
from http_client import ApiError

COMMIT_META = {
    "sha": "abc1234567890",
    "commit": {
        "message": "fix: resolve null pointer in parser",
        "author": {"name": "Dev", "date": "2026-05-01T10:00:00Z"},
    },
    "stats": {"additions": 5, "deletions": 2},
    "files": [{"filename": "src/parser.py"}],
}

COMMIT_DIFF = "diff --git a/src/parser.py b/src/parser.py\n--- a/src/parser.py\n+++ b/src/parser.py"

PR_DATA = [
    {
        "number": 42,
        "title": "Fix null pointer",
        "body": "Fixes #123",
        "html_url": "https://github.com/acme/app/pull/42",
        "user": {"login": "dev"},
    }
]


class TestGetGithubToken(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_token_cache()

    def test_from_env(self) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_test123"
        try:
            self.assertEqual(get_github_token(), "ghp_test123")
        finally:
            del os.environ["GITHUB_TOKEN"]

    @patch("github_client.subprocess.run")
    def test_from_gh_cli(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="ghp_cli_token\n")
        old = os.environ.pop("GITHUB_TOKEN", None)
        try:
            reset_token_cache()
            self.assertEqual(get_github_token(), "ghp_cli_token")
        finally:
            if old is not None:
                os.environ["GITHUB_TOKEN"] = old

    @patch("github_client.subprocess.run", side_effect=FileNotFoundError)
    def test_no_token_raises(self, _mock_run: MagicMock) -> None:
        old = os.environ.pop("GITHUB_TOKEN", None)
        try:
            reset_token_cache()
            with self.assertRaises(ApiError):
                _ = get_github_token()
        finally:
            if old is not None:
                os.environ["GITHUB_TOKEN"] = old


class TestFetchCommit(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_token_cache("test_token")

    @patch("github_client.api_request")
    def test_returns_structured_data(self, mock_req: MagicMock) -> None:
        mock_req.side_effect = [COMMIT_META, COMMIT_DIFF]
        result = fetch_commit("acme", "app", "abc1234")
        self.assertEqual(result["sha"], "abc1234")
        self.assertEqual(result["message"], "fix: resolve null pointer in parser")
        self.assertEqual(result["files"], ["src/parser.py"])
        self.assertEqual(result["diff"], COMMIT_DIFF)


class TestFetchAssociatedPr(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_token_cache("test_token")

    @patch("github_client.api_request")
    def test_returns_pr(self, mock_req: MagicMock) -> None:
        mock_req.return_value = PR_DATA
        result = fetch_associated_pr("acme", "app", "abc1234")
        assert result is not None
        self.assertEqual(result["number"], 42)
        self.assertEqual(result["title"], "Fix null pointer")

    @patch("github_client.api_request")
    def test_no_pr_returns_none(self, mock_req: MagicMock) -> None:
        mock_req.return_value = []
        result = fetch_associated_pr("acme", "app", "abc1234")
        self.assertIsNone(result)

    @patch("github_client.api_request", side_effect=ApiError(404, "Not found"))
    def test_api_error_returns_none(self, _mock_req: MagicMock) -> None:
        result = fetch_associated_pr("acme", "app", "abc1234")
        self.assertIsNone(result)


class TestFetchAll(unittest.TestCase):
    @override
    def setUp(self) -> None:
        reset_token_cache("test_token")

    @patch("github_client.fetch_associated_pr")
    @patch("github_client.fetch_commit")
    def test_aggregates_commits_and_prs(
        self, mock_commit: MagicMock, mock_pr: MagicMock
    ) -> None:
        mock_commit.return_value = {"sha": "abc1234", "message": "fix"}
        mock_pr.return_value = {"number": 42, "title": "Fix"}
        result = fetch_all("acme/app", ["abc1234"])
        self.assertEqual(result["repo"], "acme/app")
        self.assertEqual(len(result["commits"]), 1)
        self.assertEqual(len(result["prs"]), 1)

    def test_invalid_repo_slug_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ = fetch_all("noslash", ["abc"])

    @patch("github_client.fetch_associated_pr")
    @patch("github_client.fetch_commit")
    def test_deduplicates_prs(self, mock_commit: MagicMock, mock_pr: MagicMock) -> None:
        mock_commit.return_value = {"sha": "abc", "message": "fix"}
        mock_pr.return_value = {"number": 42, "title": "Fix"}
        result = fetch_all("acme/app", ["abc", "def"])
        self.assertEqual(len(result["prs"]), 1)


if __name__ == "__main__":
    _ = unittest.main()
