ARG PYTHON_BASE_IMAGE=python:3.12-slim

FROM ${PYTHON_BASE_IMAGE} AS test

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir \
    -r requirements.txt \
    -r requirements-dev.txt \
    && groupadd --gid 10001 testgroup \
    && useradd --uid 10001 --gid 10001 --no-create-home testuser \
    && chown 10001:10001 /workspace

COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 tests ./tests

USER 10001:10001

CMD ["python", "-m", "pytest", "-q"]

FROM ${PYTHON_BASE_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid 10001 --no-create-home appuser

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=10001:10001 app ./app

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
