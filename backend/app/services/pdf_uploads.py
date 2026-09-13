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
        self.message = message


@dataclass
class PdfDocument:
    document_id: str
    names: list[str]
    content: bytes = field(repr=False)
    validation_error: UploadValidationError | None = field(default=None, repr=False)


async def read_pdf_documents(files: list[UploadFile], max_pdf_bytes: int, *, isolate_validation: bool = False) -> list[PdfDocument]:
    if not files:
        raise UploadValidationError(400, "Upload at least one PDF in the files field.")
    if len(files) > MAX_DOCUMENTS:
        raise UploadValidationError(413, "Upload at most 10 PDF files per request.")
    documents: dict[str, PdfDocument] = {}
    total = 0
    for file in files:
        error = None
        if not file.filename or not file.filename.lower().endswith(".pdf") or file.content_type != "application/pdf":
            error = UploadValidationError(415, "Every upload must have a PDF filename and application/pdf content type.")
        try:
            content = await file.read(max_pdf_bytes + 1)
        except Exception:
            if not isolate_validation:
                raise UploadValidationError(400, "Unable to read an uploaded PDF.") from None
            content = b""
            error = UploadValidationError(400, "Unable to read an uploaded PDF.")
        if not content and error is None:
            error = UploadValidationError(400, "An uploaded PDF is empty.")
        elif len(content) > max_pdf_bytes:
            error = UploadValidationError(413, "Each PDF must be at most 10 MiB.")
        elif content and not content.startswith(b"%PDF-"):
            error = UploadValidationError(415, "Every uploaded file must have a valid PDF signature.")
        total += len(content)
        if total > MAX_BATCH_BYTES:
            raise UploadValidationError(413, "Combined PDF uploads must be at most 50 MiB.")
        if error and not isolate_validation:
            raise error
        document_id = "doc-" + hashlib.sha256(content).hexdigest() + ("-invalid-" + str(len(documents)) if error else "")
        name = (file.filename or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(character for character in name if character.isprintable())[:255] or "document.pdf"
        if document_id in documents:
            documents[document_id].names.append(name)
        else:
            documents[document_id] = PdfDocument(document_id=document_id, names=[name], content=content, validation_error=error)
    for document in documents.values():
        document.names = sorted(set(document.names))
    return sorted(documents.values(), key=lambda document: document.document_id)
