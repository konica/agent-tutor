"""A token verifier for tests: tokens are whatever the test registers."""

from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier


class FakeTokenVerifier(TokenVerifier):
    def __init__(self) -> None:
        self._tokens: dict[str, Principal] = {}
        self.calls = 0

    def add(self, token: str, principal: Principal) -> None:
        self._tokens[token] = principal

    def revoke(self, token: str) -> None:
        """Like a Keycloak logout: the token stops being active."""
        self._tokens.pop(token, None)

    async def verify(self, token: str) -> Principal:
        self.calls += 1
        try:
            return self._tokens[token]
        except KeyError:
            raise UnauthenticatedError("unknown token") from None
