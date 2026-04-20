"""Config flow for the Heiko Heat Pump integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, CONF_MN, CONF_FLOW_RATE, DEFAULT_FLOW_RATE

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_MN): str,
        vol.Required(CONF_FLOW_RATE, default=DEFAULT_FLOW_RATE): vol.Coerce(float),
    }
)


def _validate_mn(mn_str: str) -> bytes:
    """
    Validate and parse the MN hex string (e.g. "F4700C77F01A") to 6 bytes.
    Raises ValueError on invalid input.
    """
    mn_clean = mn_str.replace(":", "").replace("-", "").replace(" ", "").upper()
    if len(mn_clean) != 12:
        raise ValueError(f"MN must be 12 hex characters (6 bytes), got {len(mn_clean)}")
    return bytes.fromhex(mn_clean)


async def _test_connection(host: str, port: int) -> bool:
    """Attempt a TCP connection to verify the bridge is reachable."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=5.0,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as exc:
        _LOGGER.debug("Connection test failed: %s", exc)
        return False


class HeikoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow for Heiko Heat Pump."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> HeikoOptionsFlow:
        return HeikoOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            mn_str = user_input[CONF_MN].strip()

            # Validate MN format
            try:
                mn_bytes = _validate_mn(mn_str)
            except (ValueError, Exception) as exc:
                errors[CONF_MN] = "invalid_mn"
                _LOGGER.debug("Invalid MN %r: %s", mn_str, exc)
                mn_bytes = None

            if mn_bytes is not None:
                # Test TCP connectivity
                can_connect = await _test_connection(host, port)
                if not can_connect:
                    errors["base"] = "cannot_connect"
                else:
                    # Use MN as the unique ID to prevent duplicate entries
                    await self.async_set_unique_id(mn_str.upper().replace(":", ""))
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Heat Pump {host}",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_MN:   mn_str.upper().replace(":", ""),
                            CONF_FLOW_RATE: float(user_input[CONF_FLOW_RATE]),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )


class HeikoOptionsFlow(config_entries.OptionsFlow):
    """Allow editing host/port/MN/flow-rate after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            mn_str = user_input[CONF_MN].strip()
            try:
                _validate_mn(mn_str)
            except (ValueError, Exception):
                errors[CONF_MN] = "invalid_mn"
            else:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        CONF_HOST:      user_input[CONF_HOST].strip(),
                        CONF_PORT:      int(user_input[CONF_PORT]),
                        CONF_MN:        mn_str.upper().replace(":", ""),
                        CONF_FLOW_RATE: float(user_input[CONF_FLOW_RATE]),
                    },
                )
                await self.hass.config_entries.async_reload(self._entry.entry_id)
                return self.async_create_entry(title="", data={})

        current = self._entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST,      default=current.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT,      default=current.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_MN,        default=current.get(CONF_MN, "")): str,
                vol.Required(CONF_FLOW_RATE, default=current.get(CONF_FLOW_RATE, DEFAULT_FLOW_RATE)): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
