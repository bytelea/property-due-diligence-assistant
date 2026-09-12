"""Request-scoped PDF validation; no persistence and no filename/content logging."""
from dataclasses import dataclass, field
import hashlib

from fastapi import UploadFile


MAX_DOCUMENTS = 10
MAX_BATCH_BYTES = 50 * 1024 * 1024


class UploadValidationError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PdfDocument:
    document_id: str
    names: list[str]
    content: bytes = field(repr=False)


async def read_pdf_documents(files: list[UploadFile], max_pdf_bytes: int) -> list[PdfDocument]:
    if not files:
        raise UploadValidationError(400, "Upload at least one PDF in the files field.")
    if len(files) > MAX_DOCUMENTS:
        raise UploadValidationError(413, "Upload at most 10 PDF files per request.")
    documents: dict[str, PdfDocument] = {}
    total = 0
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf") or file.content_type != "application/pdf":
            raise UploadValidationError(415, "Every upload must have a PDF filename and application/pdf content type.")
        content = await file.read(max_pdf_bytes + 1)
        if not content:
            raise UploadValidationError(400, "An uploaded PDF is empty; no documents were processed.")
        if len(content) > max_pdf_bytes:
            raise UploadValidationError(413, "Each PDF must be at most 10 MiB.")
        total += len(content)
        if total > MAX_BATCH_BYTES:
            raise UploadValidationError(413, "Combined PDF uploads must be at most 50 MiB.")
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError(415, "Every uploaded file must have a valid PDF signature.")
        document_id = "doc-" + hashlib.sha256(content).hexdigest()
        name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(character for character in name if character.isprintable())[:255] or "document.pdf"
        if document_id in documents:
            documents[document_id].names.append(name)
        else:
            documents[document_id] = PdfDocument(document_id=document_id, names=[name], content=content)
    for document in documents.values():
        document.names = sorted(set(document.names))
    return sorted(documents.values(), key=lambda document: document.document_id)
