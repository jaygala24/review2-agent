from __future__ import annotations

from io import BytesIO

import requests
from pypdf import PdfReader


def download_pdf(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, timeout=120)
    response.raise_for_status()
    return response.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"\n\n[Page {index}]\n{text.strip()}\n")
    return "\n".join(pages).strip()
