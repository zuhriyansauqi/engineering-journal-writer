#!/usr/bin/env python3
"""
Engineering Journal — CLI entry point.

Usage:
  python journal_helper.py fetch <owner/repo> <sha> [<sha2> ...]
  python journal_helper.py publish [--dry-run] <journal_json_file>
  python journal_helper.py search <title>

Requires: GITHUB_TOKEN env var or gh CLI authenticated.
         OUTLINE_API_TOKEN env var for publishing/searching.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import github_client  # noqa: E402
import http_client  # noqa: E402
import outline_client  # noqa: E402

CACHE_DIR = os.path.join(tempfile.gettempdir(), "journal_cache")


def _cache_key(repo_slug: str, shas: list[str]) -> str:
    raw = f"{repo_slug}:{','.join(shas)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cmd_fetch(repo_slug: str, shas: list[str]) -> None:
    """Fetch commit data, using cache if available."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(repo_slug, shas)
    cache_file = os.path.join(CACHE_DIR, f"{key}.json")

    if os.path.exists(cache_file):
        print(f"Using cached data from {cache_file}", file=sys.stderr)
        with open(cache_file) as f:
            print(f.read())
        return

    output = github_client.fetch_all(repo_slug, shas)
    with open(cache_file, "w") as f:
        json.dump(output, f, indent=2)
    print(json.dumps(output, indent=2))


def cmd_publish(journal_file: str, dry_run: bool = False) -> None:
    """Publish a journal entry to Outline."""
    result = outline_client.publish(journal_file, dry_run=dry_run)
    print(json.dumps(result, indent=2))


def cmd_search(title: str) -> None:
    """Search for an existing journal entry by title."""
    result = outline_client.search(title)
    print(json.dumps(result, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "fetch":
            if len(sys.argv) < 4:
                print("Usage: journal_helper.py fetch <owner/repo> <sha> [<sha2> ...]", file=sys.stderr)
                sys.exit(1)
            cmd_fetch(sys.argv[2], sys.argv[3:])
        elif cmd == "publish":
            args = sys.argv[2:]
            dry_run = "--dry-run" in args
            args = [a for a in args if a != "--dry-run"]
            if not args:
                print("Usage: journal_helper.py publish [--dry-run] <journal.json>", file=sys.stderr)
                sys.exit(1)
            cmd_publish(args[0], dry_run=dry_run)
        elif cmd == "search":
            if len(sys.argv) < 3:
                print("Usage: journal_helper.py search <title>", file=sys.stderr)
                sys.exit(1)
            cmd_search(" ".join(sys.argv[2:]))
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)
    except http_client.ApiError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
