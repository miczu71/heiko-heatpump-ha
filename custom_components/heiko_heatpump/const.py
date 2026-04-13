"""Constants for the Heiko Heat Pump integration."""

DOMAIN = "heiko_heatpump"

# Config entry keys
CONF_HOST      = "host"
CONF_PORT      = "port"
CONF_MN        = "mn"   # stored as hex string, e.g. "F4700C77F01A"

# Default connection parameters
DEFAULT_PORT   = 8899
DEFAULT_HOST   = "192.168.0.82"

# Device info
MANUFACTURER   = "Heiko / Neoheat / ECOtouch"
MODEL          = "Heat Pump (USR-W600 bridge)"
