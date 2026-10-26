# The agent backend (server.py), also used to run setup_database.py.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    TZ=Asia/Singapore

# tzdata: "today" (move-in dates, a conversation's last day) is Singapore's date, as on the laptops.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /srv/app
# Dependencies first, so a code change does not install them again.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .

# --lan listens on every interface of the container; only the frontend container reaches it.
CMD ["python", "server.py", "--lan"]
