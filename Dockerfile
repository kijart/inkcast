FROM python:3.13-slim

# uv version: keep in sync with required-version in pyproject.toml
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
RUN playwright install --with-deps --only-shell chromium

COPY src ./src
RUN uv sync --locked --no-dev

EXPOSE 11113
CMD ["inkcast", "/config/config.toml"]
