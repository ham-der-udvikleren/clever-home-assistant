"""Exceptions for the Clever integration."""


class CleverError(Exception):
    """Base exception for all Clever API errors."""


class CleverAuthError(CleverError):
    """Raised when login or token refresh fails (credentials invalid/revoked)."""


class CleverApiError(CleverError):
    """Raised when a Clever backend API call fails unexpectedly."""
