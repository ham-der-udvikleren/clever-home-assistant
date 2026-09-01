# Clever Frida sidecar container (x86_64 first; ARM later)
#
# Boots a headless Android emulator with root access, installs the Clever app,
# attaches Frida to it, and exposes the parsed live-session data over a small
# local HTTP endpoint for the Home Assistant integration to poll.
#
# Requires: a Linux host (not Docker Desktop on macOS/Windows - no KVM
# passthrough there), `--device /dev/kvm` if the host supports it (falls back
# to slower software rendering otherwise).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator

# --- OS packages ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk-headless \
    curl unzip xz-utils ca-certificates \
    python3 python3-pip \
    nodejs npm \
    libgl1 libpulse0 libxcomposite1 libxcursor1 libxi6 libxtst6 libnss3 \
    libxss1 libasound2t64 libxrandr2 libxdamage1 libxfixes3 fonts-dejavu-core \
    xvfb x11vnc fluxbox novnc websockify \
    && rm -rf /var/lib/apt/lists/*

# --- Android SDK cmdline-tools + emulator + system image (x86_64, Android 15) ---
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
    && curl -sSL -o /tmp/cmdline-tools.zip \
       https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
    && unzip -q /tmp/cmdline-tools.zip -d ${ANDROID_HOME}/cmdline-tools \
    && mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
    && rm /tmp/cmdline-tools.zip

RUN yes | sdkmanager --licenses > /dev/null \
    && sdkmanager --install \
       "platform-tools" \
       "emulator" \
       "system-images;android-34;google_apis;x86_64"

# --- Frida (Python bindings; version must match the frida-server binary downloaded below) ---
RUN pip3 install --no-cache-dir --break-system-packages frida==17.17.0

# --- Frida on-device server binary (downloaded, not bundled - it's >100MB uncompressed) ---
RUN mkdir -p /opt/clever \
    && curl -sSL -o /tmp/frida-server.xz \
       https://github.com/frida/frida/releases/download/17.17.0/frida-server-17.17.0-android-x86_64.xz \
    && unxz /tmp/frida-server.xz \
    && mv /tmp/frida-server /opt/clever/frida-server-download

# --- Compile the Frida agent script from source (edit agent.js + rebuild, no manual bundling) ---
WORKDIR /opt/clever/agent-src
COPY package.json agent.js ./
# Fail the build loudly (instead of silently) if the build context has a stale agent.js
RUN grep -q "dispatchUncaughtException" agent.js \
    && echo "[build] agent.js source contains crash-suppression hook" \
    || (echo "[build] ERROR: agent.js in build context is MISSING the crash-suppression hook" && exit 1)
RUN npm install && npx frida-compile agent.js -o /opt/clever/agent.bundle.js
# Fail the build loudly if frida-compile's bundling dropped the hook
RUN grep -q "dispatchUncaughtException" /opt/clever/agent.bundle.js \
    && echo "[build] agent.bundle.js contains crash-suppression hook" \
    || (echo "[build] ERROR: frida-compile output is MISSING the crash-suppression hook" && exit 1)

# --- App/agent payload ---
RUN mkdir -p /opt/clever
COPY apks/*.apk /opt/clever/apks/
RUN mv /opt/clever/frida-server-download /opt/clever/frida-server && chmod 755 /opt/clever/frida-server
COPY relay.py /opt/clever/relay.py
COPY entrypoint.sh /opt/clever/entrypoint.sh
RUN chmod +x /opt/clever/entrypoint.sh

# noVNC (browser-based screen access, needed for the one-time interactive login)
EXPOSE 6080
# relay.py's HTTP status endpoint
EXPOSE 8000

VOLUME ["/root/.android"]

ENTRYPOINT ["/opt/clever/entrypoint.sh"]
