# 1. Базовый образ: Python 3.11 на урезанном Debian
FROM python:3.11-slim

# 2. Метаданные
LABEL maintainer="grekov@lab.local"
LABEL version="1.0"

# 3. Рабочая директория внутри контейнера
WORKDIR /app

# 4. Сначала только список зависимостей (ради кеша слоёв)
COPY requirements.txt .

# 5. Установка зависимостей
RUN pip install -r requirements.txt

# 6. Теперь код приложения
COPY app/ ./app/

# 7. Документируем порт, который слушает приложение
EXPOSE 5516

# 8. Запуск приложения на персональном порту
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5516"]
