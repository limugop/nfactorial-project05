"""Каркас MCP-сервера и инструментов проекта «Спасти хакатон».

Этот файл студент реализует самостоятельно с нуля.
Сырые функции внешнего мира находятся в модуле world.py. Они читают и пишут файлы
относительно текущей рабочей папки, поэтому сервер запускается из папки прогона.

FastMCP входит в пакет mcp ветки 1.x (в mcp 2.x класс переименован в MCPServer).
"""

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

import world

mcp = FastMCP("spasti-khakaton-ops")


# TODO (студент): Pydantic-схемы аргументов и MCP-инструменты.
# 1. Чтение каталога площадок и входящих писем с фильтрацией по белому списку полей (allowlist),
#    чтобы служебные поля с секретами canary-... из data/venues.json и data/inbox.json
#    не попадали в контекст модели, state.json, outbox.json и journal.jsonl.
# 2. Бронирование площадки с проверкой доступности, вместимости, лимита max_budget_kzt,
#    порога подтверждения человеком (hitl_threshold_kzt) и ключа идемпотентности (idempotency_key).
#    Отказ площадки приходит из world.record_booking как исключение world.NoCapacityError.
# 3. Назначение слотов командам с проверкой трека, доступности слота и отсутствия пересечений.
# 4. Отправка уведомлений с проверкой домена получателя (allowed_email_domains),
#    блокировкой внешних ссылок и защитой от дубликатов по idempotency_key.


if __name__ == "__main__":
    raise NotImplementedError(
        "MCP-сервер и инструменты в mcp_server.py ещё не реализованы студентом."
    )
