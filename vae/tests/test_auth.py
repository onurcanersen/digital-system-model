"""Tests for VAE's auth port/adapter/service (SRS DSM-VAE req 3)."""

from typing import Optional

from vae.adapters.in_memory_ldap_auth_repository import InMemoryLdapAuthRepository
from vae.domain.user import Role, User
from vae.ports.auth_repository import IAuthRepository
from vae.services.authenticate_user import AuthenticateUser


def test_in_memory_ldap_auth_repository_accepts_admin():
    user = InMemoryLdapAuthRepository().authenticate("admin", "admin")

    assert user == User(username="admin", role=Role.ADMIN)


def test_in_memory_ldap_auth_repository_accepts_operator():
    user = InMemoryLdapAuthRepository().authenticate("operator", "operator")

    assert user == User(username="operator", role=Role.OPERATOR)


def test_in_memory_ldap_auth_repository_rejects_wrong_password():
    assert InMemoryLdapAuthRepository().authenticate("admin", "wrong") is None


def test_in_memory_ldap_auth_repository_rejects_unknown_username():
    assert InMemoryLdapAuthRepository().authenticate("nobody", "admin") is None


def test_authenticate_user_delegates_to_the_given_repository():
    class _FakeAuthRepository(IAuthRepository):
        def authenticate(self, username: str, password: str) -> Optional[User]:
            if (username, password) == ("admin", "admin"):
                return User(username="admin", role=Role.ADMIN)
            return None

    service = AuthenticateUser(_FakeAuthRepository())

    assert service.execute("admin", "admin") == User(username="admin", role=Role.ADMIN)
    assert service.execute("admin", "wrong") is None
