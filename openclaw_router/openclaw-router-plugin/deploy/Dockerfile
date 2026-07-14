FROM python:3.12-slim

ARG INSTALL_BGE=0
ARG XGBOOST_VERSION=3.3.0
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=3000 \
    EMBEDDING_MODE=hash

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-bge.txt ./
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --no-deps "xgboost==$XGBOOST_VERSION" \
    && if [ "$INSTALL_BGE" = "1" ]; then \
      python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements-bge.txt; \
    fi

COPY server.py ./
COPY strategist-mvp ./strategist-mvp
COPY models ./models
COPY data ./data

RUN useradd --create-home --uid 10001 router \
    && chown -R router:router /app

USER router

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3)" || exit 1

CMD ["python", "server.py"]
