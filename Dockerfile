FROM python:3.14.10-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock requirements.txt ./

RUN uv venv /opt/venv && \
    uv sync --frozen --no-dev --python /opt/venv/bin/python


FROM python:3.14.10-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /root/Mikobot

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY . .

CMD ["python", "-m", "Mikobot"]
