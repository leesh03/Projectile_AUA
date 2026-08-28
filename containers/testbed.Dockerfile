FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

COPY containers/testbed-requirements.txt /tmp/testbed-requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/testbed-requirements.txt \
    && groupadd --gid 65532 agent \
    && useradd --uid 65532 --gid 65532 --no-create-home agent

COPY --chown=65532:65532 agents /app/agents
COPY --chown=65532:65532 policy_runtime /app/policy_runtime
COPY --chown=65532:65532 core/__init__.py /app/core/__init__.py
COPY --chown=65532:65532 core/schemas /app/core/schemas
COPY --chown=65532:65532 data/shop.db /app/data/shop.db
COPY --chown=65532:65532 policies/policy_rules.json /app/policies/policy_rules.json

USER 65532:65532

ENTRYPOINT ["python", "-B", "-m", "policy_runtime.isolated_worker"]
