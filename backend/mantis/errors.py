"""Domain errors raised by services and translated to HTTP responses in ``mantis.api``.

Services never import FastAPI. They raise one of these and the API layer maps each
class to a status code, so every route reports the same failure the same way.
"""

from __future__ import annotations


class MantisError(Exception):
    """Base class. ``detail`` is safe to show to the user."""

    status_code = 500

    def __init__(self, detail: str = "Request failed"):
        super().__init__(detail)
        self.detail = detail


class InvalidInput(MantisError):
    status_code = 400


class NotSignedIn(MantisError):
    status_code = 401

    def __init__(self, detail: str = "Not signed in"):
        super().__init__(detail)


class Forbidden(MantisError):
    status_code = 403


class NotFound(MantisError):
    status_code = 404


class Conflict(MantisError):
    status_code = 409


class ServiceUnavailable(MantisError):
    """A dependency (database, model provider configuration) is not usable."""

    status_code = 503


class UpstreamFailed(MantisError):
    """A third-party API answered with an error."""

    status_code = 502
