"""Config flow for the Clever integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CleverApiClient
from .const import CONF_REFRESH_TOKEN, DOMAIN
from .exceptions import CleverAuthError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class CleverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Clever."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

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
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_REFRESH_TOKEN: refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
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
