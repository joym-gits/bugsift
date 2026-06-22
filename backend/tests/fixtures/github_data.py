"""
GitHub API mock data and helpers for testing GitHub integrations.
Provides realistic webhook payloads and API responses.
"""

from datetime import datetime, timedelta
from typing import Any


def get_github_issue_webhook(
    action: str = "opened",
    issue_number: int = 42,
    title: str = "Test Issue",
    body: str = "Test issue body",
    owner: str = "octocat",
    repo: str = "Hello-World",
) -> dict[str, Any]:
    """Generate a realistic GitHub issue webhook payload."""
    return {
        "action": action,
        "number": issue_number,
        "issue": {
            "url": f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}",
            "id": 1296269,
            "node_id": "MDU6SXNzdWUxMjk2MjY5",
            "number": issue_number,
            "title": title,
            "user": {
                "login": "octocat",
                "id": 1,
                "node_id": "MDQ6VXNlcjE=",
                "avatar_url": "https://github.com/images/error/octocat_happy.gif",
                "type": "User",
            },
            "labels": [
                {
                    "id": 208045946,
                    "node_id": "MDU6TGFiZWwyMDgwNDU5NDY=",
                    "url": "https://api.github.com/repos/octocat/Hello-World/labels/bug",
                    "name": "bug",
                    "color": "f29513",
                    "default": True,
                }
            ],
            "state": "open",
            "assignee": None,
            "milestone": None,
            "comments": 0,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "closed_at": None,
            "body": body,
        },
        "repository": {
            "id": 1296269,
            "node_id": "MDEwOlJlcG9zaXRvcnkxMjk2MjY5",
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "owner": {
                "login": owner,
                "id": 1,
                "node_id": "MDQ6VXNlcjE=",
                "avatar_url": "https://github.com/images/error/octocat_happy.gif",
                "type": "User",
                "site_admin": False,
            },
            "private": False,
            "description": "This your first repo!",
            "fork": False,
            "url": f"https://api.github.com/repos/{owner}/{repo}",
            "html_url": f"https://github.com/{owner}/{repo}",
        },
        "sender": {
            "login": "octocat",
            "id": 1,
            "node_id": "MDQ6VXNlcjE=",
            "type": "User",
            "site_admin": False,
        },
    }


def get_github_push_webhook(
    owner: str = "octocat",
    repo: str = "Hello-World",
    ref: str = "refs/heads/main",
) -> dict[str, Any]:
    """Generate a realistic GitHub push webhook payload."""
    return {
        "ref": ref,
        "before": "9049503b47b839edf4b85a915ab9e4588e5f2eab",
        "after": "0d1a26e67d8f5eaf646eb8efac76c6639d2b4b82",
        "repository": {
            "id": 35129377,
            "node_id": "MDEwOlJlcG9zaXRvcnkzNTEyOTM3Nw==",
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "private": False,
            "owner": {
                "name": owner,
                "email": f"{owner}@example.com",
                "login": owner,
                "id": 1,
                "type": "User",
            },
            "html_url": f"https://github.com/{owner}/{repo}",
            "description": "My first repository on GitHub!",
            "url": f"https://api.github.com/repos/{owner}/{repo}",
        },
        "pusher": {
            "name": owner,
            "email": f"{owner}@example.com",
        },
        "sender": {
            "login": owner,
            "id": 1,
            "type": "User",
        },
        "created": False,
        "deleted": False,
        "forced": False,
        "base_ref": None,
        "compare": "https://github.com/octocat/Hello-World/compare/9049503b47b8...0d1a26e67d8f",
        "commits": [
            {
                "id": "0d1a26e67d8f5eaf646eb8efac76c6639d2b4b82",
                "tree_id": "f9d2a07e9488e1d8a526e6f0b760e20da6f0b6ff",
                "distinct": True,
                "message": "Update README",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "url": "https://github.com/octocat/Hello-World/commit/0d1a26e67d8f5eaf646eb8efac76c6639d2b4b82",
                "author": {
                    "name": owner,
                    "email": f"{owner}@example.com",
                    "username": owner,
                },
                "committer": {
                    "name": owner,
                    "email": f"{owner}@example.com",
                    "username": owner,
                },
                "added": [],
                "removed": [],
                "modified": ["README.md"],
            }
        ],
        "head_commit": {
            "id": "0d1a26e67d8f5eaf646eb8efac76c6639d2b4b82",
            "tree_id": "f9d2a07e9488e1d8a526e6f0b760e20da6f0b6ff",
            "message": "Update README",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "author": {
                "name": owner,
                "email": f"{owner}@example.com",
                "username": owner,
            },
            "modified": ["README.md"],
        },
    }


