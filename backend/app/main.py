from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.models.analysis import AnalysisResponse
from app.models.assessment import PropertyAssessment
from app.models.property_fact import AnonymizedDocument
from app.services.anymize import AnymizeError, AnymizeService, get_anymize_service
from app.services.demo import build_demo_assessment
from app.services.extraction import PropertyExtractionService, get_extraction_service
from app.services.structured_model import ExtractionError

app = FastAPI(title="Property Due Diligence Assistant", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "property-due-diligence-assistant"}


@app.get("/demo-assessment", response_model=PropertyAssessment)
def demo_assessment() -> PropertyAssessment:
    return build_demo_assessment()


MAX_PDF_BYTES = 10 * 1024 * 1024


@app.post("/analyze", response_model=AnalysisResponse, response_model_exclude_none=True)
async def analyze(
    request: Request,
    file: UploadFile,
    service: AnymizeService = Depends(get_anymize_service),
    extraction_service: PropertyExtractionService = Depends(get_extraction_service),
    extract_facts: bool = False,
) -> AnalysisResponse:
    try:
        form = await request.form()
        if sum(isinstance(value, StarletteUploadFile) for _, value in form.multi_items()) != 1:
            raise HTTPException(400, "Upload exactly one PDF file.")
        if (
            not file.filename
            or not file.filename.lower().endswith(".pdf")
            or file.content_type != "application/pdf"
        ):
            raise HTTPException(415, "Upload a PDF file with content type application/pdf.")
        content = await file.read(MAX_PDF_BYTES + 1)
        if not content:
            raise HTTPException(400, "The uploaded PDF is empty.")
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF must be at most 10 MiB.")
        if not content.startswith(b"%PDF-"):
            raise HTTPException(415, "The uploaded file does not have a PDF signature.")
    finally:
        await file.close()

    try:
        text = await service.anonymize_pdf(content)
    except AnymizeError as error:
        raise HTTPException(error.status_code, str(error)) from None
    extraction = None
    if extract_facts:
        if len(text) > 100_000:
            raise HTTPException(413, "Anonymized text exceeds the extraction limit of 100,000 characters.")
        try:
            extraction = await extraction_service.extract(
                AnonymizedDocument(document_id=str(uuid4()), text=text)
            )
        except ExtractionError as error:
            raise HTTPException(error.status_code, str(error)) from None
    return AnalysisResponse(anonymized_text=text, extraction=extraction)
