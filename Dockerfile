FROM python:3.14.10-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /root/Mikobot
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.14.10-slim-trixie

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /root/Mikobot
COPY . .
RUN python -m compileall -q .

CMD ["python", "-m", "Mikobot"]
