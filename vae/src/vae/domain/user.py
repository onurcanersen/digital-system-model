"""A vae session principal: the identity and role established on successful
authentication against the LDAP directory service (SRS DSM-VAE req 3)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(Enum):
    """The string values are part of the API/session contract (returned from
    /api/login, stored in the session), so the enum keeps exactly those values."""
    ADMIN = "admin"
    OPERATOR = "operator"


@dataclass
class User:
    username: str
    role: Role
