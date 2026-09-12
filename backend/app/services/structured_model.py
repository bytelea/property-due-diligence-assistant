"""Vertex AI JSON generation; no API keys or raw model responses are logged."""

import asyncio
import logging
from typing import Protocol

from google import genai
from google.auth.exceptions import GoogleAuthError
from google.genai import errors, types

from app.config import get_settings
from app.models.property_fact import StructuredModel


logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class StructuredModelClient(Protocol):
    async def generate(self, instruction: str, content: str, schema: type[StructuredModel]) -> str: ...


class GeminiStructuredModel:
    async def generate(self, instruction: str, content: str, schema: type[StructuredModel]) -> str:
        settings = get_settings()
        if not settings.gemini_model or not settings.google_cloud_project or not settings.google_cloud_location:
            raise ExtractionError(503, "Property extraction is not configured.")
        try:
            async with asyncio.timeout(60):
                async with genai.Client(
                    vertexai=True,
                    project=settings.google_cloud_project,
                    location=settings.google_cloud_location,
                    http_options=types.HttpOptions(timeout=55_000),
                ).aio as client:
                    response = await client.models.generate_content(
                        model=settings.gemini_model,
                        contents=content,
                        config=types.GenerateContentConfig(
                            system_instruction=instruction,
                            response_mime_type="application/json",
                            response_json_schema=schema.model_json_schema(),
                            temperature=0,
                        ),
                    )
                    result = response.text
            if not isinstance(result, str) or not result.strip():
                raise ExtractionError(502, "Property extraction returned no structured result.")
            return result
        except ExtractionError:
            raise
        except TimeoutError:
            raise ExtractionError(504, "Property extraction timed out.") from None
        except errors.APIError as error:
            if error.code in (401, 403):
                logger.warning("Vertex AI provider access failed.")
                raise ExtractionError(503, "Property extraction provider is unavailable.") from None
            raise ExtractionError(502, "Property extraction provider request failed.") from None
        except GoogleAuthError:
            logger.warning("Vertex AI provider access failed.")
            raise ExtractionError(503, "Property extraction provider is unavailable.") from None
        except Exception:
            # Provider/ADC errors may include request content; never forward them.
            raise ExtractionError(502, "Property extraction provider request failed.") from None


def get_structured_model() -> StructuredModelClient:
    """Explicit selection only. A provider error never switches providers."""
    provider = get_settings().model_provider
    if provider == "vertex":
        return GeminiStructuredModel()
    if provider == "anymize":
        from app.services.anymize_model import AnymizeStructuredModel
        return AnymizeStructuredModel()
    raise ExtractionError(503, "Property extraction provider is not configured.")
