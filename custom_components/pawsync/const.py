"""Constants for the Pawsync Smart Pet Feeder integration."""

DOMAIN = "pawsync"
NAME = "Pawsync Smart Pet Feeder"
VERSION = "1.3.0"

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
CARD_VERSION = "1.3.0"

# Unit System Preferences
CONF_UNIT_SYSTEM = "unit_system"
UNIT_SYSTEM_METRIC = "metric"
UNIT_SYSTEM_IMPERIAL = "imperial"
UNIT_SYSTEM_AUTO = "auto"

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
# Deprecated: Static legacy fallback retired in v1.1.3; all setups must use generate_noise_psk()
DEFAULT_NOISE_PSK = None

# Factory Backup & Recovery Constants
BACKUP_HTTP_PORT = 8088
DEFAULT_BACKUP_DIR = "pawsync_backups"
BACKUP_STATUS_BACKED_UP = "backed_up"
BACKUP_STATUS_PENDING = "pending"
BACKUP_STATUS_SLOT_OVERWRITTEN = "slot_overwritten"
BACKUP_STATUS_UNAVAILABLE = "unavailable"


def generate_noise_psk() -> str:
    """Generate a unique cryptographically secure 32-byte base64 Noise PSK."""
    import base64
    import secrets
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def generate_ota_password() -> str:
    """Generate a secure random OTA password for new device installations."""
    import secrets
    return secrets.token_urlsafe(16)

