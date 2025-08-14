from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel


class AuthenticationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    detail: Any | None = None


class APIKeyAuth(APIKeyHeader):
    """
    FastAPI dependency which evaluates a status API Key.
    """

    def __init__(
        self,
        api_key: str,
        header_name: str = "X-Api-Key",
        fail_on_unauthorized: bool = True,
    ) -> None:
        self.api_key = api_key
        self.header_name = header_name
        super().__init__(name=self.header_name, auto_error=False)

    async def _validate_api_key(self, header_api_key: str | None):
        if header_api_key is None:
            return AuthenticationResult(
                valid=False, errors=[f"Missing header {self.header_name}."]
            )

        header_api_key = header_api_key.strip()

        # Otherwise check the apikey
        if header_api_key == self.api_key or self.api_key == "":
            return AuthenticationResult(
                valid=True,
                detail=header_api_key,
            )
        else:
            return AuthenticationResult(
                valid=False,
                errors=["The provided API Key is invalid."],
            )

    async def __call__(self, request: Request) -> AuthenticationResult:  # type: ignore
        header_api_key = await super().__call__(request=request)
        result = await self._validate_api_key(header_api_key)
        if self.api_key and not result.valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=result.detail
            )
        return result
