"""Shared HTTP utilities."""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_DEFAULT_UA = "hs_analysis/1.0"


def http_get_json(
    url: str,
    *,
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None,
    user_agent: str = _DEFAULT_UA,
    on_error_return_none: bool = False,
) -> Any:
    """Fetch and parse JSON from *url*.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.
        headers: Optional extra headers (merged with User-Agent).
        user_agent: User-Agent header value.
        on_error_return_none: If True, return None on any error instead of raising.
    """
    merged = {"User-Agent": user_agent}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        if on_error_return_none:
            log.warning("HTTP fetch failed for %s: %s", url, exc)
            return None
        raise
