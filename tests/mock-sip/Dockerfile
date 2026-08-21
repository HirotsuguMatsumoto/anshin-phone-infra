FROM debian:12-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends sip-tester \
    && rm -rf /var/lib/apt/lists/*

COPY scenarios /scenarios
