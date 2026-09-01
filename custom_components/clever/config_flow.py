"""Config flow for the Clever integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CleverApiClient
from .const import CONF_LIVE_STATUS_ENABLED, CONF_LIVE_STATUS_URL, CONF_REFRESH_TOKEN, DOMAIN
from .exceptions import CleverAuthError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_LIVE_STATUS_ENABLED, default=False): bool,
    }
)

STEP_LIVE_STATUS_DATA_SCHEMA = vol.Schema({vol.Required(CONF_LIVE_STATUS_URL): str})


async def _async_validate_live_status_url(hass, url: str) -> bool:
    """Do a light connectivity check against the add-on's /status endpoint."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            await resp.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return False
    return True


class CleverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clever."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None
        self._pending_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CleverOptionsFlow()

    async def _async_validate_login(
        self, email: str, password: str
    ) -> tuple[dict[str, str], str | None]:
        """Attempt login, returning (errors, refresh_token)."""
        session = async_get_clientsession(self.hass)
        client = CleverApiClient(session)
        try:
            await client.async_login(email, password)
        except CleverAuthError as err:
            # Firebase's actual error (INVALID_PASSWORD, TOO_MANY_ATTEMPTS_TRY_LATER,
            # USER_DISABLED, etc.) is otherwise swallowed by the generic form error.
            _LOGGER.warning("Clever login failed: %s", err)
            return {"base": "invalid_auth"}, None
        except Exception as err:  # noqa: BLE001 - surface as a generic form error
            _LOGGER.warning("Clever login could not connect: %s", err)
            return {"base": "cannot_connect"}, None
        return {}, client.refresh_token

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial login step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            errors, refresh_token = await self._async_validate_login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                self._pending_data = {
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_LIVE_STATUS_ENABLED: user_input[CONF_LIVE_STATUS_ENABLED],
                }
                if user_input[CONF_LIVE_STATUS_ENABLED]:
                    return await self.async_step_live_status()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL], data=self._pending_data
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_live_status(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the live-status add-on's /status URL (only shown if the checkbox was ticked)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_LIVE_STATUS_URL]
            if await _async_validate_live_status_url(self.hass, url):
                return self.async_create_entry(
                    title=self._pending_data[CONF_EMAIL],
                    data={**self._pending_data, CONF_LIVE_STATUS_URL: url},
                )
            errors["base"] = "cannot_connect_live_status"

        return self.async_show_form(
            step_id="live_status",
            data_schema=STEP_LIVE_STATUS_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication triggered by an invalid refresh token."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and re-validate the login."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        email = self._reauth_entry.data[CONF_EMAIL]

        if user_input is not None:
            errors, refresh_token = await self._async_validate_login(
                email, user_input[CONF_PASSWORD]
            )
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_REFRESH_TOKEN: refresh_token,
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": email},
            errors=errors,
        )


class CleverOptionsFlow(OptionsFlow):
    """Lets the user enable/disable or change the live-status add-on URL later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            new_data = {**entry.data, CONF_LIVE_STATUS_ENABLED: user_input[CONF_LIVE_STATUS_ENABLED]}
            if user_input[CONF_LIVE_STATUS_ENABLED]:
                url = user_input.get(CONF_LIVE_STATUS_URL, "")
                if not url or not await _async_validate_live_status_url(self.hass, url):
                    errors["base"] = "cannot_connect_live_status"
                else:
                    new_data[CONF_LIVE_STATUS_URL] = url
            if not errors:
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LIVE_STATUS_ENABLED,
                    default=entry.data.get(CONF_LIVE_STATUS_ENABLED, False),
                ): bool,
                vol.Optional(
                    CONF_LIVE_STATUS_URL, default=entry.data.get(CONF_LIVE_STATUS_URL, "")
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
