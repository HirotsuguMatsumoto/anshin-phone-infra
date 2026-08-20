FROM debian:12-slim

ARG ASTERISK_VERSION=22.10.1
ARG ASTERISK_SHA256=0953564c44fa49827f3c9d70ca6e80db83828c9848440852c6be44c961855353
ARG ASTERISK_BUILD_JOBS=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl libedit-dev libjansson-dev \
      libncurses-dev libspandsp-dev libsqlite3-dev libssl-dev libxml2-dev \
      pkg-config python3 uuid-dev \
    && curl --fail --location --silent --show-error \
      "https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${ASTERISK_VERSION}.tar.gz" \
      --output /tmp/asterisk.tar.gz \
    && echo "${ASTERISK_SHA256}  /tmp/asterisk.tar.gz" | sha256sum --check --strict \
    && mkdir -p /usr/src/asterisk \
    && tar -xzf /tmp/asterisk.tar.gz --strip-components=1 -C /usr/src/asterisk \
    && cd /usr/src/asterisk \
    && ./configure --with-jansson-bundled \
    && make -j"${ASTERISK_BUILD_JOBS}" \
    && make install \
    && ldconfig \
    && apt-get purge -y build-essential curl libedit-dev libjansson-dev \
      libncurses-dev libspandsp-dev libsqlite3-dev libssl-dev libxml2-dev \
      pkg-config uuid-dev \
    && apt-get autoremove -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libedit2 libjansson4 libncurses6 libspandsp2 libsqlite3-0 libssl3 \
      libuuid1 libxml2 \
    && rm -rf /var/lib/apt/lists/* /tmp/asterisk.tar.gz /usr/src/asterisk

COPY config/asterisk.conf /etc/asterisk/asterisk.conf
COPY config/modules.conf /etc/asterisk/modules.conf
COPY config/rtp.conf /etc/asterisk/rtp.conf
COPY config/pjsip.conf.template /opt/anshin-phone/templates/pjsip.conf.template
COPY config/extensions.conf.template /opt/anshin-phone/templates/extensions.conf.template
COPY scripts/render_config.py /opt/anshin-phone/render_config.py
COPY scripts/entrypoint.sh /usr/local/bin/anshin-phone-asterisk-entrypoint

RUN chmod 0755 /usr/local/bin/anshin-phone-asterisk-entrypoint \
    && mkdir -p /var/spool/asterisk/fax /var/log/asterisk /var/lib/asterisk

EXPOSE 5060/udp 10000-10100/udp

ENTRYPOINT ["/usr/local/bin/anshin-phone-asterisk-entrypoint"]
CMD ["asterisk", "-f", "-U", "root", "-G", "root", "-vvv"]
