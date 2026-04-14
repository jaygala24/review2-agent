from __future__ import annotations

from io import BytesIO
from urllib.parse import urljoin

import requests
from pypdf import PdfReader


def download_pdf(pdf_url: str, *, base_url: str | None = None) -> bytes:
    normalized_url = normalize_url(pdf_url, base_url=base_url)
    response = requests.get(normalized_url, timeout=120)
    response.raise_for_status()
    return response.content


def normalize_url(url: str, *, base_url: str | None = None) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not base_url:
        return url
    return urljoin(f"{base_url.rstrip('/')}/", url)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"\n\n[Page {index}]\n{text.strip()}\n")
    return "\n".join(pages).strip()
