import pytest

from neurorulegen.authentication_authorization.services import (
    validate_password_policy,
)
from neurorulegen.github_integration.services import GitHubClient


@pytest.mark.parametrize(
    ("password", "expected_valid", "expected_message"),
    [
        ("Abcdef1!", True, ""),
        ("Ab1!", False, "Password must be at least 8 characters long."),
        ("ABCDEFG1!", False, "Password must contain at least one lowercase letter."),
        ("abcdefg1!", False, "Password must contain at least one uppercase letter."),
        ("Abcdefg!", False, "Password must contain at least one digit."),
        ("Abcdefg1", False, "Password must contain at least one special character."),
    ],
)
def test_validate_password_policy(password, expected_valid, expected_message):
    assert validate_password_policy(password) == (expected_valid, expected_message)


@pytest.mark.parametrize(
    ("repo_string", "expected"),
    [
        ("owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("http://github.com/owner/repo/", ("owner", "repo")),
    ],
)
def test_parse_github_repository_string(repo_string, expected):
    assert GitHubClient.parse_repo_string(repo_string) == expected
