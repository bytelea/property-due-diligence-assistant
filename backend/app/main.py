from fastapi import FastAPI

from app.models.assessment import PropertyAssessment
from app.services.demo import build_demo_assessment

app = FastAPI(title="Property Due Diligence Assistant", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "property-due-diligence-assistant"}


@app.get("/demo-assessment", response_model=PropertyAssessment)
def demo_assessment() -> PropertyAssessment:
    return build_demo_assessment()
