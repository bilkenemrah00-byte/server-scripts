"""
API-Football v3 HTTP client.

Handles:
- Authentication (x-apisports-key header)
- Retry with exponential backoff (429, 5xx, timeout)
- Rate limiting integration
- Structured error logging
- Response validation

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section VI.1
"""

import time
import logging
import httpx
from typing import Any, Optional
from pathlib import Path

from .rate_limiter import SyncRateLimiter, get_global_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
API_KEY_PATH = "/etc/openclaw/secrets/api_football_key"

# Retry config
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30.0


def load_api_key(path: str = API_KEY_PATH) -> str:
    """Load API key from secrets file.

    The key lives at /etc/openclaw/secrets/api_football_key
    mounted read-only into the Kestra container.
    """
    key_file = Path(path)
    if not key_file.exists():
        raise FileNotFoundError(
            f"API key not found at {path}. "
            "Ensure the secrets volume is mounted: "
            "-v /etc/openclaw/secrets:/etc/openclaw/secrets:ro"
        )
    key = key_file.read_text().strip()
    if not key:
        raise ValueError(f"API key file at {path} is empty")
    return key


class APIFootballClient:
    """Synchronous HTTP client for API-Football v3.

    Usage:
        client = APIFootballClient()

        # Fetch NS fixtures for today
        data = client.get("/fixtures", params={"date": "2026-03-19", "status": "NS"})

        # Always check response
        fixtures = data.get("response", [])

    The client handles retries internally. If all retries are exhausted,
    it raises the last exception. Callers should catch and handle.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limiter: Optional[SyncRateLimiter] = None,
    ):
        self._api_key = api_key or load_api_key()
        self._rate_limiter = rate_limiter or get_global_limiter()
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"x-apisports-key": self._api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._request_count = 0

    def get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make a GET request with retry logic.

        Args:
            endpoint: Path like '/fixtures', '/predictions', etc.
            params: Query parameters dict.

        Returns:
            Parsed JSON response dict. Always has 'response' key.

        Raises:
            httpx.HTTPStatusError: After all retries exhausted (non-429/5xx).
            httpx.TimeoutException: After all retries exhausted.
        """
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limiter.acquire()

                response = self._client.get(endpoint, params=params)
                self._request_count += 1

                # Check API-level errors (these are NOT HTTP errors)
                data = response.json()
                if data.get("errors"):
                    logger.warning(
                        f"API error on {endpoint}: {data['errors']}"
                    )
                    # API errors are not retryable (bad params, auth, etc.)
                    return data

                response.raise_for_status()

                results = data.get("results", 0)
                logger.debug(
                    f"GET {endpoint} → {results} results "
                    f"(attempt {attempt + 1}, total requests: {self._request_count})"
                )
                return data

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if status == 429:
                    # Rate limit — wait and retry
                    wait = BASE_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"429 rate limit on {endpoint}, waiting {wait}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    last_error = e

                elif status == 404:
                    # Not found — no retry
                    logger.warning(f"404 not found: {endpoint} params={params}")
                    return {"response": [], "results": 0, "errors": []}

                elif status >= 500:
                    # Server error — retry
                    wait = BASE_DELAY_SECONDS * (2 ** attempt)
                    logger.error(
                        f"Server error {status} on {endpoint}, "
                        f"retrying after {wait}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    last_error = e

                else:
                    # Other HTTP error — don't retry
                    logger.error(
                        f"HTTP {status} on {endpoint}: {e}"
                    )
                    raise

            except httpx.TimeoutException:
                wait = BASE_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    f"Timeout on {endpoint}, retrying after {wait}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(wait)
                last_error = Exception(f"Timeout after {attempt + 1} attempts: {endpoint}")

            except Exception as e:
                logger.error(f"Unexpected error on {endpoint}: {e}")
                raise

        # All retries exhausted
        logger.error(f"All {MAX_RETRIES} retries exhausted for {endpoint}")
        if last_error:
            raise last_error
        raise RuntimeError(f"Failed to fetch {endpoint} after {MAX_RETRIES} attempts")

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def request_count(self) -> int:
        """Total requests made by this client instance."""
        return self._request_count


# ---------------------------------------------------------------------------
# Convenience helpers — thin wrappers around common endpoints
# ---------------------------------------------------------------------------

def fetch_fixtures(
    client: APIFootballClient,
    date: str,
    status: str = "NS",
    league: Optional[int] = None,
) -> list[dict]:
    """Fetch fixtures for a given date.

    Args:
        date: YYYY-MM-DD format
        status: 'NS' for not started (default)
        league: Optional league ID filter

    Returns:
        List of fixture response objects.
    """
    params: dict[str, Any] = {"date": date, "status": status, "timezone": "UTC"}
    if league:
        params["league"] = league

    data = client.get("/fixtures", params=params)
    return data.get("response", [])


def fetch_predictions(client: APIFootballClient, fixture_id: int) -> Optional[dict]:
    """Fetch predictions for a fixture.

    CRITICAL: We extract ONLY raw statistics.
    We DO NOT use predictions.predictions.winner/percent/advice.

    Returns:
        First response item or None if unavailable.
    """
    data = client.get("/predictions", params={"fixture": fixture_id})
    response = data.get("response", [])
    return response[0] if response else None


def fetch_odds(
    client: APIFootballClient,
    fixture_id: int,
    bookmaker: Optional[int] = None,
) -> Optional[dict]:
    """Fetch odds for a fixture.

    Args:
        bookmaker: Optional bookmaker ID filter (e.g. 8 = Bet365)

    Returns:
        First response item or None if no odds available.
    """
    params: dict[str, Any] = {"fixture": fixture_id}
    if bookmaker:
        params["bookmaker"] = bookmaker

    data = client.get("/odds", params=params)
    response = data.get("response", [])
    return response[0] if response else None


def fetch_standings(
    client: APIFootballClient,
    league_id: int,
    season: int,
) -> list[dict]:
    """Fetch standings for a league/season.

    Returns:
        Flat list of team standing objects, or empty list.
    """
    data = client.get("/standings", params={"league": league_id, "season": season})
    response = data.get("response", [])
    if not response:
        return []
    try:
        return response[0]["league"]["standings"][0]
    except (KeyError, IndexError):
        return []


def fetch_odds_mapping(client: APIFootballClient) -> set[int]:
    """Fetch set of fixture IDs that have odds coverage.

    Used for coverage check (Stage 3).

    Returns:
        Set of fixture IDs with available odds.
    """
    data = client.get("/odds/mapping")
    response = data.get("response", [])
    return {item["fixture"]["id"] for item in response}


def fetch_bookmakers(client: APIFootballClient) -> dict[int, str]:
    """Fetch bookmaker ID → name mapping. Cache-friendly (changes rarely).

    Returns:
        Dict like {8: 'Bet365', 11: '1xBet', ...}
    """
    data = client.get("/odds/bookmakers")
    return {item["id"]: item["name"] for item in data.get("response", [])}


def fetch_bets(client: APIFootballClient) -> dict[int, str]:
    """Fetch bet type ID → name mapping. Cache-friendly (changes rarely).

    Returns:
        Dict like {1: 'Match Winner', 5: 'Goals Over/Under', ...}
    """
    data = client.get("/odds/bets")
    return {item["id"]: item["name"] for item in data.get("response", [])}


def fetch_past_fixtures(
    client: APIFootballClient,
    team_id: int,
    last: int = 20,
    league_id: Optional[int] = None,
    season: Optional[int] = None,
) -> list[dict]:
    """Fetch past completed fixtures for a team.

    Used for feature engineering — we fetch our own history
    rather than relying on predictions.last_5.

    Args:
        last: Number of past matches to fetch (max 20 recommended)

    Returns:
        List of completed fixture objects, most recent first.
    """
    params: dict[str, Any] = {"team": team_id, "last": last, "status": "FT"}
    if league_id:
        params["league"] = league_id
    if season:
        params["season"] = season

    data = client.get("/fixtures", params=params)
    return data.get("response", [])
