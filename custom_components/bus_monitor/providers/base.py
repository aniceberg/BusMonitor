"""What every vehicle-tracking provider (Traccar, Bouncie, ...) offers the coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import Position


class ProviderError(Exception):
    """Base error."""


class CannotConnect(ProviderError):
    """Server unreachable or returned an unexpected response."""


class InvalidAuth(ProviderError):
    """Credentials rejected."""


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    unique_id: str
    status: str | None = None


class Provider(Protocol):
    """One provider account: lists its vehicles and their latest positions."""

    name: str  # shown in errors, e.g. "Traccar"
    manufacturer: str  # device registry manufacturer

    async def login(self) -> None:
        """Check the credentials; raises InvalidAuth or CannotConnect."""

    async def devices(self) -> list[Device]: ...

    async def positions(self) -> list[Position]:
        """Latest known position of every vehicle this account can see."""
