"""Constants for the Clever integration."""
from datetime import timedelta

DOMAIN = "clever"
CONF_REFRESH_TOKEN = "refresh_token"

# --- Live charging status (direct from Firebase Firestore) ---
# Clever's REST API has no live-session equivalent, but the app's live data lives in
# Firestore and is readable with the very same Firebase ID token this integration
# already holds from login. We poll it on a short interval.
LIVE_STATUS_UPDATE_INTERVAL = timedelta(seconds=10)

# Clever's Firebase project + the named Firestore database the app's live session data
# lives in. Documents are at: {ROOT_COLLECTION}/{firebase_uid}/active-transactions/*
FIRESTORE_PROJECT = "clever-app-prod"
FIRESTORE_DATABASE = "user-database"
FIRESTORE_ROOT_COLLECTION = "v1-user-data"
FIRESTORE_BASE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FIRESTORE_PROJECT}"
    f"/databases/{FIRESTORE_DATABASE}/documents"
)

# --- Google Identity Toolkit / Firebase secure token endpoints ---
# This API key is embedded in the official Clever Android app itself (not a user
# secret) and is required to reach Firebase's identitytoolkit/securetoken APIs.
FIREBASE_API_KEY = "AIzaSyAQpjnGi6Tvk_sO9JFdS5Hj2NBuIEIAZjo"
VERIFY_PASSWORD_URL = (
    "https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword"
)
REFRESH_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# The token-refresh endpoint has been confirmed (by testing) to reject requests
# that don't carry these Android app identity headers, matching the real Clever
# Android app's package name and signing certificate hash. Sending them is
# required for the integration to keep working, not just cosmetic.
ANDROID_PACKAGE = "dk.clever.app"
ANDROID_CERT = "2B187B6CBA980988B235ED26BF755FEE7C1E0A43"
FIREBASE_GMPID = "1:59507274536:android:a687214acaadb386b4161d"
FIREBASE_CLIENT = (
    "H4sIAAAAAAAA_6tWykhNLCpJSk0sKVayio7VUSpLLSrOzM9TslIyUqoFAFyivEQfAAAA"
)
ANDROID_USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 16; sdk_gphone64_x86_64 "
    "Build/BE2A.250530.026.F3)"
)

# --- Clever mobile-app backend (private/undocumented REST API) ---
API_BASE_URL = "https://mobileapp-backend.clever.dk/api/v6"
# Static per-app key baked into the Clever Android app, required on every call.
API_KEY_HEADER_VALUE = "Basic bW9iaWxlYXBwOmFwaWtleQ=="
APP_VERSION = "26.33.0"
APP_USER_AGENT = f"dk.clever.core.network/{APP_VERSION}"

# Refresh the access token this many seconds before its real expiry (mirrors
# the official app's own behavior of refreshing early rather than right at expiry).
TOKEN_REFRESH_MARGIN_SECONDS = 300

UPDATE_INTERVAL = timedelta(seconds=60)

# --- Domain-specific value constraints (from Clever's official app behavior) ---
POWER_REQUIRED_MIN_KWH = 0
POWER_REQUIRED_MAX_KWH = 80
POWER_REQUIRED_STEP_KWH = 1
DEPARTURE_TIME_STEP_MINUTES = 5

# Smart-charging select options -> Clever's underlying "boost" endpoints.
SMART_CHARGING_ENABLE = "enable"
SMART_CHARGING_DISABLE_1H = "disable_1h"
SMART_CHARGING_DISABLE_3H = "disable_3h"
SMART_CHARGING_DISABLE_UNTIL_CHARGED = "disable_until_charged"
SMART_CHARGING_OPTIONS = [
    SMART_CHARGING_ENABLE,
    SMART_CHARGING_DISABLE_1H,
    SMART_CHARGING_DISABLE_3H,
    SMART_CHARGING_DISABLE_UNTIL_CHARGED,
]
