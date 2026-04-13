import httpx


class ApiClient:
    def __init__(self, settings):
        self.settings = settings

    async def ask(self, question, top_k, speaker=None):
        payload = {"question": question, "top_k": top_k}
        if speaker is not None:
            payload["filters"] = {"speaker": speaker}

        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.post(
                    "/ask",
                    json=payload,
                    headers={"x-api-key": self.settings.api_key},
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out after 30 seconds")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise RuntimeError("Authentication failed — check API_KEY")
            if exc.response.status_code == 400:
                raise RuntimeError(f"Invalid request: {exc.response.text}")
            raise RuntimeError(f"API error: status {exc.response.status_code}")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Network error: {exc}")

    async def list_videos(self):
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.get(
                    "/videos",
                    headers={"x-api-key": self.settings.api_key},
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out after 30 seconds")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise RuntimeError("Authentication failed — check API_KEY")
            if exc.response.status_code == 400:
                raise RuntimeError(f"Invalid request: {exc.response.text}")
            raise RuntimeError(f"API error: status {exc.response.status_code}")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Network error: {exc}")

    async def health(self):
        try:
            async with httpx.AsyncClient(
                timeout=30.0, base_url=self.settings.api_endpoint
            ) as client:
                response = await client.get(
                    "/health",
                    headers={"x-api-key": self.settings.api_key},
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException:
            raise RuntimeError("Request timed out after 30 seconds")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise RuntimeError("Authentication failed — check API_KEY")
            if exc.response.status_code == 400:
                raise RuntimeError(f"Invalid request: {exc.response.text}")
            raise RuntimeError(f"API error: status {exc.response.status_code}")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Network error: {exc}")
