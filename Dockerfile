FROM node:22-bookworm-slim AS web
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts ./
COPY apps/web ./apps/web
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY workers ./workers
COPY contracts ./contracts
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --all-extras --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY tools ./tools
COPY config ./config
COPY deploy/verify_restore.py ./deploy/verify_restore.py
RUN groupadd --gid 10001 rag && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin rag
COPY --from=web /build/apps/web/dist ./apps/web/dist
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
