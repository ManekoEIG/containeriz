FROM python:3.11-slim

LABEL maintainer="grekov@lab.local"
LABEL version="3.0"

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY app/ ./app/
EXPOSE 8086

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
