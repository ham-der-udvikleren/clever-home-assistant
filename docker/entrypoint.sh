#!/bin/bash
set -euo pipefail

AVD_NAME="clever"
DISPLAY_NUM=":0"
export DISPLAY="${DISPLAY_NUM}"
# Generous on purpose - software emulation (no /dev/kvm) can take many minutes to boot.
BOOT_TIMEOUT="${BOOT_TIMEOUT:-900}"
# How many consecutive failed adb health checks (30s apart) before giving up on the emulator.
MAX_FAILED_HEALTH_CHECKS=3

echo "[entrypoint] Starting virtual display + noVNC (for login, whenever it's needed)..."
# A stale lock/socket FILE isn't the only way display :0 can be unavailable: if the
# previous Xvfb process itself is still alive (unclean restart of this same container),
# rm -f'ing the lock does nothing and a new Xvfb still can't bind. Kill any leftover
# process first, then clear the lock/socket files it left behind.
pkill -9 -f "Xvfb ${DISPLAY_NUM} " 2>/dev/null || true
sleep 1
rm -f "/tmp/.X${DISPLAY_NUM#:}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
Xvfb "${DISPLAY_NUM}" -screen 0 1080x2280x24 &
XVFB_PID=$!

echo "[entrypoint] Waiting for Xvfb to come up on ${DISPLAY_NUM}..."
for _ in $(seq 1 10); do
    if [ -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
        break
    fi
    if ! kill -0 "${XVFB_PID}" 2>/dev/null; then
        echo "[entrypoint] FATAL: Xvfb exited immediately - see errors above." >&2
        exit 1
    fi
    sleep 1
done
if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
    echo "[entrypoint] FATAL: Xvfb did not create its X11 socket within 10s." >&2
    exit 1
fi

fluxbox &
# -afteraccept/-gone bring the Clever app to the foreground when someone actually opens a
# VNC session, and send it back to the background when they leave - no need to hunt for a
# home-screen icon (Android 8+ removed the old silent-shortcut-pin broadcast, and modern
# ShortcutManager pinning requires interactive user consent, so this is the reliable option).
x11vnc -display "${DISPLAY_NUM}" -forever -nopw -quiet -rfbport 5900 \
    -afteraccept 'adb shell monkey -p dk.clever.app -c android.intent.category.LAUNCHER 1' \
    -gone 'adb shell input keyevent KEYCODE_HOME' &
websockify --web=/usr/share/novnc 6080 localhost:5900 &

echo "[entrypoint] Ensuring AVD '${AVD_NAME}' exists..."
if [ ! -d "${HOME}/.android/avd/${AVD_NAME}.avd" ]; then
    echo "no" | avdmanager create avd \
        --force \
        --name "${AVD_NAME}" \
        --package "system-images;android-34;google_apis;x86_64" \
        --device "pixel_6"
fi

# Lower than the Pixel 6 default (1080x2400) - this is a headless service that rarely
# needs its screen, and the lower resolution meaningfully cuts SwiftShader's software-GL
# memory usage (confirmed by testing: ~1GB less RSS). Idempotent, safe to run every boot.
CONFIG_INI="${HOME}/.android/avd/${AVD_NAME}.avd/config.ini"
sed -i 's/^hw\.lcd\.height = .*/hw.lcd.height = 1280/' "${CONFIG_INI}"
sed -i 's/^hw\.lcd\.width = .*/hw.lcd.width = 720/' "${CONFIG_INI}"
sed -i 's/^hw\.lcd\.density = .*/hw.lcd.density = 320/' "${CONFIG_INI}"

ACCEL_FLAGS="-accel off -gpu swiftshader_indirect"
if [ -e /dev/kvm ]; then
    echo "[entrypoint] /dev/kvm present - using hardware acceleration."
    ACCEL_FLAGS="-accel on -gpu swiftshader_indirect"
else
    echo "[entrypoint] /dev/kvm NOT present - falling back to (slow) software emulation."
fi

echo "[entrypoint] Clearing any stale AVD locks from a previous unclean shutdown..."
find "${HOME}/.android/avd/${AVD_NAME}.avd" -name "*.lock" -exec rm -rf {} + 2>/dev/null || true
# The emulator keeps its crash reports under /tmp, which survives a container restart -
# left there, every boot re-reports the previous crash and asks for upload consent.
rm -rf /tmp/android-*/emu-crash-* 2>/dev/null || true

echo "[entrypoint] Booting emulator..."
# -no-metrics: the emulator warns its metrics notice will become a blocking prompt in a
# future release, and the Dockerfile always installs the latest emulator version.
emulator -avd "${AVD_NAME}" -no-audio -no-boot-anim -no-snapshot -no-metrics ${ACCEL_FLAGS} &
EMULATOR_PID=$!

# Bail out (and let Docker's restart policy retry from scratch) instead of waiting forever
# if the emulator dies or wedges mid-boot - e.g. its own hang detector killing it after
# "detected a hanging thread 'QEMU2 main loop'".
echo "[entrypoint] Waiting for boot (up to ${BOOT_TIMEOUT}s)..."
BOOT_DEADLINE=$((SECONDS + BOOT_TIMEOUT))
until [ "$(timeout 10 adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
    if ! kill -0 "${EMULATOR_PID}" 2>/dev/null; then
        echo "[entrypoint] FATAL: emulator exited during boot - see errors above." >&2
        exit 1
    fi
    if [ "${SECONDS}" -ge "${BOOT_DEADLINE}" ]; then
        echo "[entrypoint] FATAL: emulator did not finish booting within ${BOOT_TIMEOUT}s." >&2
        exit 1
    fi
    sleep 2
done
echo "[entrypoint] Boot complete."

adb root
sleep 1
adb shell device_config put activity_manager_native_boot cached_apps_freezer_enabled false || true

if ! adb shell pm list packages | grep -q "dk.clever.app"; then
    echo "[entrypoint] Installing Clever app..."
    adb install-multiple /opt/clever/apks/*.apk
else
    echo "[entrypoint] Clever app already installed (persisted volume) - skipping install."
fi

# Equivalent to toggling Settings > Apps > Clever > Battery > Unrestricted - the app runs
# in the background permanently (see relay.py's _background_app), so it must be exempt
# from Doze/App Standby or Android could eventually throttle its Firestore listeners.
echo "[entrypoint] Exempting Clever app from battery optimizations..."
adb shell dumpsys deviceidle whitelist +dk.clever.app || true
adb shell cmd appops set dk.clever.app RUN_IN_BACKGROUND allow || true
adb shell cmd appops set dk.clever.app RUN_ANY_IN_BACKGROUND allow || true

echo "[entrypoint] Starting frida-server..."
adb push /opt/clever/frida-server /data/local/tmp/frida-server
adb shell chmod 755 /data/local/tmp/frida-server
adb shell "/data/local/tmp/frida-server >/dev/null 2>&1 &"
sleep 1

cat <<'EOF'
============================================================
 If you ever need to log in manually (first run, or a
 previous session expired):
   1. Open http://<this-host>:6080/vnc.html in a browser -
      the Clever app comes to the foreground automatically
      as soon as you connect.
   2. Log in with email + password.
   3. Close the browser tab when done - the app goes back to
      the background automatically, and the session persists
      in the /root/.android Docker volume across restarts.
============================================================
EOF

echo "[entrypoint] Starting relay.py (spawns app under Frida, exposes :8000/status)..."
python3 /opt/clever/relay.py &
RELAY_PID=$!

# relay.py only recovers from the *app* dying - if the emulator itself dies or stops
# responding, it would just retry against a dead device forever while the container keeps
# looking healthy. So watch both, and exit if either is gone: Docker's restart policy
# (restart: unless-stopped) then brings the whole stack back up from a clean boot.
FAILED_HEALTH_CHECKS=0
while true; do
    sleep 30
    if ! kill -0 "${RELAY_PID}" 2>/dev/null; then
        echo "[entrypoint] FATAL: relay.py exited - exiting so Docker restarts the container." >&2
        exit 1
    fi
    if ! kill -0 "${EMULATOR_PID}" 2>/dev/null; then
        echo "[entrypoint] FATAL: emulator exited - exiting so Docker restarts the container." >&2
        exit 1
    fi
    if timeout 20 adb shell true >/dev/null 2>&1; then
        FAILED_HEALTH_CHECKS=0
        continue
    fi
    FAILED_HEALTH_CHECKS=$((FAILED_HEALTH_CHECKS + 1))
    echo "[entrypoint] Emulator not responding to adb (${FAILED_HEALTH_CHECKS}/${MAX_FAILED_HEALTH_CHECKS})." >&2
    if [ "${FAILED_HEALTH_CHECKS}" -ge "${MAX_FAILED_HEALTH_CHECKS}" ]; then
        echo "[entrypoint] FATAL: emulator unresponsive - exiting so Docker restarts the container." >&2
        exit 1
    fi
done
