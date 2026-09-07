"""Use case: authenticate a user against the LDAP directory service (SRS DSM-VAE req 3)."""

from __future__ import annotations

from typing import Optional

from vae.domain.user import User
from vae.ports.auth_repository import IAuthRepository


class AuthenticateUser:
    def __init__(self, auth_repo: IAuthRepository):
        self._auth_repo = auth_repo

    def execute(self, username: str, password: str) -> Optional[User]:
        return self._auth_repo.authenticate(username, password)
