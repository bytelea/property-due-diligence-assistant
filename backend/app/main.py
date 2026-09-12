from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.models.analysis import AnalysisResponse
from app.models.assessment import PropertyAssessment
from app.services.anymize import AnymizeError, AnymizeService, get_anymize_service
from app.services.demo import build_demo_assessment

app = FastAPI(title="Property Due Diligence Assistant", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "property-due-diligence-assistant"}


@app.get("/demo-assessment", response_model=PropertyAssessment)
def demo_assessment() -> PropertyAssessment:
    return build_demo_assessment()


MAX_PDF_BYTES = 10 * 1024 * 1024


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    request: Request,
    file: UploadFile,
    service: AnymizeService = Depends(get_anymize_service),
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
    return AnalysisResponse(anonymized_text=text)
