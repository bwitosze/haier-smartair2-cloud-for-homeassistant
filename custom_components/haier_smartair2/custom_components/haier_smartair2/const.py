"""Constants for the Haier SmartAir2 integration.

This integration controls legacy Haier air conditioners (the ones paired with the
SmartAir2 app, not hOn) via two transports, chosen per device:

* CLOUD  — MQTT gateway (gw-gea-*.haieriot.net), for units whose dongle uses the
           newer encrypted local protocol (local control impossible).
* LOCAL  — direct TCP 56800, for older dongles that speak plaintext smartair2.

Protocol details were reverse engineered; see
https://github.com/bwitosze/haier-smartair2-cloud-for-homeassistant
"""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "haier_smartair2"
PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]

# --- config entry keys ---
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_LOCAL_IPS = "local_ips"  # comma-separated IPs to probe for local control
CONF_CLIENT_ID = "client_id"  # per-installation gateway client id (generated)

# --- cloud REST (login) ---
LOGIN_HOST = "uhome.haieriot.net"
LOGIN_PORT = 7263
APP_KEY = "c403cbfc780dd8a0ab68784bb6d3023b"
APP_ID = "MB-HKQHWBB-0001"
APP_VERSION = "3.2.1"
REST_CLIENT_ID = "4BC6E2ADBF06AD33FA18AC1190F3DED9"

# The gateway "app installation" clientId is generated per HA installation
# (any unique 32-hex value works; must be stable so Business topics don't collide
# between users). See generate_client_id() and the config entry CONF_CLIENT_ID.


def generate_client_id() -> str:
    """Random 32-hex gateway client id, one per HA installation."""
    import secrets

    return secrets.token_hex(16)

# --- gateway regions (master-gw domain). Only EU confirmed. ---
REGIONS = {
    "eu": "gw-gea-euro.haieriot.net",
    "us": "gw-gea-us.haieriot.net",
    "sg": "gw-gea-sg.haieriot.net",
}
DEFAULT_REGION = "eu"
MASTER_GW_PORT = 56815
LOCAL_PORT = 56800

# AES auth salt baked into the SDK (uss_encrpyt_user_auth)
AUTH_SALT = b"haier_sdk"

# --- HVAC mode maps (HA <-> device raw) ---
# smartair2 conditioning modes (V2 / cloud attribute 20200D raw values)
MODE_AUTO = 0
MODE_COOL = 1
MODE_HEAT = 2
MODE_FAN = 3
MODE_DRY = 4

# fan raw (V2): 0 HIGH, 1 MID, 2 LOW, 3 AUTO
FAN_HIGH = 0
FAN_MID = 1
FAN_LOW = 2
FAN_AUTO = 3

MIN_TEMP = 16
MAX_TEMP = 30
TEMP_STEP = 1.0

# polling
SCAN_INTERVAL_SECONDS = 30
# refresh the cloud access token proactively (TGT tickets are short-lived)
TOKEN_REFRESH_SECONDS = 30 * 60
