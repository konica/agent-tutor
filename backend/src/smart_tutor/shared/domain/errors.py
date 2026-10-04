"""Base errors. Modules subclass these so entrypoints can map them to responses."""


class DomainError(Exception):
    """A business rule was violated."""


class NotFoundError(DomainError):
    """The entity does not exist or is not visible to the caller."""


class AccessDeniedError(DomainError):
    """The caller may not access this resource (e.g. a document they cannot read)."""


class UnauthenticatedError(Exception):
    """No valid credentials: the token is missing, inactive, for another audience, or can't be checked.

    Messages give the reason only, never the token.
    """


class IntrospectionUnavailableError(UnauthenticatedError):
    """Keycloak couldn't be asked or refused our client: a server-side problem, still a 401 for the caller."""
