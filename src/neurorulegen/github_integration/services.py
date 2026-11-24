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

    async def get_repository_details(
        self,
        repo_str: str,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Fetch repository details from GitHub API.
        Attempts authenticated request first if user_id is provided, otherwise falls back to public request.
        """
        owner, repo = self.parse_repo_string(repo_str)
        url = f"{self.API_BASE_URL}/repos/{owner}/{repo}"

        if self.oauth_service and user_id is not None:
            async with httpx.AsyncClient(timeout=10.0) as client:
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
                            f"Repository '{owner}/{repo}' not found on GitHub or you do not have permission to access it."
                        )
                    if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                        raise GitHubAccessDeniedError(
                            f"Access denied for repository '{owner}/{repo}'. Check permissions."
                        )
                    response.raise_for_status()
                except AuthError:
                    # User might not have a GitHub token connected; try public lookup
                    pass

        # Try unauthenticated / public request
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == HTTP_OK:
                    return response.json()
                if response.status_code == HTTP_NOT_FOUND:
                    raise GitHubRepoNotFoundError(
                        f"Repository '{owner}/{repo}' not found or is private. If it is private, please connect your GitHub account in your Profile first."
                    )
                if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                    raise GitHubAccessDeniedError(
                        f"Access denied or rate limit exceeded while querying '{owner}/{repo}'. Please connect your GitHub account."
                    )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise GitHubServiceError(
                    f"Failed to communicate with GitHub: {e}"
                ) from e

        raise GitHubRepoNotFoundError(
            f"Repository '{owner}/{repo}' could not be resolved."
        )
