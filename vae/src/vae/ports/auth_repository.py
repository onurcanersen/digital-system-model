"""Port for the LDAP directory service (SRS DSM-VAE req 3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from vae.domain.user import User


class IAuthRepository(ABC):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """The user for a valid username/password pair, or None on any
        mismatch (unknown username or wrong password — the two are not
        distinguished, so a caller can't use this to enumerate usernames)."""
