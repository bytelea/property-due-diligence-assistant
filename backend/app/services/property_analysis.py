"""All-or-error orchestration over request-scoped PDFs and anonymized facts."""
from app.services.extraction_diagnostics import begin, end, emit, unexpected_failure
import hashlib
import json

from fastapi import Depends

from app.models.assessment import PropertyAssessment
from app.models.document import ProcessedDocument
from app.models.property_fact import AnonymizedDocument, PropertyFact
from app.services.analysis_engine import AnalysisEngine
from app.services.normalization import normalize_facts
from app.services.anymize import AnymizeError, AnymizeService, get_anymize_service
from app.services.extraction import PropertyExtractionService, get_extraction_service
from app.services.pdf_uploads import PdfDocument
from app.services.structured_model import ExtractionError


class PropertyAnalysisError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class PropertyAnalysisService:
    def __init__(self, anonymizer: AnymizeService, extractor: PropertyExtractionService, engine: AnalysisEngine):
        self.anonymizer = anonymizer
        self.extractor = extractor
        self.engine = engine

    async def analyze(self, documents: list[PdfDocument]) -> PropertyAssessment:
        combined = []
        processed = []
        for ordinal, document in enumerate(sorted(documents, key=lambda item: item.document_id), start=1):
            try:
                anonymized = await self.anonymizer.anonymize_pdf(document.content)
            except AnymizeError as error:
                raise PropertyAnalysisError(error.status_code, "Document anonymization failed; no assessment was completed.") from None
            except Exception:
                raise PropertyAnalysisError(502, "Document anonymization failed; no assessment was completed.") from None
            if not isinstance(anonymized, str) or not anonymized.strip():
                raise PropertyAnalysisError(502, "Document anonymization returned no usable text; no assessment was completed.")
            if len(anonymized) > 100_000:
                raise PropertyAnalysisError(413, "An anonymized document exceeds the extraction limit of 100,000 characters.")
            diagnostic_token = begin(ordinal)
            stage = "model_output_received"
            category = "unexpected_extraction_error"
            try:
                extraction = await self.extractor.extract(AnonymizedDocument(document_id=document.document_id, text=anonymized))
                stage, category = "provenance_validation", "provenance_validation_failed"
                if extraction.document_id != document.document_id:
                    raise ValueError("Mismatched extraction provenance")
                facts = []
                for value in extraction.facts:
                    stage, category = "property_fact_schema_validation", "schema_validation_failed"
                    fact = PropertyFact.model_validate(value.model_dump())
                    emit(stage, schema_validated=True)
                    stage, category = "provenance_validation", "provenance_validation_failed"
                    if (fact.document_id != document.document_id or fact.document_type != extraction.classification.document_type
                        or not fact.evidence.strip() or fact.evidence not in anonymized):
                        raise ValueError("Mismatched fact provenance")
                    facts.append(fact)
                emit("provenance_validation", provenance_validated=True, fact_count=len(facts))
                emit("document_extraction_complete", "empty_fact_set" if not facts else None, fact_count=len(facts))
            except ExtractionError as error:
                unexpected_failure()
                message = "Property extraction provider is unavailable." if error.status_code == 503 else "Document extraction failed; no assessment was completed."
                raise PropertyAnalysisError(error.status_code, message) from None
            except Exception:
                emit(stage, category, False)
                raise PropertyAnalysisError(502, "Document extraction failed; no assessment was completed.") from None
            finally:
                end(diagnostic_token)
            combined.extend(facts)
            processed.append(ProcessedDocument(
                document_id=document.document_id, document_name=document.names[0], document_names=document.names,
                document_type=extraction.classification.document_type, fact_ids=sorted(f.fact_id for f in facts),
            ))
        try:
            canonical = normalize_facts(combined)
        except Exception:
            raise PropertyAnalysisError(502, "Document normalization failed; no assessment was completed.") from None
        try:
            assessment = self.engine.analyze(canonical)
        except Exception:
            raise PropertyAnalysisError(502, "Combined property analysis failed; no assessment was completed.") from None
        assessment.documents = processed
        names = {document.document_id: document.document_name for document in processed}
        for finding in assessment.findings:
            for evidence in finding.evidence:
                if evidence.document_id not in names:
                    raise PropertyAnalysisError(502, "Combined analysis returned invalid source provenance.")
                evidence.document_name = names[evidence.document_id]
        # Include documents producing zero facts in provenance and batch identity.
        assessment.run_metadata["input_document_ids"] = sorted(names)
        assessment.run_metadata["processed_document_count"] = len(processed)
        assessment.run_metadata["processing_stages_completed"] = True
        assessment.technical_processing_completed = True
        assessment.processing_status = "incomplete" if assessment.decision_readiness == "NOT_DECISION_READY" else "completed"
        fingerprint = json.dumps({"engine_assessment_id": assessment.id, "document_ids": sorted(names)}, sort_keys=True)
        assessment.id = "assessment-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
        return assessment


def get_analysis_engine() -> AnalysisEngine:
    # Preserve Julia's current policy defaults; never substitute fixture thresholds.
    return AnalysisEngine()


def get_property_analysis_service(
    anonymizer: AnymizeService = Depends(get_anymize_service),
    extractor: PropertyExtractionService = Depends(get_extraction_service),
    engine: AnalysisEngine = Depends(get_analysis_engine),
) -> PropertyAnalysisService:
    return PropertyAnalysisService(anonymizer, extractor, engine)
