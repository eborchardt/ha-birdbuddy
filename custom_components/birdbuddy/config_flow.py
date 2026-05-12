"""Config flow for Bird Buddy integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from birdbuddy.client import BirdBuddy
from birdbuddy.exceptions import AuthenticationFailedError

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_EMAIL
from homeassistant.data_entry_flow import FlowResult

from .const import (
    AUTH_METHOD_EMAIL,
    AUTH_METHOD_GOOGLE,
    CONF_AUTH_METHOD,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


CONF_GOOGLE_TOKEN = "google_token"

STEP_EMAIL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_GOOGLE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GOOGLE_TOKEN): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bird Buddy."""

    VERSION = 1

    def __init__(self):
        self._client: BirdBuddy | None = None
        self._reauth_entry: ConfigEntry | None = None
        super().__init__()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: choose sign-in method."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["email", "google"],
        )

    async def async_step_email(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle email + password sign-in."""
        if user_input is None:
            return self.async_show_form(
                step_id="email", data_schema=STEP_EMAIL_DATA_SCHEMA
            )

        errors: dict[str, str] = {}
        self._client = BirdBuddy(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        result = await self._validate_client(errors)
        if result is None:
            return self.async_show_form(
                step_id="email",
                data_schema=STEP_EMAIL_DATA_SCHEMA,
                errors=errors,
            )

        await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
        entry_data = {
            CONF_AUTH_METHOD: AUTH_METHOD_EMAIL,
            CONF_EMAIL: user_input[CONF_EMAIL],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
        }
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={**self._reauth_entry.data, **entry_data},
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=result["title"], data=entry_data)

    async def async_step_google(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Google SSO sign-in via a pasted OAuth token."""
        if user_input is None:
            return self.async_show_form(
                step_id="google", data_schema=STEP_GOOGLE_DATA_SCHEMA
            )

        errors: dict[str, str] = {}
        self._client = BirdBuddy(google_token=user_input[CONF_GOOGLE_TOKEN])
        result = await self._validate_client(errors)
        if result is None:
            return self.async_show_form(
                step_id="google",
                data_schema=STEP_GOOGLE_DATA_SCHEMA,
                errors=errors,
            )

        user_email = self._client.user["email"].lower()
        await self.async_set_unique_id(user_email)
        entry_data = {
            CONF_AUTH_METHOD: AUTH_METHOD_GOOGLE,
            CONF_REFRESH_TOKEN: self._client.refresh_token,
            CONF_EMAIL: user_email,
        }
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data={**self._reauth_entry.data, **entry_data},
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=result["title"], data=entry_data)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Re-authenticate an existing entry whose Bird Buddy session was rejected."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if entry_data.get(CONF_AUTH_METHOD) == AUTH_METHOD_GOOGLE:
            return await self.async_step_google()
        return await self.async_step_email()

    async def _validate_client(self, errors: dict[str, str]) -> dict | None:
        """Call refresh() on the current client. Sets `errors` and returns None on failure."""
        try:
            ok = await self._client.refresh()
        except AuthenticationFailedError:
            self._client = None
            errors["base"] = "invalid_auth"
            return None
        except Exception:  # noqa: BLE001
            self._client = None
            errors["base"] = "cannot_connect"
            return None
        if not ok:
            self._client = None
            errors["base"] = "cannot_connect"
            return None
        return {"title": self._client.user.name}
