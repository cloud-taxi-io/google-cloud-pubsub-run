class DomainError(Exception):
    """Base class for business-rule errors, translated to HTTP by the API layer."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ForbiddenOperationError(DomainError):
    pass
