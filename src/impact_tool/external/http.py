from __future__ import annotations

import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_TIMEOUT_SECONDS = 25.0
USER_AGENT = "geoint-flood-impact-tool/1.0 (academic decision-support application)"


def configured_timeout() -> tuple[float, float]:
    try:
        value = float(os.getenv("EXTERNAL_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    value = max(1.0, min(value, 60.0))
    return (min(5.0, value), value)


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs: Any,
) -> Any:
    kwargs.setdefault("timeout", configured_timeout())
    response = session.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def romanian_http_error(service: str, error: Exception) -> str:
    if isinstance(error, requests.Timeout):
        return f"{service} nu a răspuns în intervalul configurat."
    if isinstance(error, requests.ConnectionError):
        return f"{service} nu este accesibil momentan."
    if isinstance(error, requests.HTTPError):
        return f"{service} a returnat un răspuns HTTP invalid."
    return f"{service} nu a putut furniza datele solicitate."
