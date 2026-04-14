from __future__ import annotations

import time
from typing import Any

import requests

from scientific_reviewer.runlog import RunLogger


class ExternalEvidenceCollector:
    def __init__(
        self,
        logger: RunLogger | None = None,
        search_results: int = 5,
        semantic_scholar_api_key: str | None = None,
    ) -> None:
        self.logger = logger
        self.search_results = search_results
        self.session = requests.Session()
        self._request_index = 0
        self._max_retries = 2
        if semantic_scholar_api_key:
            self.session.headers.update({"x-api-key": semantic_scholar_api_key})

    def collect(
        self,
        *,
        research_round: int,
        queries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for query in queries:
            query_text = (query.get("query") or "").strip()
            if not query_text:
                continue
            results = self._search_semantic_scholar(query_text)
            for result in results:
                key = str(
                    result.get("paperId") or result.get("url") or result.get("title")
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                items.append(
                    {
                        "query": query_text,
                        "purpose": query.get("purpose"),
                        "source": "semantic_scholar",
                        "result": result,
                    }
                )

        bundle = {
            "research_round": research_round,
            "queries": queries,
            "items": items,
        }
        if self.logger:
            self.logger.write_json(
                f"analysis/external_evidence_round_{research_round}.json", bundle
            )
            self.logger.log_event(
                "external_evidence_bundle",
                research_round=research_round,
                query_count=len(queries),
                item_count=len(items),
            )
        return bundle

    def _search_semantic_scholar(self, query: str) -> list[dict[str, Any]]:
        last_error: str | None = None
        for attempt in range(self._max_retries + 1):
            self._request_index += 1
            response = self.session.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": self.search_results,
                    "fields": "title,abstract,year,venue,url,authors,citationCount,externalIds",
                },
                timeout=60,
            )

            if response.status_code == 429:
                retry_after = self._retry_delay_seconds(response, attempt)
                last_error = f"429 rate limited from Semantic Scholar, retrying in {retry_after}s"
                if self.logger:
                    self.logger.write_json(
                        f"research/{self._request_index:02d}_semantic_scholar_rate_limit.json",
                        {
                            "query": query,
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "body": response.text[:2000],
                            "attempt": attempt,
                            "retry_after_seconds": retry_after,
                        },
                    )
                    self.logger.log_event(
                        "external_search_rate_limited",
                        index=self._request_index,
                        source="semantic_scholar",
                        query=query,
                        attempt=attempt,
                        retry_after_seconds=retry_after,
                    )
                    self.logger.console(last_error)
                if attempt < self._max_retries:
                    time.sleep(retry_after)
                    continue
                return []

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                last_error = str(exc)
                if self.logger:
                    self.logger.write_json(
                        f"research/{self._request_index:02d}_semantic_scholar_error.json",
                        {
                            "query": query,
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "body": response.text[:2000],
                            "attempt": attempt,
                            "error": last_error,
                        },
                    )
                    self.logger.log_event(
                        "external_search_error",
                        index=self._request_index,
                        source="semantic_scholar",
                        query=query,
                        attempt=attempt,
                        error=last_error,
                    )
                    self.logger.console(
                        f"External search failed for query '{query}': {last_error}"
                    )
                return []

            payload = response.json()
            if self.logger:
                self.logger.write_json(
                    f"research/{self._request_index:02d}_semantic_scholar.json", payload
                )
                self.logger.log_event(
                    "external_search_response",
                    index=self._request_index,
                    source="semantic_scholar",
                    query=query,
                    result_count=len(payload.get("data", [])),
                )
            return payload.get("data", [])

        if self.logger and last_error:
            self.logger.console(
                f"External search exhausted retries for query '{query}': {last_error}"
            )
        return []

    def _retry_delay_seconds(self, response: requests.Response, attempt: int) -> int:
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            return min(max(int(retry_after), 1), 30)
        return min(5 * (attempt + 1), 15)
