"""Outline API client — publish and update journal entries."""

from __future__ import annotations

import json
import os
from typing import Any, cast

from http_client import api_request, ApiError


def _get_config() -> tuple[str, str, str]:
    url = os.environ.get("OUTLINE_URL", "http://localhost:3000")
    token = os.environ.get("OUTLINE_API_TOKEN", "")
    collection_id = os.environ.get("OUTLINE_COLLECTION_ID", "")
    if not token:
        raise ApiError(401, "OUTLINE_API_TOKEN not set.")
    if not collection_id:
        raise ApiError(422, "OUTLINE_COLLECTION_ID not set.")
    return url, token, collection_id


def _outline_api(base_url: str, token: str, endpoint: str, body: dict[str, object]) -> dict[str, Any] | str:
    return api_request(
        f"{base_url}/api/{endpoint}",
        method="POST",
        body=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def _find_existing(base_url: str, token: str, collection_id: str, title: str) -> dict[str, Any] | None:
    """Search for an existing document with the exact title."""
    resp = _outline_api(base_url, token, "documents.search", {
        "query": title,
        "collectionId": collection_id,
        "limit": 5,
    })
    if isinstance(resp, str):
        return None
    data: list[dict[str, Any]] = resp.get("data", [])
    for item in data:
        raw_doc: object = item.get("document")
        if isinstance(raw_doc, dict):
            document = cast(dict[str, Any], raw_doc)
            if document.get("title") == title:
                return document
    return None


def publish(journal_file: str, dry_run: bool = False) -> dict[str, object]:
    """Publish a journal entry to Outline. Returns action result dict."""
    with open(journal_file) as f:
        journal: dict[str, Any] = json.load(f)

    title: str = journal["title"]
    body: str = journal["body"]

    if dry_run:
        return {"action": "dry-run", "title": title, "body_length": len(body)}

    base_url, token, collection_id = _get_config()

    existing = _find_existing(base_url, token, collection_id, title)

    if existing:
        resp = _outline_api(base_url, token, "documents.update", {
            "id": existing["id"],
            "text": body,
        })
        doc: dict[str, Any] = resp if isinstance(resp, dict) else {}
        return {"action": "updated", "id": doc.get("data", {}).get("id"), "url": doc.get("data", {}).get("url")}

    resp = _outline_api(base_url, token, "documents.create", {
        "title": title,
        "text": body,
        "collectionId": collection_id,
        "publish": True,
    })
    doc = resp if isinstance(resp, dict) else {}
    return {"action": "created", "id": doc.get("data", {}).get("id"), "url": doc.get("data", {}).get("url")}
