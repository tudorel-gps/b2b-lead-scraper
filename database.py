"""SQLite persistence layer: stores leads and prevents duplicates across runs."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

NO_WEBSITE = "FARA_WEBSITE"

_PLACE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.IGNORECASE)


@dataclass
class Lead:
    name: str
    maps_url: str
    category: str = ""
    rating: float | None = None
    reviews: int | None = None
    address: str = ""
    phone: str = ""
    website: str = NO_WEBSITE
    query: str = ""
    # enrichment
    site_status: int | None = None  # HTTP status, 0 = unreachable, None = not checked
    https: bool | None = None
    emails: list[str] = field(default_factory=list)
    tag: str = ""
    tag_reason: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def place_key(self) -> str:
        return place_key(self.maps_url)

    @property
    def has_website(self) -> bool:
        return bool(self.website) and self.website != NO_WEBSITE


def place_key(maps_url: str) -> str:
    """Stable identifier for a Google Maps place (hex feature id, or URL without query)."""
    m = _PLACE_ID_RE.search(maps_url)
    if m:
        return m.group(1).lower()
    parts = urlsplit(maps_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")).lower()


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    place_key   TEXT PRIMARY KEY,
    query       TEXT,
    name        TEXT NOT NULL,
    category    TEXT,
    rating      REAL,
    reviews     INTEGER,
    address     TEXT,
    phone       TEXT,
    website     TEXT,
    maps_url    TEXT,
    site_status INTEGER,
    https       INTEGER,
    emails      TEXT,
    tag         TEXT,
    tag_reason  TEXT,
    scraped_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_query ON leads(query);
"""

_COLUMNS = [
    "place_key", "query", "name", "category", "rating", "reviews", "address", "phone",
    "website", "maps_url", "site_status", "https", "emails", "tag", "tag_reason", "scraped_at",
]


class LeadDatabase:
    def __init__(self, path: str | Path = "leads.db") -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "LeadDatabase":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def known_keys(self) -> set[str]:
        return {row[0] for row in self._conn.execute("SELECT place_key FROM leads")}

    def exists(self, maps_url: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM leads WHERE place_key = ?", (place_key(maps_url),))
        return cur.fetchone() is not None

    def upsert(self, lead: Lead) -> None:
        data = asdict(lead)
        data["place_key"] = lead.place_key
        data["emails"] = ", ".join(lead.emails)
        data["https"] = None if lead.https is None else int(lead.https)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "place_key")
        with self._tx() as conn:
            conn.execute(
                f"INSERT INTO leads ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(place_key) DO UPDATE SET {updates}",
                data,
            )

    def leads_for_query(self, query: str) -> list[Lead]:
        rows = self._conn.execute(
            "SELECT * FROM leads WHERE query = ? ORDER BY scraped_at", (query,)
        ).fetchall()
        return [_row_to_lead(r) for r in rows]


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        name=row["name"],
        maps_url=row["maps_url"],
        category=row["category"] or "",
        rating=row["rating"],
        reviews=row["reviews"],
        address=row["address"] or "",
        phone=row["phone"] or "",
        website=row["website"] or NO_WEBSITE,
        query=row["query"] or "",
        site_status=row["site_status"],
        https=None if row["https"] is None else bool(row["https"]),
        emails=[e for e in (row["emails"] or "").split(", ") if e],
        tag=row["tag"] or "",
        tag_reason=row["tag_reason"] or "",
        scraped_at=row["scraped_at"] or "",
    )
