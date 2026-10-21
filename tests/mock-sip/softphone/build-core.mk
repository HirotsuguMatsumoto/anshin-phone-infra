include build.mak
.PHONY: all
all:
	$(APP_CXX) -std=c++17 -shared -fPIC $(APP_CFLAGS) /phone-native/phone_sip.cpp -o /libphone-softphone.so -Wl,--no-undefined -Wl,--start-group $(APP_LIB_FILES) -Wl,--end-group -lm -lpthread
