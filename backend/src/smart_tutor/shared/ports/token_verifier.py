"""Checks a bearer token and returns the caller (PRD §9.3, ADR 0007)."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.principal import Principal


class TokenVerifier(ABC):
    @abstractmethod
    async def verify(self, token: str) -> Principal:
        """Return the caller for an active token; raise UnauthenticatedError otherwise."""
