"""Base errors. Modules subclass these so entrypoints can map them to responses."""


class DomainError(Exception):
    """A business rule was violated."""


class NotFoundError(DomainError):
    """The entity does not exist or is not visible to the caller."""


class AccessDeniedError(DomainError):
    """The caller may not access this resource (e.g. a document they cannot read)."""
