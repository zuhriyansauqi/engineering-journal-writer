"""GitHub API client — fetch commits, diffs, and associated PRs."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from http_client import api_request, ApiError

_token_cache: str | None = None


def reset_token_cache(value: str | None = None) -> None:
    """Reset the cached token. For testing."""
    global _token_cache
    _token_cache = value


def get_github_token() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        _token_cache = token
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        _token_cache = result.stdout.strip()
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    raise ApiError(401, "No GITHUB_TOKEN set and gh CLI not authenticated.")


def _github_api(path: str, **kwargs: Any) -> dict[str, Any] | str:
    token = get_github_token()
    headers: dict[str, str] = kwargs.pop("headers", {})
    headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com{path}" if path.startswith("/") else path
    return api_request(url, headers=headers, **kwargs)


def fetch_commit(owner: str, repo: str, sha: str) -> dict[str, object]:
    """Fetch commit metadata and diff."""
    meta = _github_api(f"/repos/{owner}/{repo}/commits/{sha}")
    diff = _github_api(
        f"/repos/{owner}/{repo}/commits/{sha}",
        accept="application/vnd.github.v3.diff",
    )
    if isinstance(meta, str):
        meta = {}
    return {
        "sha": meta.get("sha", "")[:7] if isinstance(meta.get("sha"), str) else "",
        "message": meta.get("commit", {}).get("message", ""),
        "author": meta.get("commit", {}).get("author", {}).get("name", ""),
        "date": meta.get("commit", {}).get("author", {}).get("date", ""),
        "stats": meta.get("stats", {}),
        "files": [f["filename"] for f in meta.get("files", []) if isinstance(f, dict)],
        "diff": diff,
    }


def fetch_associated_pr(owner: str, repo: str, sha: str) -> dict[str, object] | None:
    """Find the PR associated with a commit, if any."""
    try:
        resp = _github_api(f"/repos/{owner}/{repo}/commits/{sha}/pulls")
        if isinstance(resp, str):
            return None
        prs: list[dict[str, Any]] = resp  # type: ignore[assignment]
        if prs:
            pr = prs[0]
            return {
                "number": pr["number"],
                "title": pr["title"],
                "body": pr.get("body", ""),
                "url": pr["html_url"],
                "author": pr["user"]["login"],
            }
    except ApiError as e:
        print(f"Warning: could not fetch PR for {sha}: {e}", file=sys.stderr)
    return None


def _fetch_one(owner: str, repo: str, sha: str) -> tuple[dict[str, object], dict[str, object] | None]:
    """Fetch commit + PR for a single SHA. Used as a thread target."""
    commit = fetch_commit(owner, repo, sha)
    pr = fetch_associated_pr(owner, repo, sha)
    return commit, pr


class FetchResult(TypedDict):
    repo: str
    commits: list[dict[str, object]]
    prs: list[dict[str, object]]


def fetch_all(repo_slug: str, shas: list[str]) -> FetchResult:
    """Fetch all commit data and associated PRs for the given repo and SHAs."""
    if "/" not in repo_slug:
        raise ValueError(f"repo must be owner/repo format, got: {repo_slug}")

    owner, repo = repo_slug.split("/", 1)
    seen_prs: dict[object, dict[str, object]] = {}

    with ThreadPoolExecutor(max_workers=min(len(shas), 4)) as pool:
        futures = [pool.submit(_fetch_one, owner, repo, sha) for sha in shas]
        results = [f.result() for f in futures]

    commits: list[dict[str, object]] = []
    for commit, pr in results:
        commits.append(commit)
        if pr and pr["number"] not in seen_prs:
            seen_prs[pr["number"]] = pr

    return {
        "repo": repo_slug,
        "commits": commits,
        "prs": list(seen_prs.values()),
    }
