from __future__ import annotations

import io
import os
import zipfile
from typing import Iterable

import fitz
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="HBS PDF Converter API", version="0.1.0")


def get_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Converted-Pages", "X-Output-Filename"],
)


def parse_page_range(range_text: str | None, total_pages: int) -> list[int]:
    text = (range_text or "").strip()

    if not text or text == "전체":
        return list(range(1, total_pages + 1))

    pages: set[int] = set()

    for part in text.replace(" ", "").split(","):
        if not part:
            continue

        if "-" in part:
            start_text, end_text = part.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="페이지 범위를 다시 확인해 주세요.") from exc

            if start < 1 or end < start:
                raise HTTPException(status_code=400, detail="페이지 범위를 다시 확인해 주세요.")

            for page in range(start, min(end, total_pages) + 1):
                pages.add(page)
            continue

        try:
            page = int(part)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="페이지 번호를 다시 확인해 주세요.") from exc

        if page < 1 or page > total_pages:
            raise HTTPException(status_code=400, detail="페이지 번호를 다시 확인해 주세요.")

        pages.add(page)

    if not pages:
        raise HTTPException(status_code=400, detail="변환할 페이지가 없습니다.")

    return sorted(pages)


def quality_to_matrix(quality: float) -> fitz.Matrix:
    clamped = min(max(quality, 0.5), 1.0)
    scale = 1.4 + ((clamped - 0.5) / 0.5) * 1.2
    return fitz.Matrix(scale, scale)


def iter_selected_pages(document: fitz.Document, pages: Iterable[int]) -> Iterable[tuple[int, fitz.Page]]:
    for page_number in pages:
        yield page_number, document.load_page(page_number - 1)


@app.get("/health")
def healthcheck() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.post("/api/pdf/convert")
async def convert_pdf_to_jpg_zip(
    file: UploadFile = File(...),
    page_range: str = Form(""),
    jpg_quality: float = Form(0.9),
) -> StreamingResponse:
    if file.content_type not in {"application/pdf", "application/octet-stream"} and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="비어 있는 파일입니다.")

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - fitz raises several concrete types
        raise HTTPException(status_code=400, detail="PDF 파일을 열지 못했습니다.") from exc

    try:
        pages_to_convert = parse_page_range(page_range, document.page_count)
        matrix = quality_to_matrix(jpg_quality)
        filename_root = os.path.splitext(file.filename)[0] or "converted"
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for page_number, page in iter_selected_pages(document, pages_to_convert):
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                jpg_bytes = pixmap.tobytes("jpg", jpg_quality=int(min(max(jpg_quality, 0.5), 1.0) * 100))
                archive.writestr(
                    f"{filename_root}-page-{page_number:02d}.jpg",
                    jpg_bytes,
                )
    finally:
        document.close()

    zip_buffer.seek(0)
    output_name = f"{filename_root}-jpg.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{output_name}"',
            "X-Converted-Pages": str(len(pages_to_convert)),
            "X-Output-Filename": output_name,
        },
    )
