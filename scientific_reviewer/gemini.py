from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from scientific_reviewer.runlog import RunLogger


class GeminiClient:
    def __init__(
        self, api_key: str, model: str, logger: RunLogger | None = None
    ) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.logger = logger
        self._call_index = 0

    def generate_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self._call_index += 1
        if self.logger:
            self.logger.write_json(
                f"llm/{self._call_index:02d}_request.json",
                {
                    "model": self.model,
                    "temperature": temperature,
                    "system_instruction": system_instruction,
                    "prompt": prompt,
                },
            )
            self.logger.log_event(
                "llm_request",
                index=self._call_index,
                model=self.model,
                temperature=temperature,
            )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )
        text = (response.text or "").strip()
        if self.logger:
            self.logger.write_json(
                f"llm/{self._call_index:02d}_response.json", {"text": text}
            )
            self.logger.log_event(
                "llm_response",
                index=self._call_index,
                model=self.model,
                response_chars=len(text),
            )
        return json.loads(_strip_json_fences(text))


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("\n", 1)[0]
    return cleaned.strip()
