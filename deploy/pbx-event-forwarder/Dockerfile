FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY forwarder.py /app/forwarder.py
COPY healthcheck.py /app/healthcheck.py

RUN groupadd --gid 10001 anshin-phone \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin anshin-phone

USER 10001:10001

CMD ["python", "/app/forwarder.py"]
