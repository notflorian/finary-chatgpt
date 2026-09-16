FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build/finary-bridge

COPY LICENSE /build/LICENSE
COPY finary-bridge/pyproject.toml finary-bridge/setup.py finary-bridge/MANIFEST.in ./
COPY finary-bridge/.repository-source ./
COPY finary-bridge/app ./app

RUN pip install --no-cache-dir . && rm -rf /build

WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
