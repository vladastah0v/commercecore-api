# CommerceCore API

Портфолио-проект: модульный backend интернет-магазина на Python и FastAPI.
Проект находится на начальном этапе разработки.

## Локальный запуск

Для работы необходимы Python 3.12 и [uv](https://docs.astral.sh/uv/).
При необходимости скопируйте `.env.example` в `.env` и измените настройки.

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
```

Документация API доступна по адресу <http://127.0.0.1:8000/docs>.
Эндпоинт `/api/v1/health` проверяет, что приложение отвечает; подключение к базе данных
и Redis пока не настроено.

## Запуск через Docker

Для запуска необходимы Docker и Docker Compose. Создайте локальный файл настроек:

```bash
cp .env.example .env
```

Замените `POSTGRES_PASSWORD` в `.env` на свой пароль для локальной разработки, затем запустите:

```bash
docker compose up --build -d
```

API доступен по адресу <http://127.0.0.1:8000>, Swagger UI — по адресу
<http://127.0.0.1:8000/docs>. PostgreSQL и Redis запускаются в отдельных контейнерах,
а данные PostgreSQL сохраняются в именованном томе `postgres_data`. На этом этапе сервисы
подготовлены, но приложение ещё не подключается к ним.

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
