"""Settings that operators change without a release (SSM Parameter Store, `/smart-tutor/*`; PRD §9.12)."""

from abc import ABC, abstractmethod


class ParameterNotFoundError(Exception):
    """The named parameter doesn't exist."""


class ParameterStore(ABC):
    @abstractmethod
    def get(self, name: str) -> str:
        """The parameter's value; raises ParameterNotFoundError."""
