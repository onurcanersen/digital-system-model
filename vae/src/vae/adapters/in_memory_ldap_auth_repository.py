"""In-memory stand-in for the LDAP directory service (SRS DSM-VAE req 3):
a fixed set of users, to be replaced by a real LDAP-backed adapter later
without changing IAuthRepository's callers."""

from __future__ import annotations

from typing import Optional

from vae.domain.user import Role, User
from vae.ports.auth_repository import IAuthRepository


class InMemoryLdapAuthRepository(IAuthRepository):
    _USERS = {
        "admin": ("admin", Role.ADMIN),
        "operator": ("operator", Role.OPERATOR),
    }

    def authenticate(self, username: str, password: str) -> Optional[User]:
        entry = self._USERS.get(username)
        if entry is None or entry[0] != password:
            return None
        return User(username=username, role=entry[1])
