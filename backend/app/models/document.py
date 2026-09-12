from typing import Literal

from pydantic import BaseModel, Field

from app.models.property_fact import DocumentType


class ProcessedDocument(BaseModel):
    document_id: str
    document_name: str
    document_names: list[str]
    document_type: DocumentType
    fact_ids: list[str] = Field(default_factory=list)
    processing_status: Literal["completed"] = "completed"
