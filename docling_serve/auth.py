from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.security import APIKeyCookie, APIKeyHeader
from pydantic import BaseModel


class AuthenticationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    detail: Any | None = None


class KeyValidator:
    def __init__(
        self,
        api_key: str,
        field_name: str = "X-Api-Key",
        fail_on_unauthorized: bool = True,
    ) -> None:
        self.api_key = api_key
        self.field_name = field_name
        self.fail_on_unauthorized = fail_on_unauthorized

    async def __call__(self, candidate_key: str | None):
        if candidate_key is None:
            return self._error(f"Missing field {self.field_name}.")

        candidate_key = candidate_key.strip()

        # Otherwise check the apikey
        if candidate_key == self.api_key or self.api_key == "":
            return AuthenticationResult(
                valid=True,
                detail=candidate_key,  # Remove?
            )
        else:
            return self._error("The provided API Key is invalid.")

    def _error(self, error: str):
        if self.fail_on_unauthorized and self.api_key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, error)
        else:
            return AuthenticationResult(
                valid=False,
                errors=[error],
            )


class APIKeyHeaderAuth(APIKeyHeader):
    """
    FastAPI dependency which evaluates a status API Key in a header.
    """

    def __init__(self, validator: str | KeyValidator) -> None:
        self.validator = (
            KeyValidator(validator) if isinstance(validator, str) else validator
        )
        super().__init__(name=self.validator.field_name, auto_error=False)

    async def __call__(self, request: Request) -> AuthenticationResult:  # type: ignore
        key = await super().__call__(request=request)
        return await self.validator(key)


class APIKeyCookieAuth(APIKeyCookie):
    """
    FastAPI dependency which evaluates a status API Key in a cookie.
    """

    def __init__(self, validator: str | KeyValidator) -> None:
        self.validator = (
            KeyValidator(validator) if isinstance(validator, str) else validator
        )
        super().__init__(name=self.validator.field_name, auto_error=False)

    async def __call__(self, request: Request) -> AuthenticationResult:  # type: ignore
        api_key = await super().__call__(request=request)
        return await self.validator(api_key)

    def _set_api_key(self, response: Response, api_key: str, expires=24 * 3600):
        response.set_cookie(
            key=self.validator.field_name,
            value=api_key,
            expires=expires,
            secure=True,
            httponly=True,
            samesite="strict",
        )
