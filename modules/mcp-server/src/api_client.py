import httpx

from src.config import get_settings


class ApiClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def ask(self, question: str, top_k: int = 5, speaker: str | None = None) -> dict:
        body: dict = {"question": question, "top_k": top_k}
        if speaker is not None:
            body["filters"] = {"speaker": speaker}
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.post(
                    "/ask", json=body, headers={"x-api-key": self.settings.api_key}
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Authentication failed: invalid API key")
            if e.response.status_code == 400:
                raise RuntimeError("Invalid request")
            raise RuntimeError(f"API error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error: {e}")

    async def list_videos(self) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.get(
                    "/videos", headers={"x-api-key": self.settings.api_key}
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Authentication failed: invalid API key")
            if e.response.status_code == 400:
                raise RuntimeError("Invalid request")
            raise RuntimeError(f"API error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error: {e}")

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.get(
                    "/health", headers={"x-api-key": self.settings.api_key}
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Authentication failed: invalid API key")
            if e.response.status_code == 400:
                raise RuntimeError("Invalid request")
            raise RuntimeError(f"API error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error: {e}")
