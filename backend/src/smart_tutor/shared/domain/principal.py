"""The signed-in caller."""

from dataclasses import dataclass

from smart_tutor.shared.domain.ids import UserId


@dataclass(frozen=True)
class Principal:
    """Who is calling, from a token Keycloak says is active (ADR 0007). Never holds the token itself."""

    user_id: UserId
    name: str
    roles: frozenset[str]
