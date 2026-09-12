from typing import Literal

from pydantic import BaseModel


class AnalysisResponse(BaseModel):
    document_received: Literal[True] = True
    processing_status: Literal["completed"] = "completed"
    ready_for_extraction: Literal[True] = True
    anonymized_text: str
