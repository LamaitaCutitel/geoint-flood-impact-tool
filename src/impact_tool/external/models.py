from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceStatus:
    source: str
    ok: bool
    duration_seconds: float = 0.0
    warning: str = ""
    completeness: str = "complet"


@dataclass(frozen=True)
class ExternalResult:
    data: Any = None
    status: SourceStatus = field(
        default_factory=lambda: SourceStatus(source="necunoscut", ok=False)
    )

    @classmethod
    def success(
        cls,
        data: Any,
        *,
        source: str,
        duration_seconds: float,
        completeness: str = "complet",
        warning: str = "",
    ) -> "ExternalResult":
        return cls(
            data=data,
            status=SourceStatus(
                source=source,
                ok=True,
                duration_seconds=duration_seconds,
                warning=warning,
                completeness=completeness,
            ),
        )

    @classmethod
    def failure(
        cls,
        *,
        source: str,
        warning: str,
        duration_seconds: float = 0.0,
        data: Any = None,
        completeness: str = "indisponibil",
    ) -> "ExternalResult":
        return cls(
            data=data,
            status=SourceStatus(
                source=source,
                ok=False,
                duration_seconds=duration_seconds,
                warning=warning,
                completeness=completeness,
            ),
        )
