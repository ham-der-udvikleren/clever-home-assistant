"""Runs inside the Docker sidecar: spawns the Clever app under Frida (using
spawn+resume to dodge the Maps-SDK-crash race), hooks the same domain classes
we validated manually, and exposes the latest captured data over a tiny local
HTTP endpoint for Home Assistant (or anything else) to poll.

Auto-respawns whenever the app process dies (it crashes periodically due to an
unrelated Google Play Services Maps SDK bug - see project notes).
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import frida

PACKAGE = "dk.clever.app"
AGENT_JS = (Path(__file__).parent / "agent.bundle.js").read_text(encoding="utf-8")
HTTP_PORT = 8000

# className -> {"text": <last toString() we saw>, "captured_at": <iso timestamp>}
latest: dict[str, dict[str, str]] = {}
latest_lock = threading.Lock()

# ActiveTransaction carries a real sessionId+startTimestamp - the only reliable way to
# tell "which charging session is this" apart from Firestore's local-cache replay churn
# (a currentTime-only watermark can't tell an older session's re-touched cache entry
# apart from a genuinely newer one, since it's just a client processing clock).
_SESSION_RE = re.compile(r"sessionId=([^,]+),.*?startTimestamp=(\d+)")
_current_session_start: int | None = None

ACTIVE_TRANSACTION_CLASS = "dk.clever.data.transaction.domain.ActiveTransaction"
CHARGING_PLAN_CLASS = "dk.clever.data.transaction.domain.ChargingPlan"
VEHICLE_SOC_CLASS = "dk.clever.data.transaction.domain.VehicleStateOfCharge"


def _extract_nested_object(text: str, marker: str) -> str | None:
    """Extract "ClassName(...)" for a nested field, balancing parens. `marker` must end in '('."""
    start = text.find(marker)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def record(class_name: str, text: str) -> None:
    global _current_session_start

    if class_name == ACTIVE_TRANSACTION_CLASS:
        match = _SESSION_RE.search(text)
        if match:
            session_start = int(match.group(2))
            if _current_session_start is not None and session_start < _current_session_start:
                print(
                    f"[relay] Ignoring ActiveTransaction from an older session "
                    f"(startTimestamp {session_start} < {_current_session_start})",
                    flush=True,
                )
                return
            _current_session_start = session_start
        now = datetime.now(timezone.utc).isoformat()
        with latest_lock:
            latest[class_name] = {"text": text, "captured_at": now}
            # Cascade the nested chargingPlan/vehicleStateOfCharge into the other two
            # /status keys so all three always agree on which session is current.
            nested_plan = _extract_nested_object(text, "ChargingPlan(")
            if nested_plan:
                latest[CHARGING_PLAN_CLASS] = {"text": nested_plan, "captured_at": now}
            nested_soc = _extract_nested_object(text, "VehicleStateOfCharge(")
            if nested_soc:
                latest[VEHICLE_SOC_CLASS] = {"text": nested_soc, "captured_at": now}
        return

    # Standalone ChargingPlan/VehicleStateOfCharge constructions carry no session
    # identity of their own, so they can't be reliably filtered - and were observed
    # clobbering the correctly session-filtered cascade above moments later with stale
    # cache-replay data. Just log them; don't let them write into `latest` at all.
    print(f"[relay] Ignoring standalone {class_name} (no session identity to filter on)", flush=True)


def on_message(message, data):  # noqa: ANN001 - frida callback signature
    if message["type"] != "send":
        print("MESSAGE:", message, flush=True)
        return
    payload = message["payload"]
    print(payload, flush=True)
    if " => " in payload:
        class_name, text = payload.split(" => ", 1)
        record(class_name.strip(), text.strip())


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required method name
        if self.path != "/status":
            self.send_response(404)
            self.end_headers()
            return
        with latest_lock:
            body = json.dumps(latest, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - silence default logging
        pass


def start_http_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), StatusHandler)
    server.serve_forever()


def force_stop() -> None:
    subprocess.run(["adb", "shell", "am", "force-stop", PACKAGE], check=False)


def _background_app() -> None:
    """Press Home to send the app to the background.

    Frida's hooks fire on JVM constructor calls regardless of whether the app is
    visible, and Firestore listeners keep delivering updates in the background too
    (that's exactly what cached_apps_freezer_enabled=false in entrypoint.sh is for) -
    so the app doesn't need to sit in the foreground continuously redrawing its live
    charging-session screen at ~35fps. Confirmed by testing: this alone dropped the
    container's CPU usage from ~1400% to ~35%, with no loss of live data.
    """
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_HOME"], check=False)


VNC_PORT = 5900
_TCP_ESTABLISHED = "01"


def _vnc_client_connected() -> bool:
    """Whether a VNC client currently has an established connection to x11vnc.

    Same network namespace as x11vnc (both run directly in this container), so reading
    /proc/net/tcp here reflects it - no extra tools (ss/netstat) needed.
    """
    try:
        with open("/proc/net/tcp", encoding="ascii") as f:
            next(f)  # header line
            for line in f:
                local_address, state = line.split()[1], line.split()[3]
                port = int(local_address.split(":")[1], 16)
                if port == VNC_PORT and state == _TCP_ESTABLISHED:
                    return True
    except OSError:
        pass
    return False


def _maybe_background_app() -> None:
    """Only background the app if nobody's actually using VNC right now.

    Avoids yanking the app away mid-session if someone's still connected when this
    timer fires - entrypoint.sh's x11vnc -gone hook handles backgrounding it as soon as
    they actually disconnect, so this just needs to keep deferring until then.
    """
    if _vnc_client_connected():
        threading.Timer(30, _maybe_background_app).start()
        return
    _background_app()


def spawn_and_hook(device: frida.core.Device) -> frida.core.Session:
    force_stop()
    pid = device.spawn([PACKAGE])
    session = device.attach(pid)
    script = session.create_script(AGENT_JS)
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    # Fallback for the case nobody ever opens VNC after a (re)spawn - if they do,
    # entrypoint.sh's x11vnc -afteraccept/-gone hooks foreground/background it instead,
    # dynamically, for as long as the session is actually open.
    threading.Timer(120, _maybe_background_app).start()
    return session


def supervisor_loop() -> None:
    device = frida.get_usb_device(timeout=10)
    while True:
        detached = threading.Event()
        try:
            session = spawn_and_hook(device)
            session.on("detached", lambda reason=None: detached.set())
            print("[relay] Hooked and running.", flush=True)
        except Exception as err:  # noqa: BLE001 - keep the supervisor alive no matter what
            print(f"[relay] spawn/attach failed: {err!r} - retrying in 3s", flush=True)
            time.sleep(3)
            continue

        detached.wait()
        print("[relay] Session detached (app likely crashed) - respawning...", flush=True)
        time.sleep(1)


def main() -> None:
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    print(f"[relay] Status endpoint listening on :{HTTP_PORT}/status", flush=True)
    supervisor_loop()


if __name__ == "__main__":
    main()
