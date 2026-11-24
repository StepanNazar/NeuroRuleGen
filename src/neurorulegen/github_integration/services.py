"""GitHub API integration service."""

import re
from typing import Any

import httpx

from neurorulegen.authentication_authorization.services import (
    AuthError,
    GitHubOAuthService,
)

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class GitHubServiceError(Exception):
    """Base exception for GitHub integration errors."""


class GitHubRepoNotFoundError(GitHubServiceError):
    """Raised when the repository is not found or is inaccessible."""


class GitHubAccessDeniedError(GitHubServiceError):
    """Raised when access to the GitHub repository is forbidden."""


class GitHubClient:
    """Client for querying GitHub API."""

    API_BASE_URL = "https://api.github.com"

    def __init__(self, oauth_service: GitHubOAuthService | None = None) -> None:
        self.oauth_service = oauth_service

    @staticmethod
    def parse_repo_string(repo_str: str) -> tuple[str, str]:
        """
        Parse owner and repository name from URL or 'owner/repo' format.
        Supported formats:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - http://github.com/owner/repo
        - owner/repo
        """
        clean = repo_str.strip()
        # Strip trailing slashes and .git
        clean = re.sub(r"\.git$", "", clean.rstrip("/"))
        match = re.search(r"(?:https?://github\.com/)?([^/]+)/([^/]+)$", clean)
        if not match:
            raise ValueError(
                "Invalid GitHub repository format. Expected 'owner/repo' or 'https://github.com/owner/repo'."
            )
        return match.group(1), match.group(2)

    async def get_pull_request(
        self,
        repo_str: str,
        pr_number: int,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Fetch pull request details from GitHub."""
        owner, repo = self.parse_repo_string(repo_str)
        url = f"{self.API_BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
        return await self._get_json_with_fallback(url=url, user_id=user_id, owner=owner, repo=repo)

    async def get_pull_request_diff(
        self,
        repo_str: str,
        pr_number: int,
        user_id: int | None = None,
    ) -> str:
        """Fetch raw diff of a pull request."""
        owner, repo = self.parse_repo_string(repo_str)
        url = f"{self.API_BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {
            "Accept": "application/vnd.github.v3.diff",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.oauth_service and user_id is not None:
            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await self.oauth_service._request_with_token_refresh(
                        client=client,
                        method="GET",
                        url=url,
                        user_id=user_id,
                        headers=headers,
                    )
                    if response.status_code == HTTP_OK:
                        return response.text
                except AuthError:
                    pass

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == HTTP_OK:
                    return response.text
                if response.status_code == HTTP_NOT_FOUND:
                    raise GitHubRepoNotFoundError(f"PR #{pr_number} in '{owner}/{repo}' not found.")
                if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                    raise GitHubAccessDeniedError(f"Access denied for PR #{pr_number} in '{owner}/{repo}'.")
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise GitHubServiceError(f"Failed to fetch PR diff: {e}") from e

        return ""

    async def get_pull_request_files(
        self,
        repo_str: str,
        pr_number: int,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch list of changed files in a pull request."""
        owner, repo = self.parse_repo_string(repo_str)
        url = f"{self.API_BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        res = await self._get_json_with_fallback(url=url, user_id=user_id, owner=owner, repo=repo)
        return res if isinstance(res, list) else []

    async def get_file_content(
        self,
        repo_str: str,
        path: str,
        ref: str | None = None,
        user_id: int | None = None,
    ) -> str:
        """Fetch raw content of a file in the repository at a given ref/commit."""
        owner, repo = self.parse_repo_string(repo_str)
        url = f"{self.API_BASE_URL}/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
        params = {"ref": ref} if ref else {}
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.oauth_service and user_id is not None:
            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await self.oauth_service._request_with_token_refresh(
                        client=client,
                        method="GET",
                        url=url,
                        user_id=user_id,
                        headers=headers,
                        params=params,
                    )
                    if response.status_code == HTTP_OK:
                        return response.text
                except AuthError:
                    pass

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == HTTP_OK:
                    return response.text
                if response.status_code == HTTP_NOT_FOUND:
                    raise GitHubRepoNotFoundError(f"File '{path}' not found at ref '{ref}'.")
                if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                    raise GitHubAccessDeniedError(f"Access denied for file '{path}'.")
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise GitHubServiceError(f"Failed to fetch file content: {e}") from e

        return ""

    async def _get_json_with_fallback(
        self,
        url: str,
        user_id: int | None,
        owner: str,
        repo: str,
    ) -> Any:
        if self.oauth_service and user_id is not None:
            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await self.oauth_service._request_with_token_refresh(
                        client=client,
                        method="GET",
                        url=url,
                        user_id=user_id,
                    )
                    if response.status_code == HTTP_OK:
                        return response.json()
                    if response.status_code == HTTP_NOT_FOUND:
                        raise GitHubRepoNotFoundError(
                            f"Resource at '{url}' not found or no permission."
                        )
                    if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                        raise GitHubAccessDeniedError(
                            f"Access denied for repository '{owner}/{repo}'."
                        )
                    response.raise_for_status()
                except AuthError:
                    pass

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == HTTP_OK:
                    return response.json()
                if response.status_code == HTTP_NOT_FOUND:
                    raise GitHubRepoNotFoundError(
                        f"Resource at '{url}' not found."
                    )
                if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                    raise GitHubAccessDeniedError(
                        f"Access denied or rate limit exceeded for '{owner}/{repo}'."
                    )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise GitHubServiceError(
                    f"Failed to communicate with GitHub: {e}"
                ) from e

        raise GitHubRepoNotFoundError(f"Could not resolve resource at '{url}'.")
