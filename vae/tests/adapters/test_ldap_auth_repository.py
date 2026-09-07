"""Tests for LdapAuthRepository's fixed user set (SRS DSM-VAE req 3)."""

from vae.adapters.ldap_auth_repository import LdapAuthRepository
from vae.domain.user import Role, User


def test_ldap_auth_repository_accepts_admin():
    user = LdapAuthRepository().authenticate("admin", "admin")

    assert user == User(username="admin", role=Role.ADMIN)


def test_ldap_auth_repository_accepts_operator():
    user = LdapAuthRepository().authenticate("operator", "operator")

    assert user == User(username="operator", role=Role.OPERATOR)


def test_ldap_auth_repository_rejects_wrong_password():
    assert LdapAuthRepository().authenticate("admin", "wrong") is None


def test_ldap_auth_repository_rejects_unknown_username():
    assert LdapAuthRepository().authenticate("nobody", "admin") is None
