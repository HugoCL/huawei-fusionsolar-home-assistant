"""Constants for Huawei FusionSolar integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "huawei_fusionsolar"
PLATFORMS = ["sensor"]

DEFAULT_HOST = "la5.fusionsolar.huawei.com"
DEFAULT_VERIFY_SSL = True
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_POLL_INTERVAL_SECONDS = 60
MAX_BACKOFF_SECONDS = 600

CONF_HOST_OVERRIDE = "host_override"
CONF_VERIFY_SSL = "verify_ssl"
CONF_ENABLED_PLANT_IDS = "enabled_plant_ids"
CONF_POLL_INTERVAL_SECONDS = "poll_interval_seconds"
CONF_REQUEST_TIMEOUT_SECONDS = "request_timeout_seconds"
CONF_PLANT_INDEX = "plant_index"

OPTIONAL_DATA_KEYS = {
    CONF_HOST_OVERRIDE,
    CONF_VERIFY_SSL,
}

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS)
