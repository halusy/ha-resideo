"""Exceptions raised by aioresideo."""

from __future__ import annotations

from typing import Any


class ResideoError(Exception):
    """Base error for all aioresideo failures."""


class ResideoAuthError(ResideoError):
    """Authentication / token failure (HTTP 401, invalid credentials, expired refresh token).

    Carries the failing ``step`` of the Auth0 flow, the HTTP ``status``, and the normalized
    Auth0 error ``code`` (e.g. ``invalid_captcha``) when the response supplied one, so callers
    can tell "wrong password" apart from "the flow itself broke".
    """

    def __init__(
        self,
        message: str,
        *,
        step: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.status = status
        self.code = code


class ResideoConnectionError(ResideoError):
    """Network/transport error talking to api.resideo.com (timeouts, DNS, TLS, ...)."""


class ResideoApiError(ResideoError):
    """A non-2xx API response that is not an authentication failure.

    Carries the HTTP ``status`` and parsed ``body`` (when available) for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
