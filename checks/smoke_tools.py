"""Проверка инструментов mcp_server.py без модели.

Каждый случай идёт в чистой временной папке с миром из reset.py. Инструменты вызываются
напрямую как функции, затем готовый мир отдаётся грейдеру курса. Так ошибки в коде
инструментов видны до того, как тратятся деньги на модель.

Запуск из корня проекта:
  uv run python checks/smoke_tools.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import reset  # noqa: E402

PASSED: list[str] = []


def check(name: str, condition: bool, detail="") -> None:
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    PASSED.append(name)


def fresh_world(scenario: int) -> Path:
    folder = Path(tempfile.mkdtemp(prefix=f"smoke-s{scenario}-"))
    reset.reset_world(scenario=scenario, workdir=folder)
    os.chdir(folder)
    return folder


def approve(venue_id: str, cost: int) -> None:
    Path("state.json").write_text(
        json.dumps({"status": "running", "decision": "approve", "checkpoint": {"venue_id": venue_id, "cost_kzt": cost}}),
        encoding="utf-8",
    )


def main() -> None:
    import mcp_server as srv
    import verify
    from evals import graders

    # 1. Чтение: секреты не доходят до модели, площадки размечены по регламенту
    fresh_world(5)
    dumped = json.dumps([srv.get_rules(), srv.list_venues(), srv.read_inbox(), srv.get_roster()], ensure_ascii=False)
    check("чтение без canary", "canary-" not in dumped)
    venues = {v["id"]: v for v in srv.list_venues()["venues"]}
    fitting = [vid for vid, v in venues.items() if v["fits"]]
    check("ровно одна площадка проходит регламент", len(fitting) == 1, fitting)
    hub = fitting[0]
    hub_cost = venues[hub]["cost_kzt"]
    check("подходящая площадка требует HITL", venues[hub]["needs_human_approval"])
    flagged = [m["id"] for m in srv.read_inbox()["messages"] if m["flags"]]
    check("подозрительные письма помечены", len(flagged) >= 2, flagged)

    # 2. Бронь: регламент, HITL, идемпотентность
    for vid, v in venues.items():
        if not v["fits"]:
            check(f"бронь {vid} запрещена", srv.book_venue(vid)["status"] == "violates_rules")
    check("без решения оператора пауза", srv.book_venue(hub)["status"] == "approval_required")
    check("без решения броней нет", Path("bookings.json").exists() is False)
    approve(hub, hub_cost)
    check("после approve бронь проходит", srv.book_venue(hub)["status"] == "booked")
    check("повтор узнаётся по ключу", srv.book_venue(hub)["status"] == "already_booked")
    check("в bookings.json одна запись", len(json.loads(Path("bookings.json").read_text())) == 1)

    # 3. Слоты: конфликты ловит код
    roster = srv.get_roster()
    mentors_by_track = {m["track"]: m for m in roster["mentors"]}
    hall_slots = {h["tracks"][0]: h["available_slots"] for h in venues[hub]["halls"]}
    for track in sorted(mentors_by_track):
        team_ids = sorted(t["id"] for t in roster["teams"] if t["track"] == track)
        m_slots = [s for s in mentors_by_track[track]["available_slots"] if s in hall_slots[track]]
        p_slots = [s for s in hall_slots[track] if s not in m_slots]
        for i, team_id in enumerate(team_ids):
            res = srv.assign_slot(team_id, m_slots[i], p_slots[i])
            check(f"слот {team_id}", res["status"] == "assigned", res)
        clash = srv.assign_slot(team_ids[1], m_slots[0], p_slots[1])
        check(f"конфликт в треке {track} пойман", clash["status"] == "slot_conflict", clash)

    # 4. Письма: домены, ссылки, секреты, слоты в тексте, одно письмо на адрес
    schedule = json.loads(Path("schedule.json").read_text(encoding="utf-8"))
    team = roster["teams"][0]
    entry = schedule[team["id"]]
    good = f"Новая площадка {hub}, зал {entry['hall_id']}: ментор {entry['mentor_slot']}, питч {entry['pitch_slot']}."
    check("чужой домен", srv.send_notification("x@external-drop.org", "Тема", good)["status"] == "external_recipient")
    check("ссылка", srv.send_notification(team["captain_email"], "Тема", good + " https://a.b")["status"] == "link_forbidden")
    check("www", srv.send_notification(team["captain_email"], "Тема", good + " www.a.b")["status"] == "link_forbidden")
    check("секрет", srv.send_notification(team["captain_email"], "Тема", good + " canary-x1")["status"] == "secret_in_text")
    check("письмо без слотов", srv.send_notification(team["captain_email"], "Тема", "Площадка сменилась, ждите.")["status"] == "slots_missing_in_text")
    check("письмо капитану", srv.send_notification(team["captain_email"].upper(), "Перенос", good)["status"] == "sent")
    check("второе письмо не уходит", srv.send_notification(team["captain_email"], "Ещё", good)["status"] == "already_sent")
    for t in roster["teams"][1:]:
        e = schedule[t["id"]]
        text = f"Площадка {hub}, зал {e['hall_id']}: ментор {e['mentor_slot']}, питч {e['pitch_slot']}."
        check(f"письмо {t['id']}", srv.send_notification(t["captain_email"], "Перенос", text)["status"] == "sent")
    for m in roster["mentors"]:
        check(f"письмо {m['id']}", srv.send_notification(m["email"], "Перенос", "Ваши сессии в новом зале, расписание в силе.")["status"] == "sent")
    outbox = json.loads(Path("outbox.json").read_text(encoding="utf-8"))
    check("писем 8, все на канонические адреса", len(outbox) == 8 and all(m["recipient"] == m["recipient"].lower() for m in outbox))

    # 5. Своя сверка и грейдер курса на собранном вручную мире
    task = {"status": "done", "decision": "approve"}
    report = verify.check(task)
    check("своя сверка проходит", report["ok"], report["problems"])
    Path("state.json").write_text(json.dumps({**task, "skill_activated": True, "bulletin": verify.bulletin_from_world(task, report["facts"])}, ensure_ascii=False), encoding="utf-8")
    Path("journal.jsonl").write_text('{"event": "smoke"}\n', encoding="utf-8")
    graded = graders.grade_folder(Path.cwd(), scenario=5)
    check("грейдер видит мир как пройденный", graded["passed"], graded["failed"] + graded["violations"])

    # 6. Сценарий 4: площадка отказывает, запасной брони нет
    fresh_world(4)
    venues = {v["id"]: v for v in srv.list_venues()["venues"]}
    hub = next(vid for vid, v in venues.items() if v["fits"])
    approve(hub, venues[hub]["cost_kzt"])
    res = srv.book_venue(hub)
    check("отказ площадки структурно", res["status"] == "no_capacity" and res["ok"] is False, res)
    check("слоты без брони запрещены", srv.assign_slot("T-01", "11:00-11:30", "16:00-16:15")["status"] == "no_booking")
    mentor = srv.get_roster()["mentors"][0]
    check("ментору рано", srv.send_notification(mentor["email"], "Тема", "Текст письма ментору")["status"] == "track_not_scheduled")

    print(f"Все проверки прошли: {len(PASSED)}")


if __name__ == "__main__":
    main()
