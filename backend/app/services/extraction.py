import re
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from app.models.property_fact import (
    AnonymizedDocument, DocumentClassification, FactCandidates, PropertyExtraction, PropertyFact,
)
from app.prompts.property_extraction import EXTRACTION_PROMPT
from app.services.classification import DocumentClassificationService
from app.services.structured_model import ExtractionError, get_structured_model, StructuredModelClient


def number_occurs_in_evidence(value: float, evidence: str) -> bool:
    """Check numeric grounding, allowing common English/German number formats."""
    for token in re.findall(r"\d+(?:[., \u00a0]\d+)*", evidence):
        token = token.replace(" ", "").replace("\u00a0", "")
        candidates = set()
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
            candidates.add(token.replace(",", "").replace(".", ""))
        if "." in token and "," in token:
            decimal_separator = "." if token.rfind(".") > token.rfind(",") else ","
            thousands_separator = "," if decimal_separator == "." else "."
            candidates.add(token.replace(thousands_separator, "").replace(decimal_separator, "."))
        else:
            candidates.add(token.replace(",", "."))
        for candidate in candidates:
            try:
                if float(candidate) == value:
                    return True
            except ValueError:
                continue
    return False


class PropertyFactExtractionService:
    def __init__(self, model: StructuredModelClient):
        self.model = model

    async def extract(
        self, document: AnonymizedDocument, classification: DocumentClassification,
    ) -> list[PropertyFact]:
        raw = await self.model.generate(EXTRACTION_PROMPT, document.text, FactCandidates)
        try:
            candidates = FactCandidates.model_validate_json(raw)
        except ValidationError:
            raise ExtractionError(502, "Fact extraction returned invalid structured data.") from None
        facts = []
        seen = set()
        for candidate in candidates.facts:
            if not candidate.evidence.strip() or candidate.evidence not in document.text:
                raise ExtractionError(502, "Fact evidence could not be verified against the anonymized document.")
            if isinstance(candidate.value, str) and candidate.value not in candidate.evidence:
                raise ExtractionError(502, "Reference value could not be verified against its evidence.")
            if isinstance(candidate.value, float) and not number_occurs_in_evidence(candidate.value, candidate.evidence):
                raise ExtractionError(502, "Numeric value could not be verified against its evidence.")
            identity = candidate.model_dump(exclude={"confidence"})
            identity_json = candidate.model_copy(update={"confidence": 0}).model_dump_json()
            fact_id = str(uuid5(NAMESPACE_URL, document.document_id + ":" + identity_json))
            if fact_id in seen:
                continue
            seen.add(fact_id)
            facts.append(PropertyFact(
                **identity, confidence=candidate.confidence, fact_id=fact_id,
                document_id=document.document_id, document_type=classification.document_type,
                page=None,
            ))
        return facts


class PropertyExtractionService:
    """Orchestrates classification and extraction; deliberately runs no rules."""

    def __init__(self, model: StructuredModelClient | None = None):
        model = model if model is not None else get_structured_model()
        self.classifier = DocumentClassificationService(model)
        self.extractor = PropertyFactExtractionService(model)

    async def extract(self, document: AnonymizedDocument) -> PropertyExtraction:
        if not document.text.strip():
            raise ExtractionError(422, "Anonymized document text is empty.")
        classification = await self.classifier.classify(document)
        facts = await self.extractor.extract(document, classification)
        return PropertyExtraction(document_id=document.document_id, classification=classification, facts=facts)


def get_extraction_service() -> PropertyExtractionService:
    return PropertyExtractionService()
