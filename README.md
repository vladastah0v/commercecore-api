# CommerceCore API

Портфолио-проект: модульный backend интернет-магазина на Python и FastAPI.
Проект находится на начальном этапе разработки.

## Локальный запуск

Для работы необходимы Python 3.12 и [uv](https://docs.astral.sh/uv/).
Скопируйте `.env.example` в `.env`, задайте локальный пароль PostgreSQL и запустите
PostgreSQL и Redis. Для сервисов можно использовать Docker Compose:

```bash
cp .env.example .env
docker compose up -d postgres redis
uv sync --locked
uv run uvicorn app.main:app --reload
```

Для создания таблиц примените миграции отдельной командой:

```bash
uv run alembic upgrade head
```

Документация API доступна по адресу <http://127.0.0.1:8000/docs>.
Эндпоинт `/api/v1/health` проверяет, что приложение отвечает. Эндпоинт
`/api/v1/health/ready` проверяет подключение к PostgreSQL и Redis и возвращает HTTP 503,
если один из сервисов недоступен.

## Запуск через Docker

Для запуска необходимы Docker и Docker Compose. Создайте локальный файл настроек:

```bash
cp .env.example .env
```

Замените `POSTGRES_PASSWORD` в `.env` на свой пароль для локальной разработки, затем запустите:

```bash
docker compose up --build -d
```

Примените миграции к базе в Docker:

```bash
docker compose run --rm api alembic upgrade head
```

Миграции не выполняются автоматически при старте API. Сейчас созданы таблицы
пользователей, refresh-токенов и категорий; остальные таблицы будут добавлены на следующих этапах.

API доступен по адресу <http://127.0.0.1:8000>, Swagger UI — по адресу
<http://127.0.0.1:8000/docs>. PostgreSQL и Redis запускаются в отдельных контейнерах,
а данные PostgreSQL сохраняются в именованном томе `postgres_data`.

Чтобы остановить контейнеры, сохранив данные PostgreSQL:

```bash
docker compose down
```

Файл `.env` не добавляется в Git. При первом создании тома PostgreSQL использует настройки
из `.env`; изменение пароля в файле не меняет пароль в уже существующей базе.

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Интеграционные проверки подключения используют отдельные тестовые PostgreSQL и Redis.
Для их запуска необходим работающий Docker:

```bash
docker compose -p commercecore-test -f docker-compose.test.yml up -d --wait
COMMERCECORE_RUN_INFRA_TESTS=1 uv run pytest
docker compose -p commercecore-test -f docker-compose.test.yml down --volumes
```

Тестовые сервисы используют порты `55432` и `56379` и отдельную базу
`commercecore_test`. Без `COMMERCECORE_RUN_INFRA_TESTS=1` интеграционные проверки
пропускаются. Команда `down --volumes` удаляет данные тестового проекта.
