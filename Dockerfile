FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic openai python-dotenv openenv-core

COPY env ./env
COPY server ./server
COPY inference.py ./inference.py
COPY openenv.yaml ./openenv.yaml
COPY README.md ./README.md

EXPOSE 8000

CMD ["python", "-m", "server.app"]
