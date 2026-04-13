"""Constants for the Heiko Heat Pump integration."""

DOMAIN = "heiko_heatpump"

# Config entry keys
CONF_HOST      = "host"
CONF_PORT      = "port"
CONF_MN        = "mn"   # stored as hex string, e.g. "F4700C77F01A"
CONF_FLOW_RATE = "flow_rate_lps"  # water flow rate in L/s (for COP calculation)

# Default connection parameters
DEFAULT_PORT      = 8899
DEFAULT_HOST      = "192.168.0.82"

# Default flow rate: Neoheat Eko II 6 nominal = 0.29 L/s (from manual)
# Eko II 6=0.29, Eko II 9=0.43, Eko II 12=0.57, Eko II 15=0.714, Eko II 19=0.92
DEFAULT_FLOW_RATE = 0.29  # Eko II 6 nominal; change to 0.43 for 9kW, 0.57 for 12kW  # L/s

# Device info
MANUFACTURER   = "Heiko / Neoheat / ECOtouch"
MODEL          = "Heat Pump (USR-W600 bridge)"
