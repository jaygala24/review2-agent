from __future__ import annotations

from typing import Any

import requests

from scientific_reviewer.runlog import RunLogger


class ExternalEvidenceCollector:
    def __init__(
        self, logger: RunLogger | None = None, search_results: int = 5
    ) -> None:
        self.logger = logger
        self.search_results = search_results
        self.session = requests.Session()
        self._request_index = 0

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
        response.raise_for_status()
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
