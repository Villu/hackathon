"""Fault injection used by the chaos round (spec 6.4). Do not remove — disabling `/chaos`
forfeits the resilience points. Faults are applied inside the LLM and MCP clients.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class ChaosState:
    llm_delay_ms: int = 0
    llm_garbage: bool = False
    llm_down: bool = False
    mcp_down: bool = False

    def update(self, payload: dict) -> None:
        """Replace the whole state: `{}` clears every fault."""
        names = {f.name for f in fields(self)}
        for name in names:
            setattr(self, name, payload.get(name, self.__dataclass_fields__[name].default))

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def active(self) -> bool:
        return any(v for v in asdict(self).values())


chaos = ChaosState()
