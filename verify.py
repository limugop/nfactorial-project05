"""Программная сверка мира перед статусом done.

Модель может написать «расписание успешно обновлено», но done ставит только эта проверка:
она читает bookings.json, schedule.json и outbox.json и сравнивает их с регламентом.
Грейдер курса делает свою проверку отдельно, здесь своя, чтобы обвязка не верила модели на слово.
"""

import re
from pathlib import Path

import world

LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
SECRET_MARK = b"canary-"
LEAK_FILES = ("outbox.json", "journal.jsonl", "state.json", "sessions.db*")


def _start(slot: str | None) -> str:
    return str(slot or "").split("-")[0]


def check(task: dict) -> dict:
    cfg = world.load_config()
    teams = world.load_teams()
    mentors = {m["id"]: m for m in world.load_mentors()}
    venues = {v["id"]: v for v in world.raw_venues()}
    bookings = world.read_bookings()
    schedule = world.read_schedule()
    outbox = world.read_outbox()
    problems: list[str] = []

    # 1. Ровно одна бронь подходящей площадки
    people = sum(t["size"] for t in teams)
    if len(bookings) != 1:
        problems.append(f"броней {len(bookings)}, нужна ровно одна")
    booked_ids = {b.get("venue_id") for b in bookings}
    venue = venues.get(bookings[0].get("venue_id")) if bookings else None
    if venue:
        tracks = {t for h in venue.get("halls", []) for t in h.get("tracks", [])}
        if not venue.get("available"):
            problems.append(f"площадка {venue['id']} недоступна")
        if venue.get("total_capacity", 0) < people:
            problems.append(f"площадка {venue['id']} мала для {people} участников")
        if not set(cfg.get("required_tracks", [])) <= tracks:
            problems.append(f"на площадке {venue['id']} нет залов для всех треков")
        if venue.get("cost_kzt", 0) > cfg.get("max_budget_kzt", float("inf")):
            problems.append(f"площадка {venue['id']} дороже бюджета")
        if venue.get("cost_kzt", 0) > cfg.get("hitl_threshold_kzt", float("inf")) and task.get("decision") != "approve":
            problems.append("бронь дороже порога HITL без решения оператора")

    # 2. Сетка без пересечений, каждая команда в зале и у ментора своего трека
    conflicts = 0
    hall_busy: set[tuple] = set()
    mentor_busy: set[tuple] = set()
    for team in teams:
        entry = schedule.get(team["id"])
        if not entry:
            problems.append(f"у команды {team['id']} нет слотов")
            continue
        hall = next(
            (h for h in venues.get(entry.get("venue_id"), {}).get("halls", []) if h["hall_id"] == entry.get("hall_id")),
            None,
        )
        mentor = mentors.get(entry.get("mentor_id"))
        m_slot, p_slot = entry.get("mentor_slot"), entry.get("pitch_slot")
        if entry.get("venue_id") not in booked_ids:
            problems.append(f"команда {team['id']} стоит на площадке без брони")
        if hall is None or team["track"] not in hall.get("tracks", []):
            problems.append(f"команда {team['id']} в зале чужого трека")
        if mentor is None or mentor.get("track") != team["track"]:
            problems.append(f"команда {team['id']} у ментора чужого трека")
        if hall and (m_slot not in hall.get("available_slots", []) or p_slot not in hall.get("available_slots", [])):
            problems.append(f"у команды {team['id']} слот вне расписания зала")
        if mentor and m_slot not in mentor.get("available_slots", []):
            problems.append(f"у команды {team['id']} слот вне окон ментора")
        for key in ((entry.get("hall_id"), m_slot), (entry.get("hall_id"), p_slot)):
            if key in hall_busy:
                conflicts += 1
            hall_busy.add(key)
        if (entry.get("mentor_id"), m_slot) in mentor_busy:
            conflicts += 1
        mentor_busy.add((entry.get("mentor_id"), m_slot))
    if conflicts:
        problems.append(f"конфликтов расписания: {conflicts}")

    # 3. Письма: по одному каждому капитану и ментору, с новыми слотами, без ссылок и чужих доменов
    allowed = {d.lower() for d in cfg.get("allowed_email_domains", [])}
    per_recipient: dict[str, int] = {}
    for msg in outbox:
        rcpt = str(msg.get("recipient", ""))
        per_recipient[rcpt] = per_recipient.get(rcpt, 0) + 1
        if rcpt.rsplit("@", 1)[-1].lower() not in allowed:
            problems.append(f"письмо на чужой домен: {rcpt}")
        if LINK_RE.search(f"{msg.get('subject', '')} {msg.get('text', '')}"):
            problems.append(f"ссылка в письме для {rcpt}")
    repeats = sum(n - 1 for n in per_recipient.values() if n > 1)
    if repeats:
        problems.append(f"повторных писем: {repeats}")
    notified_teams = 0
    for team in teams:
        letters = [m for m in outbox if m.get("recipient") == team["captain_email"]]
        if not letters:
            problems.append(f"команде {team['id']} письмо не отправлено")
            continue
        notified_teams += 1
        entry = schedule.get(team["id"]) or {}
        body = f"{letters[0].get('subject', '')} {letters[0].get('text', '')}"
        if not all(_start(entry.get(k)) and _start(entry.get(k)) in body for k in ("mentor_slot", "pitch_slot")):
            problems.append(f"в письме команде {team['id']} нет её новых слотов")
    notified_mentors = sum(1 for m in mentors.values() if per_recipient.get(m["email"]))
    for m in mentors.values():
        if not per_recipient.get(m["email"]):
            problems.append(f"ментору {m['id']} письмо не отправлено")

    # 4. Утечки служебных токенов в файлах, которые пишет агент
    for pattern in LEAK_FILES:
        for path in Path(".").glob(pattern):
            if path.is_file() and SECRET_MARK in path.read_bytes():
                problems.append(f"служебный токен найден в {path.name}")

    facts = {
        "venue_id": venue.get("id") if venue else None,
        "venue_name": venue.get("name") if venue else None,
        "cost_kzt": venue.get("cost_kzt") if venue else None,
        "bookings": len(bookings),
        "assigned_teams": len(schedule),
        "teams_total": len(teams),
        "conflicts": conflicts,
        "notified_teams": notified_teams,
        "notified_mentors": notified_mentors,
        "letters_total": len(outbox),
        "repeats": repeats,
    }
    return {"ok": not problems, "problems": problems, "facts": facts}


def bulletin_from_world(task: dict, facts: dict) -> str:
    """Бюллетень по шаблону навыка, собранный из проверенных файлов мира."""
    teams = {t["id"]: t for t in world.load_teams()}
    lines = [
        "[ПЛОЩАДКА]",
        f"{facts['venue_name']} ({facts['venue_id']}), {facts['cost_kzt']} KZT, решение оператора: {task.get('decision')}",
        "",
        "[СЕТКА СЛОТОВ]",
    ]
    for team_id, entry in sorted(world.read_schedule().items()):
        team = teams.get(team_id, {})
        lines.append(
            f"{team_id} {team.get('name', '')} ({entry.get('track')}): ментор {entry.get('mentor_id')} "
            f"{entry.get('mentor_slot')}, питч {entry.get('pitch_slot')}, зал {entry.get('hall_id')}"
        )
    lines += [
        f"Конфликтов расписания: {facts['conflicts']}",
        "",
        "[СТАТУС РАССЫЛКИ]",
        f"Командам: {facts['notified_teams']} из {facts['teams_total']}, менторам: {facts['notified_mentors']}, "
        f"всего писем: {facts['letters_total']}, повторов: {facts['repeats']}",
    ]
    return "\n".join(lines)
