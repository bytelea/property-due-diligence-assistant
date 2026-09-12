from typing import Literal

from pydantic import BaseModel

from app.models.property_fact import PropertyExtraction


class AnalysisResponse(BaseModel):
    document_received: Literal[True] = True
    processing_status: Literal["completed"] = "completed"
    ready_for_extraction: Literal[True] = True
    anonymized_text: str
    extraction: PropertyExtraction | None = None
