"""API client for Clever's private mobile-app backend and Firebase auth."""
from __future__ import annotations

import time
from typing import Any

import aiohttp

from .const import (
    ANDROID_CERT,
    ANDROID_PACKAGE,
    ANDROID_USER_AGENT,
    API_BASE_URL,
    API_KEY_HEADER_VALUE,
    APP_USER_AGENT,
    APP_VERSION,
    FIREBASE_API_KEY,
    FIREBASE_CLIENT,
    FIREBASE_GMPID,
    REFRESH_TOKEN_URL,
    TOKEN_REFRESH_MARGIN_SECONDS,
    VERIFY_PASSWORD_URL,
)
from .exceptions import CleverApiError, CleverAuthError
from .models import ChargingProfile, CleverCharger


class CleverApiClient:
    """Handles Firebase auth and calls to Clever's mobile-app backend."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._id_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def refresh_token(self) -> str | None:
        """The current refresh token, to be persisted in the config entry."""
        return self._refresh_token

    async def async_login(self, email: str, password: str) -> None:
        """Log in with email/password and obtain the initial tokens."""
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True,
            "clientType": "CLIENT_TYPE_ANDROID",
        }
        # Google's API-key restriction requires these Android identity headers on
        # verifyPassword too, not just the refresh-token endpoint - without them the
        # request is rejected with "Requests from this Android client application
        # <empty> are blocked."
        headers = {
            "X-Android-Package": ANDROID_PACKAGE,
            "X-Android-Cert": ANDROID_CERT,
            "User-Agent": ANDROID_USER_AGENT,
        }
        try:
            async with self._session.post(
                VERIFY_PASSWORD_URL,
                params={"key": FIREBASE_API_KEY},
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    message = (data or {}).get("error", {}).get("message", resp.status)
                    raise CleverAuthError(f"Login failed: {message}")
        except aiohttp.ClientError as err:
            raise CleverAuthError(f"Error communicating with Clever login: {err}") from err

        self._id_token = data["idToken"]
        self._refresh_token = data["refreshToken"]
        self._expires_at = time.time() + int(data["expiresIn"])

    async def async_ensure_token(self) -> None:
        """Make sure we have a valid, non-expired access token."""
        if self._id_token and time.time() < self._expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            return
        await self._async_refresh_token()

    async def _async_refresh_token(self) -> None:
        if not self._refresh_token:
            raise CleverAuthError("No refresh token available; login required")

        # These Android-identity headers are required by Clever/Firebase's API key
        # restrictions for this endpoint - confirmed to 403 without them.
        headers = {
            "X-Android-Package": ANDROID_PACKAGE,
            "X-Android-Cert": ANDROID_CERT,
            "X-Firebase-GMPID": FIREBASE_GMPID,
            "X-Firebase-Client": FIREBASE_CLIENT,
            "User-Agent": ANDROID_USER_AGENT,
        }
        payload = {"grantType": "refresh_token", "refreshToken": self._refresh_token}
        try:
            async with self._session.post(
                REFRESH_TOKEN_URL,
                params={"key": FIREBASE_API_KEY},
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    message = (data or {}).get("error", {}).get("message", resp.status)
                    raise CleverAuthError(f"Token refresh failed: {message}")
        except aiohttp.ClientError as err:
            raise CleverAuthError(f"Error communicating with Clever token refresh: {err}") from err

        self._id_token = data["id_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + int(data["expires_in"])

    def _api_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._id_token}",
            "Accept": "application/json",
            "x-api-key": API_KEY_HEADER_VALUE,
            "App-Version": APP_VERSION,
            "App-Platform": "Android",
            "Accept-Language": "en",
            "User-Agent": APP_USER_AGENT,
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _async_request(
        self, method: str, path: str, retry_on_auth_error: bool = True, **kwargs: Any
    ) -> Any:
        await self.async_ensure_token()
        url = f"{API_BASE_URL}{path}"
        try:
            async with self._session.request(
                method, url, headers=self._api_headers(), **kwargs
            ) as resp:
                if resp.status == 401 and retry_on_auth_error:
                    await self._async_refresh_token()
                    return await self._async_request(
                        method, path, retry_on_auth_error=False, **kwargs
                    )
                return await self._async_handle_response(resp)
        except aiohttp.ClientError as err:
            raise CleverApiError(f"Error communicating with Clever API: {err}") from err

    @staticmethod
    async def _async_handle_response(resp: aiohttp.ClientResponse) -> Any:
        if resp.status >= 400:
            raise CleverApiError(f"Clever API returned {resp.status} for {resp.url}")
        if resp.content_length == 0:
            return None
        return await resp.json(content_type=None)

    async def async_get_installations(self) -> list[CleverCharger]:
        """Fetch all charger installations for this account."""
        data = await self._async_request("GET", "/installations")
        return [CleverCharger.from_api(item) for item in (data or {}).get("data", [])]

    async def async_get_charging_profiles(self) -> list[ChargingProfile]:
        """Fetch all charging profiles for this account."""
        data = await self._async_request("GET", "/chargingprofiles")
        return [ChargingProfile.from_api(item) for item in (data or {}).get("data", [])]

    async def async_set_departure_time(self, profile_id: str, departure_time: str) -> None:
        """Set the departure time (HH:MM, 5-minute increments) for a profile."""
        await self._async_request(
            "PUT",
            f"/chargingprofiles/{profile_id}/departure-time",
            json={"departureTime": departure_time},
        )

    async def async_set_power_required(self, profile_id: str, power_required_kwh: int) -> None:
        """Set the desired charge energy (kWh) for a profile."""
        await self._async_request(
            "PUT",
            f"/chargingprofiles/{profile_id}/power-required",
            json={"powerRequired": power_required_kwh},
        )

    async def async_boost(self, charge_box_id: str, connector_id: int) -> None:
        """Disable smart charging until fully charged."""
        await self._async_request(
            "POST",
            f"/smartcharging/chargePoints/{charge_box_id}/connectors/{connector_id}/boost",
        )

    async def async_timebox_boost(
        self, charge_box_id: str, connector_id: int, duration_minutes: int
    ) -> None:
        """Disable smart charging for a fixed duration."""
        await self._async_request(
            "POST",
            f"/smartcharging/chargePoints/{charge_box_id}/connectors/{connector_id}/timebox-boost",
            params={"durationInMinutes": duration_minutes},
        )

    async def async_unboost(self, charge_box_id: str, connector_id: int) -> None:
        """Re-enable smart charging."""
        await self._async_request(
            "POST",
            f"/smartcharging/chargePoints/{charge_box_id}/connectors/{connector_id}/unboost",
        )
