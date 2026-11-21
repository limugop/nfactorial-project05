"""Состояние задачи переноса в state.json, отдельно от истории модели в sessions.db.

Граф статусов записан словарём, как в уроке 17: ключ это статус, множество это статусы, куда
из него можно перейти. Все смены статуса идут через move(). Файл пишется атомарно: целиком
старый или целиком новый, половины не бывает.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from journal import redact, write

PATH = Path("state.json")

GRAPH = {
    "new": {"running"},
    # running -> running: повтор после падения процесса
    "running": {"running", "waiting_approval", "done", "failed", "needs_attention"},
    "waiting_approval": {"running"},
    "done": set(),
    "failed": set(),
    "needs_attention": set(),
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fresh() -> dict:
    return {
        "status": "new",
        "attempts": 0,
        "decision": None,
        "selected_venue": None,
        "skill_activated": False,
        "bulletin": None,
        "checkpoint": None,
        "token_usage": {
            "model": None,
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "runs": [],
        },
        "history": [],
    }


def load() -> dict:
    task = fresh()
    if PATH.exists():
        task.update(json.loads(PATH.read_text(encoding="utf-8")))
    return task


def save(task: dict) -> None:
    task["updated_at"] = now()
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(redact(task), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def move(task: dict, target: str, **fields) -> dict:
    current = task.get("status", "new")
    if target not in GRAPH.get(current, set()):
        raise ValueError(f"Переход {current} -> {target} не разрешён графом")
    task.update(fields)
    task["status"] = target
    step = {"at": now(), "from": current, "to": target}
    if fields.get("reason"):
        step["reason"] = fields["reason"]
    task.setdefault("history", []).append(step)
    save(task)
    write("status", source=current, target=target, reason=fields.get("reason"))
    return task
