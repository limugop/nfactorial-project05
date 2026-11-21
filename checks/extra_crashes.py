"""Сбой в других точках: после назначения слота и после отправки письма.

Грейдер курса роняет процесс только сразу после брони (after_booking). В world.py есть ещё
две точки, after_slot и after_send, и в уроке 17 советуют проверить именно их: не получит ли
кто-нибудь второе письмо после перезапуска. Сценарий тот же, что во втором: пауза, --approve
со сбоем, обычный запуск. Сбой ставлю на третью команду, чтобы часть работы уже прошла,
а часть ещё нет. Проверяю ожиданиями второго сценария из грейдера курса.

Запуск из корня проекта (модель настоящая, ключ из .env):
  uv run python checks/extra_crashes.py --out runs-extra
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals import graders  # noqa: E402


def run_case(base: Path, point: str) -> dict:
    folder = graders._fresh_dir(base, f"crash-{point}", 2)
    target = json.loads((folder / "data" / "teams.json").read_text(encoding="utf-8"))[2]["id"]
    crash_at = f"{point}:{target}"
    graders._run_agent(folder)
    crashed = graders._run_agent(folder, "--approve", crash_at=crash_at)
    graders._run_agent(folder)
    result = graders.grade_folder(folder, scenario=2)
    result["crash_at"] = crash_at
    result["crash_seen"] = "[сбой]" in crashed.stdout + crashed.stderr
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Сбой после слота и после письма")
    parser.add_argument("--out", default="runs-extra")
    args = parser.parse_args()
    base = Path(args.out)
    if base.exists():
        raise SystemExit(f"{base} уже есть: старый прогон не перезаписываю, задайте другое имя")
    base.mkdir(parents=True)
    ok = True
    for point in ("after_slot", "after_send"):
        res = run_case(base, point)
        passed = res["passed"] and res["crash_seen"]
        ok = ok and passed
        facts = res["facts"]
        print(
            f"[{'УСПЕХ (PASS)' if passed else 'ПРОВАЛ (FAIL)'}] CRASH_AT={res['crash_at']}: "
            f"сбой виден: {res['crash_seen']}, броней {facts.get('booked:V-HUB', 0)}, "
            f"повторных броней {facts.get('duplicate_bookings', 0)}, повторных писем {facts.get('duplicate_notifications', 0)}, "
            f"статус {facts.get('status')}"
        )
        for line in res["failed"] + res["violations"]:
            print(f"    - {line}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
