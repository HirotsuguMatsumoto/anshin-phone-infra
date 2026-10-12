FROM asterisk_runtime

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends sip-tester \
    && rm -rf /var/lib/apt/lists/*

COPY scenarios /scenarios
COPY fax /mock-fax
RUN python3 /mock-fax/generate_audio.py
ENTRYPOINT []
