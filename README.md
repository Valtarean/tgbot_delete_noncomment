# tgbot_delete_noncomment (refactor)

Этот репозиторий — бот для Telegram, который автоматически удаляет сообщения в группе, если они не являются комментариями под постами канала.

В этом наборе изменений добавлены:
- pydantic-based настройки (Settings)
- Перенос логики в модули (analyzer, notifier, warning_manager, db)
- Сохранение предупреждений в SQLite (aiosqlite)
- Тесты (pytest, pytest-asyncio)
- CI (GitHub Actions), Dockerfile, systemd example
- Улучшенная обработка ошибок и graceful shutdown

Быстрый старт
1. Скопируйте `.env.example` в `.env` и заполните значения.
2. Установите зависимости:
   pip install -r requirements.txt
3. Запустите:
   python bot.py

Docker
1. Соберите:
   docker build -t tgbot_delete_noncomment:latest .
2. Запустите (пример):
   docker run --env-file .env tgbot_delete_noncomment:latest

CI
- GitHub Actions запускает тесты и проверки форматирования.

Тесты
- Запуск: `pytest`

Конфигурация
- Файл `.env` (или переменные окружения) используются для конфигурации. См. `.env.example`.

Примечания
- Для production рекомендуется хранить токен и IDs как Secrets в CI / среде развертывания.
- Если вы хотите Redis вместо SQLite, замените слой `db.py` и соответствующие вызовы.