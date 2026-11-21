"""Журнал journal.jsonl: шаги обвязки и каждый вызов инструмента, как Journal из урока 17.

Каждая строка пишется с flush и os.fsync, чтобы пережить падение процесса. Перед записью всё
проходит через redact(): журнал, состояние и трасса тоже хранилища, и секретам там не место.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from agents import RunHooks

PATH = Path("journal.jsonl")
HIDDEN = "[скрыто]"
SECRET_PATTERNS = (
    (re.compile(r"canary-[\w.-]*", re.IGNORECASE), HIDDEN),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), HIDDEN),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password)=([^\s&\"']+)"), r"\1=" + HIDDEN),
)


class CostLimitExceeded(RuntimeError):
    """Прогон дороже max_cost_usd из регламента."""


def redact(value):
    if isinstance(value, str):
        for pattern, replacement in SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def write(event: str, **fields) -> None:
    record = {"time": datetime.now().isoformat(timespec="seconds"), "event": event, **fields}
    line = json.dumps(redact(record), ensure_ascii=False, default=str)
    with PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def tool_text(output) -> str:
    """Результат MCP-инструмента приходит как {'type': 'text', 'text': ...} или списком таких."""
    if isinstance(output, dict):
        return str(output.get("text", output))
    if isinstance(output, list):
        return "\n".join(tool_text(item) for item in output)
    return str(output)


def parse(output) -> dict | None:
    try:
        data = json.loads(tool_text(output))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Journal(RunHooks):
    """Пишет вызовы модели и инструментов и считает токены и стоимость прогона."""

    def __init__(self, run_id: str, price: tuple[float, float] | None, cost_limit: float | None):
        self.run_id = run_id
        self.price = price
        self.cost_limit = cost_limit
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.pending_approval: dict | None = None
        self.booking_refusals: list[dict] = []

    @property
    def cost_usd(self) -> float | None:
        if self.price is None:
            return None
        return round(
            self.input_tokens / 1_000_000 * self.price[0] + self.output_tokens / 1_000_000 * self.price[1], 6
        )

    async def on_llm_end(self, context, agent, response) -> None:
        usage = response.usage
        self.requests += max(1, usage.requests or 0)
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        write(
            "llm_end",
            run=self.run_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd_so_far=self.cost_usd,
        )
        if self.cost_limit is not None and self.cost_usd is not None and self.cost_usd > self.cost_limit:
            raise CostLimitExceeded(f"стоимость прогона {self.cost_usd:.4f} USD выше лимита {self.cost_limit} USD")

    async def on_tool_start(self, context, agent, tool) -> None:
        write(
            "tool_start",
            run=self.run_id,
            call_id=getattr(context, "tool_call_id", None),
            tool=tool.name,
            args=getattr(context, "tool_arguments", None),
        )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        data = parse(result) or {}
        if tool.name == "book_venue" and data.get("status") == "approval_required":
            self.pending_approval = data
        elif tool.name == "book_venue" and data.get("ok") is False:
            self.booking_refusals.append(data)
        write(
            "tool_end",
            run=self.run_id,
            call_id=getattr(context, "tool_call_id", None),
            tool=tool.name,
            ok=data.get("ok"),
            status=data.get("status"),
            result=tool_text(result)[:1500],
        )
