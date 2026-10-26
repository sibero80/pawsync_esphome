"""Constants for the Pawsync Smart Pet Feeder integration."""

DOMAIN = "pawsync"
NAME = "Pawsync Smart Pet Feeder"
VERSION = "1.0.1"

# Cloud API Endpoints
PAWSYNC_API_BASE = "https://smartapi.pawsync.com"
VESYNC_API_BASE = "https://smartapi.vesync.com"
DEFAULT_MODEL = "VS_WB_PFM_PPF-R361S-WUS_US"
MODEL_FAMILY = "PPF-R361S"

# Configuration Keys
CONF_ONBOARDING_MODE = "onboarding_mode"
MODE_CLOUD_ONBOARDING = "cloud_onboarding"
MODE_DIRECT_ESPHOME = "direct_esphome"

CONF_ACCOUNT_ID = "account_id"
CONF_TOKEN = "token"
CONF_COUNTRY_CODE = "country_code"
CONF_TIME_ZONE = "time_zone"
CONF_FEEDERS = "feeders"
CONF_SELECTED_FEEDER = "selected_feeder"
CONF_FLASH_METHOD = "flash_method"
CONF_HOST = "host"
CONF_SSID = "ssid"
CONF_WIFI_PASSWORD = "wifi_password"

# Flashing Methods
FLASH_METHOD_OTA = "wireless_ota"
FLASH_METHOD_WEBSERIAL = "webserial"
FLASH_METHOD_SKIP = "manual_skip"

# Frontend / Card
CARD_FILENAME = "pawsync-feeder-card.js"
CARD_URL_PATH = "/pawsync/pawsync-feeder-card.js"
CARD_VERSION = "1.2.0"

# OTA Staging Constants
DEFAULT_STAGING_PORT = 8000
DEV_PORT = 55555
HEADER_LEN = 129
PACE_INITIAL_PAUSE_SEC = 8.0
PACE_CHUNK_DELAY_SEC = 0.020
CHUNK_SIZE = 2048
MAX_FIRMWARE_SIZE = 1310720  # 1.25 MB (0x140000)

# Default Defaults
DEFAULT_COUNTRY_CODE = "US"
DEFAULT_TIME_ZONE = "America/New_York"
DEFAULT_NOISE_PSK = "2M4yBDYqWbBDSl3PIkccw2IkCUj5WIySqP8JHYVG7Mc="
