# Only the isolated existing mock-smartphone service; never a production image.
FROM mock_sip_runtime
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY --from=phone_sdk / /sdk/
COPY --from=phone_native / /phone-native/
RUN test "$(cat /sdk/phone-sdk-commit.txt)" = 5a457451fa2712ba18e12b01738e8ff3af2b26fd \
    && cd /sdk && printf '%s\n' '#define PJMEDIA_HAS_VIDEO 0' '#define PJMEDIA_HAS_L16_CODEC 0' > pjlib/include/pj/config_site.h \
    && CFLAGS=-fPIC ./configure --disable-pjsua2 --disable-video --disable-sound --disable-ssl --disable-libsrtp --disable-libwebrtc --disable-opencore-amr --disable-silk --disable-opus --disable-speex-aec --disable-speex-codec --disable-gsm-codec --disable-ilbc-codec --disable-g722-codec --disable-g7221-codec \
    && make dep && make -j2 lib
COPY build-core.mk /sdk/build-core.mk
RUN cd /sdk && make -f build-core.mk
COPY driver.py /softphone-driver.py
ENTRYPOINT []
