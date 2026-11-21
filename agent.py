"""Каркас управляемого агента-организатора и обвязки (harness) проекта «Спасти хакатон».

Этот файл студент реализует самостоятельно с нуля.

Примеры вызова CLI при проверке сценариев:
  uv run python agent.py
  uv run python agent.py --approve
  uv run python agent.py --reject
  uv run python agent.py --use-skill
  uv run python agent.py --no-skill
  uv run python agent.py --query "Какой текущий статус и слот у одной команды T-01?"

Папка прогона и папка кода различаются: evals/graders.py --run-all запускает этот файл
по полному пути из временной папки. Файлы мира (data/, state.json, bookings.json и другие)
лежат в текущей рабочей папке, а mcp_server.py и skills/ находятся рядом с agent.py (ROOT).
"""

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Агент-организатор переноса хакатона")
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument("--approve", action="store_true", help="Подтвердить действие на паузе HITL")
    decision.add_argument("--reject", action="store_true", help="Отклонить действие на паузе HITL")
    skill = parser.add_mutually_exclusive_group()
    skill.add_argument("--use-skill", action="store_true", help="Принудительно включить пакет SKILL.md")
    skill.add_argument("--no-skill", action="store_true", help="Принудительно отключить пакет SKILL.md")
    parser.add_argument("--query", type=str, default=None, help="Одиночный справочный запрос (Сценарий 3в)")
    parser.add_argument("--max-turns", type=int, default=None, help="Переопределить лимит шагов цикла")
    return parser.parse_args()


def main() -> None:
    _args = parse_args()
    # TODO (студент): управляемый цикл агента и обвязка (harness).
    # 1. Состояние задачи в state.json отдельно от истории сообщений и граф разрешённых переходов
    #    статусов (new -> running -> waiting_approval -> running -> done / failed / needs_attention).
    # 2. Подключение своего пакета навыка skills/<имя_навыка>/SKILL.md по условию задачи
    #    (флаг skill_activated и сводный бюллетень bulletin в state.json).
    # 3. Остановка на паузе waiting_approval перед бронированием площадки дороже hitl_threshold_kzt
    #    и продолжение с сохранённого чекпоинта по флагам --approve / --reject.
    # 4. Восстановление после аварийного сбоя CRASH_AT без повторных броней и дублирующих писем.
    #    MCP-сервер в режиме stdio получает от клиента только короткий список безопасных
    #    переменных окружения, поэтому CRASH_AT передаётся ему явно через параметр env.
    # 5. Запись вызовов инструментов и событий в journal.jsonl.
    # 6. Программная проверка конечного состояния мира перед выставлением статуса done.
    raise NotImplementedError(
        "Управляемый агент и обвязка в agent.py ещё не реализованы студентом."
    )


if __name__ == "__main__":
    main()
