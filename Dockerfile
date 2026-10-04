# Prediction API. The same image runs locally and on AWS Lambda: the Lambda Web
# Adapter extension forwards Lambda invocations to uvicorn, so the app is plain FastAPI.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /bin/uv
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter

# LightGBM needs OpenMP.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cached layer): only what serving imports, pinned to uv.lock.
COPY pyproject.toml uv.lock README.md ./
COPY serving/requirements.in serving/
RUN uv export --frozen --no-hashes --all-extras --no-emit-project -o /tmp/constraints.txt \
    && uv pip install --system --no-cache -r serving/requirements.in -c /tmp/constraints.txt

COPY src ./src
RUN uv pip install --system --no-cache --no-deps .

# One image serves exactly one model version, exported from the registry at build time.
COPY build/model /opt/model

ENV MODEL_DIR=/opt/model \
    PYTHONUNBUFFERED=1 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    AWS_LWA_READINESS_CHECK_TIMEOUT_SECONDS=9

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8080
CMD ["uvicorn", "ne_demand.serving.app:app", "--host", "0.0.0.0", "--port", "8080"]
