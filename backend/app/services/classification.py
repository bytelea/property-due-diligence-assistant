from pydantic import ValidationError
from app.services.extraction_diagnostics import emit, validation_failure

from app.models.property_fact import AnonymizedDocument, DocumentClassification
from app.prompts.property_extraction import CLASSIFICATION_PROMPT
from app.services.structured_model import ExtractionError, StructuredModelClient


class DocumentClassificationService:
    def __init__(self, model: StructuredModelClient):
        self.model = model

    async def classify(self, document: AnonymizedDocument) -> DocumentClassification:
        raw = await self.model.generate(CLASSIFICATION_PROMPT, document.text, DocumentClassification)
        emit("model_output_received")
        try:
            result = DocumentClassification.model_validate_json(raw)
            emit("structured_json_parse", structured_json_parsed=True)
            emit("property_fact_schema_validation", schema_validated=True)
            return result
        except ValidationError as error:
            validation_failure(error)
            raise ExtractionError(502, "Document classification returned invalid structured data.") from None
