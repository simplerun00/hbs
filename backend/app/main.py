from __future__ import annotations

import io
import json
import os
import zipfile
from typing import Iterable

import fitz
from PIL import Image, ImageDraw
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="HBS PDF Converter API", version="0.3.0")


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

    if not text or text.lower() == "all" or text == "전체":
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


def parse_json_form(value: str | None, field_name: str) -> dict:
    text = (value or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 데이터 형식이 올바르지 않습니다.") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} 데이터 형식이 올바르지 않습니다.")

    return parsed


def apply_page_edits(pixmap: fitz.Pixmap, edits: list[dict] | None, jpg_quality: float) -> bytes:
    image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)

    if edits:
        draw = ImageDraw.Draw(image)
        width, height = image.size

        for edit in edits:
            if edit.get("type") == "rect":
                x1 = int(float(edit.get("x1", 0)) * width)
                y1 = int(float(edit.get("y1", 0)) * height)
                x2 = int(float(edit.get("x2", 0)) * width)
                y2 = int(float(edit.get("y2", 0)) * height)
                draw.rectangle([x1, y1, x2, y2], fill="white")
                continue

            if edit.get("type") == "freehand":
                points = edit.get("points") or []
                line_points = [
                    (int(float(px) * width), int(float(py) * height))
                    for px, py in points
                ]
                line_width = max(1, int(float(edit.get("width", 0.01)) * width))

                if len(line_points) >= 2:
                    draw.line(line_points, fill="white", width=line_width, joint="curve")

                radius = max(1, line_width // 2)
                for px, py in line_points:
                    draw.ellipse([px - radius, py - radius, px + radius, py + radius], fill="white")

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=int(min(max(jpg_quality, 0.5), 1.0) * 100))
    return output.getvalue()


@app.get("/")
def index() -> JSONResponse:
    return JSONResponse(
        {
            "service": "hbs-pdf-backend",
            "status": "ok",
            "health": "/health",
            "convert": "/api/pdf/convert",
        }
    )


@app.get("/health")
def healthcheck() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.post("/api/pdf/convert")
async def convert_pdf_to_jpg_zip(
    file: UploadFile = File(...),
    page_range: str = Form(""),
    jpg_quality: float = Form(0.9),
    edits_json: str = Form(""),
    rotations_json: str = Form(""),
) -> StreamingResponse:
    filename = file.filename or ""
    is_pdf = file.content_type in {"application/pdf", "application/octet-stream"} or filename.lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="비어 있는 파일입니다.")

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail="PDF 파일을 읽지 못했습니다.") from exc

    try:
        pages_to_convert = parse_page_range(page_range, document.page_count)
        base_matrix = quality_to_matrix(jpg_quality)
        edits_by_page = parse_json_form(edits_json, "편집")
        rotations_by_page = parse_json_form(rotations_json, "회전")
        filename_root = os.path.splitext(filename)[0] or "converted"
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for page_number, page in iter_selected_pages(document, pages_to_convert):
                rotation = int(rotations_by_page.get(str(page_number), 0) or 0)
                matrix = fitz.Matrix(base_matrix.a, base_matrix.d)
                if rotation:
                    matrix = matrix.prerotate(rotation)

                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                page_edits = edits_by_page.get(str(page_number), [])
                jpg_bytes = apply_page_edits(pixmap, page_edits, jpg_quality)
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
