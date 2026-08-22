FROM debian:12-slim

ARG RTPENGINE_VERSION=10.5.3.5-1+deb12u1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      rtpengine="${RTPENGINE_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10003 rtpengine-runtime \
    && useradd --uid 10003 --gid 10003 --no-create-home --shell /usr/sbin/nologin rtpengine-runtime

COPY scripts/entrypoint.sh /usr/local/bin/anshin-phone-rtpengine-entrypoint
RUN chmod 0755 /usr/local/bin/anshin-phone-rtpengine-entrypoint

USER 10003:10003

ENTRYPOINT ["/usr/local/bin/anshin-phone-rtpengine-entrypoint"]
