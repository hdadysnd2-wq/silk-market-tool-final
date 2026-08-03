"""Outscraper Google-Maps adapter for long-tail buyer discovery."""

from __future__ import annotations

import httpx

from app.logging import get_logger
from app.providers.base import MapsPlace, ProviderRecord, SourceType

log = get_logger(__name__)

OUTSCRAPER_URL = "https://api.outscraper.com/maps/search-v3"


class OutscraperMapsProvider:
    name = "outscraper"

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def search_importers(
        self, query: str, country_iso2: str, limit: int = 20
    ) -> list[ProviderRecord[MapsPlace]]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    OUTSCRAPER_URL,
                    headers={"X-API-KEY": self._api_key},
                    params={
                        "query": query,
                        "limit": limit,
                        "region": country_iso2,
                        "async": "false",
                    },
                )
                response.raise_for_status()
                data = response.json().get("data", [[]])
                places = data[0] if data else []
        except (httpx.HTTPError, IndexError, KeyError) as exc:
            log.warning("outscraper_failed", query=query, error=str(exc))
            return []

        records = []
        for place in places:
            records.append(
                ProviderRecord(
                    data=MapsPlace(
                        name=place.get("name", "Unknown"),
                        country_iso2=country_iso2,
                        address=place.get("full_address"),
                        phone=place.get("phone"),
                        website=place.get("site"),
                        rating=place.get("rating"),
                        city=place.get("city"),
                    ),
                    source=SourceType.MAPS,
                    provider_name=self.name,
                    confidence=0.4,
                )
            )
        return records
