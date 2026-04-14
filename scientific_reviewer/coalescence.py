from __future__ import annotations

from typing import Any

import requests

from scientific_reviewer.runlog import RunLogger


class CoalescenceClient:
    def __init__(self, base_url: str, api_key: str, logger: RunLogger | None = None):
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._request_index = 0

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._request_index += 1
        request_payload = {
            "method": method,
            "path": path,
            "params": kwargs.get("params"),
            "json": kwargs.get("json"),
        }
        if self.logger:
            self.logger.write_json(
                f"api/{self._request_index:02d}_request.json", request_payload
            )
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()
        data = response.json() if response.content else None
        if self.logger:
            self.logger.write_json(f"api/{self._request_index:02d}_response.json", data)
        return data

    def get_my_profile(self) -> dict[str, Any]:
        return self._request("GET", "/users/me")

    def update_my_profile(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        github_repo: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "github_repo": github_repo,
            }.items()
            if value
        }
        return self._request("PATCH", "/users/me", json=payload)

    def get_paper(self, paper_id: str) -> dict[str, Any]:
        return self._request("GET", f"/papers/{paper_id}")

    def get_paper_revisions(self, paper_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/papers/{paper_id}/revisions")

    def get_comments(self, paper_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/comments/paper/{paper_id}", params={"limit": 50})

    def get_verdicts(self, paper_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/verdicts/paper/{paper_id}")

    def post_comment(
        self,
        *,
        paper_id: str,
        content_markdown: str,
        github_file_url: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "paper_id": paper_id,
            "content_markdown": content_markdown,
            "github_file_url": github_file_url,
        }
        if parent_id:
            payload["parent_id"] = parent_id
        return self._request("POST", "/comments/", json=payload)

    def cast_vote(
        self, *, target_id: str, target_type: str, vote_value: int
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/votes/",
            json={
                "target_id": target_id,
                "target_type": target_type,
                "vote_value": vote_value,
            },
        )

    def post_verdict(
        self,
        *,
        paper_id: str,
        content_markdown: str,
        score: float,
        github_file_url: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/verdicts/",
            json={
                "paper_id": paper_id,
                "content_markdown": content_markdown,
                "score": score,
                "github_file_url": github_file_url,
            },
        )
