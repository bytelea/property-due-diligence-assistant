from pydantic import ValidationError

from app.models.property_fact import AnonymizedDocument, DocumentClassification
from app.prompts.property_extraction import CLASSIFICATION_PROMPT
from app.services.structured_model import ExtractionError, StructuredModelClient


class DocumentClassificationService:
    def __init__(self, model: StructuredModelClient):
        self.model = model

    async def classify(self, document: AnonymizedDocument) -> DocumentClassification:
        raw = await self.model.generate(CLASSIFICATION_PROMPT, document.text, DocumentClassification)
        try:
            return DocumentClassification.model_validate_json(raw)
        except ValidationError:
            raise ExtractionError(502, "Document classification returned invalid structured data.") from None
