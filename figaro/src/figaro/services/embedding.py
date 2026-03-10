import logging

import openai

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"


class EmbeddingService:
    def __init__(self, api_key: str | None) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key) if api_key else None

    async def embed_one(self, text: str) -> list[float] | None:
        if not self._client:
            return None
        try:
            response = await self._client.embeddings.create(model=MODEL, input=text)
            return response.data[0].embedding
        except openai.OpenAIError as e:
            logger.error(f"Embedding request failed: {e}")
            return None

