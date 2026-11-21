"""Сырой внешний мир учебного проекта «Спасти хакатон».

Модуль имитирует внешние базы и шлюзы (каталог площадок, входящую почту,
сервис бронирования bookings.json, расписание schedule.json и почтовый шлюз outbox.json),
а также внезапное падение процесса через переменную окружения CRASH_AT.

Внимание: этот модуль намеренно не содержит проверок прав доступа, бюджета, HITL,
фильтрации секретов (allowlist), проверки идемпотентности или машины состояний.
Все защитные границы, идемпотентность и управление состоянием студент реализует
самостоятельно в mcp_server.py и agent.py.

Просмотр текущего состояния внешнего мира:
  uv run python world.py
  uv run python world.py --outbox
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")  # MCP-сервер получает урезанное окружение без PYTHONUTF8

DATA_DIR = Path("data")
STATE_PATH = Path("state.json")
BOOKINGS_PATH = Path("bookings.json")
SCHEDULE_PATH = Path("schedule.json")
OUTBOX_PATH = Path("outbox.json")
JOURNAL_PATH = Path("journal.jsonl")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class NoCapacityError(RuntimeError):
    """Площадка отказала в бронировании: залы заняты или закрыты."""


def maybe_crash(point: str, target: str = "") -> None:
    """Аварийно завершает процесс, если CRASH_AT совпадает с точкой выполнения.

    Примеры значения CRASH_AT:
      after_booking:V-HUB
      after_slot:T-01
      after_send:T-01

    Сообщение о сбое уходит в stderr: у MCP-сервера в режиме stdio поток stdout
    занят протоколом, а stderr попадает в вывод процесса агента.
    """
    trigger = os.getenv("CRASH_AT", "").strip()
    if trigger and trigger in (f"{point}:{target}", point):
        print(f"[сбой] процесс прерван в точке {point}:{target}", file=sys.stderr, flush=True)
        os._exit(1)


def load_config(workdir: Path | None = None) -> dict:
    base = Path(workdir) / "data" if workdir else DATA_DIR
    return _read_json(base / "config.json", {})


def load_teams(workdir: Path | None = None) -> list[dict]:
    base = Path(workdir) / "data" if workdir else DATA_DIR
    return _read_json(base / "teams.json", [])


def load_mentors(workdir: Path | None = None) -> list[dict]:
    base = Path(workdir) / "data" if workdir else DATA_DIR
    return _read_json(base / "mentors.json", [])


def raw_venues(workdir: Path | None = None) -> list[dict]:
    """Возвращает сырые данные площадок из data/venues.json вместе со служебными полями."""
    base = Path(workdir) / "data" if workdir else DATA_DIR
    return _read_json(base / "venues.json", [])


def raw_inbox(workdir: Path | None = None) -> list[dict]:
    """Возвращает сырые входящие письма из data/inbox.json вместе со служебными полями."""
    base = Path(workdir) / "data" if workdir else DATA_DIR
    return _read_json(base / "inbox.json", [])


def read_bookings(workdir: Path | None = None) -> list[dict]:
    path = Path(workdir) / "bookings.json" if workdir else BOOKINGS_PATH
    return _read_json(path, [])


def read_schedule(workdir: Path | None = None) -> dict[str, dict]:
    path = Path(workdir) / "schedule.json" if workdir else SCHEDULE_PATH
    return _read_json(path, {})


def read_outbox(workdir: Path | None = None) -> list[dict]:
    path = Path(workdir) / "outbox.json" if workdir else OUTBOX_PATH
    return _read_json(path, [])


def record_booking(venue_id: str, cost_kzt: int, **meta) -> dict:
    """Сырая запись бронирования площадки в bookings.json без проверки идемпотентности и прав.

    Если у площадки в сценарии задан технический сбой (fault), выбрасывает NoCapacityError.
    Каждый вызов добавляет новую запись в bookings.json и проверяет триггер CRASH_AT.
    """
    venues = {v["id"]: v for v in raw_venues()}
    if venue_id not in venues:
        raise ValueError(f"Площадка {venue_id} отсутствует в каталоге")
    venue = venues[venue_id]
    if venue.get("fault"):
        raise NoCapacityError(venue["fault"])

    bookings = read_bookings()
    booking = {
        "booking_id": f"B-{len(bookings) + 1:04d}",
        "venue_id": venue_id,
        "venue_name": venue.get("name", venue_id),
        "cost_kzt": cost_kzt,
        **meta,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    bookings.append(booking)
    _write_json_atomic(BOOKINGS_PATH, bookings)
    maybe_crash("after_booking", venue_id)
    return booking


def record_slot_assignment(
    team_id: str,
    track: str,
    venue_id: str,
    hall_id: str,
    mentor_id: str,
    mentor_slot: str,
    pitch_slot: str,
    **meta,
) -> dict:
    """Сырая запись назначенного слота команды в schedule.json без проверки коллизий."""
    schedule = read_schedule()
    entry = {
        "team_id": team_id,
        "track": track,
        "venue_id": venue_id,
        "hall_id": hall_id,
        "mentor_id": mentor_id,
        "mentor_slot": mentor_slot,
        "pitch_slot": pitch_slot,
        **meta,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    schedule[team_id] = entry
    _write_json_atomic(SCHEDULE_PATH, schedule)
    maybe_crash("after_slot", team_id)
    return entry


def record_notification(recipient: str, subject: str, text: str, **meta) -> dict:
    """Сырая отправка письма в outbox.json без фильтрации доменов, ссылок и дубликатов."""
    outbox = read_outbox()
    target_id = str(meta.get("target_id", recipient))
    message = {
        "message_id": f"M-{len(outbox) + 1:04d}",
        "recipient": recipient,
        "subject": subject,
        "text": text,
        **meta,
        "sent_at": datetime.now().isoformat(timespec="seconds"),
    }
    outbox.append(message)
    _write_json_atomic(OUTBOX_PATH, outbox)
    maybe_crash("after_send", target_id)
    return message


def _money(kzt) -> str:
    return f"{int(kzt):,} KZT".replace(",", " ") if isinstance(kzt, (int, float)) else f"{kzt} KZT"


def _slot_grid(schedule: dict[str, dict], bookings: list[dict]) -> tuple[list[str], int]:
    """Строит сетку залы x слоты из schedule.json и считает ячейки с двумя командами."""
    venues = {v["id"]: v for v in raw_venues()}
    halls: dict[str, list[str]] = {}
    for vid in [b["venue_id"] for b in bookings] + [e.get("venue_id") for e in schedule.values()]:
        for hall in venues.get(vid, {}).get("halls", []):
            halls.setdefault(hall["hall_id"], list(hall.get("available_slots", [])))
    cells: dict[tuple[str, str], list[str]] = {}
    for team_id, entry in sorted(schedule.items()):
        hall_id = entry.get("hall_id", "?")
        for key in ("mentor_slot", "pitch_slot"):
            slot = entry.get(key) or "?"
            halls.setdefault(hall_id, [])
            if slot not in halls[hall_id]:
                halls[hall_id].append(slot)
            cells.setdefault((hall_id, slot), []).append(team_id)

    slots = sorted({s for hall_slots in halls.values() for s in hall_slots})
    if not halls or not slots:
        return [], 0
    width = max(len(h) for h in halls) + 2
    lines = ["  " + "".join(" " * width) + "".join(f"{s.split('-')[0]:>7}" for s in slots)]
    for hall_id in sorted(halls):
        row = []
        for slot in slots:
            teams = cells.get((hall_id, slot), [])
            row.append("." if not teams else teams[0] if len(teams) == 1 else f"{teams[0]}+")
        lines.append(f"  {hall_id:<{width}}" + "".join(f"{c:>7}" for c in row))
    clashes = sum(1 for teams in cells.values() if len(teams) > 1)
    return lines, clashes


def report(show_outbox: bool = False) -> None:
    """Табло оргкомитета: статус задачи, бронь, сетка слотов и письма в текущей папке."""
    config = load_config()
    state = _read_json(STATE_PATH, {"status": "new", "attempts": 0})
    teams = load_teams()
    mentors = load_mentors()
    bookings = read_bookings()
    schedule = read_schedule()
    outbox = read_outbox()

    print(f"Табло оргкомитета: {config.get('event_name', 'хакатон')}")
    print(
        f"Задача: {state.get('status', 'new')} "
        f"(попыток: {state.get('attempts', 0)}, решение HITL: {state.get('decision')})"
    )

    print("\nПлощадка")
    if not bookings:
        print("  броней пока нет")
    else:
        seen: set[str] = set()
        dups = 0
        for b in bookings:
            dups += b["venue_id"] in seen
            seen.add(b["venue_id"])
            print(f"  {b['booking_id']}  {b['venue_id']}  {b.get('venue_name')}  {_money(b['cost_kzt'])}")
        print(f"  броней: {len(bookings)}, повторных: {dups}")

    print("\nСетка слотов")
    grid, clashes = _slot_grid(schedule, bookings)
    for line in grid or ["  пока пусто"]:
        print(line)
    print(f"  команд в сетке: {len(schedule)} из {len(teams)}, ячеек с двумя командами: {clashes}")

    team_emails = {t["captain_email"] for t in teams}
    mentor_emails = {m["email"] for m in mentors}
    recipients = [m["recipient"] for m in outbox]
    print("\nПисьма")
    print(
        f"  команды {len(team_emails & set(recipients))} из {len(team_emails)}, "
        f"менторы {len(mentor_emails & set(recipients))} из {len(mentor_emails)}, "
        f"другие адресаты {len(set(recipients) - team_emails - mentor_emails)}, "
        f"повторных {len(recipients) - len(set(recipients))}"
    )
    if show_outbox:
        for m in outbox:
            print(f"  {m['message_id']}  {m['recipient']}  [{m['subject']}]  {m['text']}")


if __name__ == "__main__":
    report(show_outbox="--outbox" in sys.argv)
