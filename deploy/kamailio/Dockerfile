FROM debian:12-slim

ARG KAMAILIO_VERSION=5.6.3-2

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates \
      kamailio="${KAMAILIO_VERSION}" \
      python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10002 kamailio-runtime \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin kamailio-runtime

COPY config/kamailio.cfg.template /opt/anshin-phone/templates/kamailio.cfg.template
COPY scripts/render_config.py /opt/anshin-phone/render_config.py
COPY scripts/entrypoint.sh /usr/local/bin/anshin-phone-kamailio-entrypoint

RUN chmod 0755 /usr/local/bin/anshin-phone-kamailio-entrypoint \
    && mkdir -p /etc/kamailio /run/kamailio \
    && chown -R 10002:10002 /etc/kamailio /run/kamailio

USER 10002:10002

ENTRYPOINT ["/usr/local/bin/anshin-phone-kamailio-entrypoint"]
