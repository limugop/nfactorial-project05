"""Выбор модели по переменным окружения, как в уроке 17: MODEL_PROVIDER = openai, ollama или hf.

Проверяющий запускает проект со своим ключом, поэтому всё берётся из .env (образец .env.example).
Здесь же цены моделей для учёта стоимости прогона.
"""

import os

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

DEFAULTS = {
    "openai": ("OPENAI_MODEL", "gpt-5.6-luna"),
    "ollama": ("OLLAMA_MODEL", "qwen3.5:4b"),
    "hf": ("HF_MODEL", "openai/gpt-oss-120b"),
}

# USD за 1 млн токенов: (вход, выход). Для модели не из списка цена задаётся в .env через
# MODEL_PRICE_INPUT_PER_1M и MODEL_PRICE_OUTPUT_PER_1M. Без цены стоимость не считается,
# и лимит max_cost_usd проверить нельзя: обвязка пишет об этом в журнал.
PRICES = {
    # developers.openai.com/api/docs/models/gpt-5.6-luna, цена после снижения 30.07.2026
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
}


def provider() -> str:
    return os.getenv("MODEL_PROVIDER", "openai").strip().lower()


def model_name() -> str:
    env_name, default = DEFAULTS.get(provider(), ("OPENAI_MODEL", "gpt-5.6-luna"))
    return os.getenv(env_name, default)


def describe() -> str:
    return f"{provider()}:{model_name()}"


def price_per_1m() -> tuple[float, float] | None:
    custom_in = os.getenv("MODEL_PRICE_INPUT_PER_1M")
    custom_out = os.getenv("MODEL_PRICE_OUTPUT_PER_1M")
    if custom_in and custom_out:
        return float(custom_in), float(custom_out)
    if provider() == "ollama":
        return 0.0, 0.0
    return PRICES.get(model_name())


def check_ready() -> str | None:
    """Возвращает текст ошибки, если запустить модель нельзя."""
    if provider() not in DEFAULTS:
        return f"Неизвестный MODEL_PROVIDER={provider()}, допустимы openai, ollama, hf"
    if provider() == "openai" and not os.getenv("OPENAI_API_KEY"):
        return "Нет OPENAI_API_KEY: скопируйте .env.example в .env и впишите ключ"
    if provider() == "hf" and not os.getenv("HF_TOKEN"):
        return "Нет HF_TOKEN для MODEL_PROVIDER=hf"
    return None


def build_model():
    if provider() == "openai":
        return model_name()
    # Трассы уходят на platform.openai.com только с ключом OpenAI, для других провайдеров их выключаем.
    if not os.getenv("OPENAI_API_KEY"):
        set_tracing_disabled(True)
    if provider() == "ollama":
        client = AsyncOpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"), api_key="ollama"
        )
        return OpenAIChatCompletionsModel(model=model_name(), openai_client=client)
    client = AsyncOpenAI(base_url="https://router.huggingface.co/v1", api_key=os.environ["HF_TOKEN"])
    return OpenAIChatCompletionsModel(model=model_name(), openai_client=client)
