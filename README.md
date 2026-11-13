# CommerceCore API

Портфолио-проект: модульный backend интернет-магазина на Python и FastAPI.
Проект находится на начальном этапе разработки.

## Локальный запуск

Для работы необходимы Python 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
```

Документация API доступна по адресу <http://127.0.0.1:8000/docs>.
Эндпоинт `/api/v1/health` проверяет, что приложение отвечает; подключение к базе данных
и Redis пока не настроено.

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
