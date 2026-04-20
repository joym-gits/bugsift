"""Role-based access control.

Three roles, ranked by privilege — each role implicitly grants every
privilege of the roles below it:

- ``admin``: everything. Manages users, rotates keys, registers or
  deletes GitHub Apps, deletes ticket/Slack destinations, reads the
  audit log. The operator who stood the deployment up is admin.
- ``triager``: the day-to-day user. Approves, skips, edits, and
  reruns triage cards; manages their own LLM API keys; creates
  feedback apps; adds Slack / ticket destinations. Cannot promote
  users or delete the GitHub App.
- ``viewer``: read-only. Can see the queue and history but can't
  take action on cards or change configuration. Useful for
  executives, support, or security reviewers.

Gates are enforced at the FastAPI route level via the
:func:`require_role` dependency. Data-level isolation (user→data
scoping) stays on top — RBAC and tenancy are independent.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, status

from bugsift.api.deps import get_current_user
from bugsift.db.models import User


class Role(str, Enum):
    admin = "admin"
    triager = "triager"
    viewer = "viewer"

    @classmethod
    def parse(cls, raw: str) -> "Role":
        try:
            return cls(raw)
        except ValueError:
            # Unknown role stored in DB (e.g. after a downgrade). Treat
            # as the least-privileged role so we fail safe.
            return cls.viewer


# Privilege ordering — higher value = more privilege. "require admin"
# is satisfied by admin only; "require triager" is satisfied by admin
# or triager; "require viewer" is satisfied by anyone.
_LEVEL: dict[Role, int] = {
    Role.viewer: 0,
    Role.triager: 1,
    Role.admin: 2,
}


def has_at_least(user: User, needed: Role) -> bool:
    """True if ``user`` holds ``needed`` or a higher-privileged role."""
    current = Role.parse(user.role)
    return _LEVEL[current] >= _LEVEL[needed]


def require_role(needed: Role) -> Callable[..., User]:
    """FastAPI dependency factory. Use as::

        @router.post("/keys", dependencies=[Depends(require_role(Role.triager))])

    or pull the user out by using it as the value dep::

        def handler(user: User = Depends(require_role(Role.admin))): ...
    """

    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_at_least(user, needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires the {needed.value} role; your "
                    f"account is {user.role}."
                ),
            )
        return user

    return _dep
