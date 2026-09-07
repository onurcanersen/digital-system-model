"""Tests for the AuthenticateUser use case (SRS DSM-VAE req 3)."""

from typing import Optional

from vae.domain.user import Role, User
from vae.ports.auth_repository import IAuthRepository
from vae.services.authenticate_user import AuthenticateUser


def test_authenticate_user_delegates_to_the_given_repository():
    class _FakeAuthRepository(IAuthRepository):
        def authenticate(self, username: str, password: str) -> Optional[User]:
            if (username, password) == ("admin", "admin"):
                return User(username="admin", role=Role.ADMIN)
            return None

    service = AuthenticateUser(_FakeAuthRepository())

    assert service.execute("admin", "admin") == User(username="admin", role=Role.ADMIN)
    assert service.execute("admin", "wrong") is None
