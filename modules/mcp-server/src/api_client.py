import logging
from typing import Any, cast

import httpx

from src.config import Settings

logger = logging.getLogger(__name__)


class ApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def ask(
        self,
        question: str,
        top_k: int,
        speaker: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question, "top_k": top_k}
        if speaker is not None:
            payload["filters"] = {"speaker": speaker}

        return await self._post("/ask", payload)

    async def list_videos(self) -> dict[str, Any]:
        return await self._get("/videos")

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.post(
                    path,
                    json=payload,
                    headers={"x-api-key": self.settings.api_key},
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {e}")
            raise RuntimeError(
                "Request timed out. The API is taking too long to respond."
            ) from e
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            if e.response.status_code == 401:
                raise RuntimeError(
                    "Authentication failed. Please check your API_KEY."
                ) from e
            elif e.response.status_code == 400:
                raise RuntimeError(
                    "Invalid request. Please check your question format."
                ) from e
            else:
                raise RuntimeError(
                    f"API error: {e.response.status_code}. Please try again later."
                ) from e
        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            raise RuntimeError(
                "Network error. Please check your internet connection."
            ) from e

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.get(
                    path,
                    headers={"x-api-key": self.settings.api_key},
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {e}")
            raise RuntimeError(
                "Request timed out. The API is taking too long to respond."
            ) from e
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e}")
            if e.response.status_code == 401:
                raise RuntimeError(
                    "Authentication failed. Please check your API_KEY."
                ) from e
            else:
                raise RuntimeError(
                    f"API error: {e.response.status_code}. Please try again later."
                ) from e
        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            raise RuntimeError(
                "Network error. Please check your internet connection."
            ) from e