def get_github_issue_comment_webhook(
    action: str = "created",
    issue_number: int = 42,
    comment: str = "This is a test comment",
    owner: str = "octocat",
    repo: str = "Hello-World",
) -> dict[str, Any]:
    """Generate a realistic GitHub issue comment webhook payload."""
    return {
        "action": action,
        "issue": {
            "url": f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}",
            "id": 1296269,
            "number": issue_number,
            "title": "Spelling error in the README file",
            "body": "It looks like you accidently spelled 'commit' with two 't's.",
            "user": {
                "login": "octocat",
                "id": 1,
                "type": "User",
            },
            "labels": [],
            "state": "open",
            "comments": 0,
            "created_at": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
        "comment": {
            "url": f"https://api.github.com/repos/{owner}/{repo}/issues/comments/99262140",
            "id": 99262140,
            "user": {
                "login": "octocat",
                "id": 1,
                "type": "User",
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "body": comment,
        },
        "repository": {
            "id": 1296269,
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "owner": {
                "login": owner,
                "id": 1,
                "type": "User",
            },
        },
        "sender": {
            "login": "octocat",
            "id": 1,
            "type": "User",
        },
    }


def get_github_api_repo_response(
    owner: str = "octocat",
    repo: str = "Hello-World",
) -> dict[str, Any]:
    """Generate a realistic GitHub API GET /repos/{owner}/{repo} response."""
    return {
        "id": 1296269,
        "node_id": "MDEwOlJlcG9zaXRvcnkxMjk2MjY5",
        "name": repo,
        "full_name": f"{owner}/{repo}",
        "owner": {
            "login": owner,
            "id": 1,
            "node_id": "MDQ6VXNlcjE=",
            "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
            "type": "User",
        },
        "private": False,
        "html_url": f"https://github.com/{owner}/{repo}",
        "description": "My first repository on GitHub!",
        "fork": False,
        "created_at": "2011-01-26T19:01:12Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "pushed_at": datetime.utcnow().isoformat() + "Z",
        "language": "Python",
        "size": 180,
        "stargazers_count": 80,
        "watchers_count": 80,
        "forks_count": 9,
        "open_issues_count": 0,
        "topics": ["python", "testing"],
    }


def get_github_api_issue_response(
    issue_number: int = 42,
    owner: str = "octocat",
    repo: str = "Hello-World",
) -> dict[str, Any]:
    """Generate a realistic GitHub API GET /repos/{owner}/{repo}/issues/{number} response."""
    return {
        "id": 1296269,
        "node_id": "MDU6SXNzdWUxMjk2MjY5",
        "url": f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}",
        "number": issue_number,
        "title": "Found a bug",
        "user": {
            "login": "octocat",
            "id": 1,
            "type": "User",
        },
        "labels": [
            {
                "id": 208045946,
                "name": "bug",
                "color": "f29513",
                "default": True,
            }
        ],
        "state": "open",
        "locked": False,
        "assignee": None,
        "assignees": [],
        "milestone": None,
        "comments": 0,
        "created_at": (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "closed_at": None,
        "body": "I'm having a problem with this.",
        "reactions": {
            "url": f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/reactions",
            "+1": 0,
            "-1": 0,
            "laugh": 0,
            "hooray": 0,
            "confused": 0,
            "heart": 0,
            "rocket": 0,
            "eyes": 0,
        },
        "timeline_url": f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/timeline",
    }


def get_github_api_file_response(
    path: str = "README.md",
    content: str = "# Test Repo",
) -> dict[str, Any]:
    """Generate a realistic GitHub API GET /repos/{owner}/{repo}/contents/{path} response."""
    import base64

    encoded_content = base64.b64encode(content.encode()).decode()
    return {
        "name": path.split("/")[-1],
        "path": path,
        "sha": "abc123def456",
        "size": len(content),
        "type": "file",
        "url": f"https://api.github.com/repos/octocat/Hello-World/contents/{path}",
        "html_url": f"https://github.com/octocat/Hello-World/blob/main/{path}",
        "git_url": f"https://api.github.com/repos/octocat/Hello-World/git/blobs/abc123def456",
        "download_url": f"https://raw.githubusercontent.com/octocat/Hello-World/main/{path}",
        "content": encoded_content,
        "encoding": "base64",
    }
