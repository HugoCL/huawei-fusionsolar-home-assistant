"""Async client for Huawei FusionSolar private endpoints."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import aiohttp
from yarl import URL

from .const import DEFAULT_HOST, DEFAULT_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)

VALIDATE_USER_PATH = "/rest/dp/uidm/unisso/v1/validate-user"
SSO_READY_PATH = "/rest/dp/uidm/auth/v1/on-sso-credential-ready"
LOGIN_REDIRECT_PATH = "/rest/pvms/web/login/v1/redirecturl"
LOGIN_PAGE_PATH = "/pvmswebsite/login/build/index.html"
VERIFY_CODE_CHECK_PATH = "/rest/dp/uidm/unisso/v1/is-check-verify-code"
LIST_UNFORBIDDEN_SERVER_PATH = (
    "/rest/pvms/web/server/v1/servermgmt/list-unforbidden-server"
)

KEEPALIVE_PATH = "/rest/dpcloud/auth/v1/keep-alive"
STATION_LIST_PATH = "/rest/pvms/web/station/v1/station/station-list"
STATION_REAL_KPI_PATH = "/rest/pvms/web/station/v1/overview/station-real-kpi"

LOGIN_SERVICE_PARAM = "/rest/dp/uidm/auth/v1/on-sso-credential-ready"
LOGIN_APP_ID = "smartpvms"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

LOGIN_ERROR_CODES = {
    "401",
    "403",
    "100001",
    "100002",
    "USER_PASSWORD_ERROR",
    "USER_NOT_EXIST",
}

PLANT_ID_KEYS = (
    "dn",
    "stationDn",
    "stationCode",
    "plantId",
    "stationId",
    "id",
)

PLANT_NAME_KEYS = (
    "name",
    "stationName",
    "plantName",
    "stationAlias",
)

POWER_KEYS = (
    "currentPower",
    "activePower",
    "realTimePower",
    "power",
    "pac",
)

POWER_UNIT_KEYS = (
    "powerUnit",
    "activePowerUnit",
    "onlyInverterPowerUnit",
    "unit",
)

ENERGY_TODAY_KEYS = (
    "dailyEnergy",
    "energyToday",
    "dayEnergy",
    "todayEnergy",
)

ENERGY_MONTH_KEYS = (
    "monthEnergy",
    "energyMonth",
    "monthlyEnergy",
)

ENERGY_YEAR_KEYS = (
    "yearEnergy",
    "energyYear",
    "annualEnergy",
)

ENERGY_TOTAL_KEYS = (
    "cumulativeEnergy",
    "totalEnergy",
    "energyTotal",
    "accumulatedEnergy",
    "lifetimeEnergy",
)

CSRF_KEYS = ("csrf", "csrfToken", "token", "xsrftoken")


class FusionSolarApiError(Exception):
    """Base API error."""


class CannotConnect(FusionSolarApiError):
    """Raised when connection cannot be established."""


class InvalidAuth(FusionSolarApiError):
    """Raised when credentials are invalid or session is unauthorized."""


class RateLimited(FusionSolarApiError):
    """Raised when the server rate-limits requests."""


class EndpointSchemaChanged(FusionSolarApiError):
    """Raised when endpoint response does not match expected schema."""


@dataclass(slots=True, frozen=True)
class PlantInfo:
    """Normalized plant metadata."""

    plant_id: str
    plant_name: str


@dataclass(slots=True, frozen=True)
class PlantSnapshot:
    """Normalized plant telemetry snapshot."""

    plant_id: str
    plant_name: str
    power_w: float
    energy_today_kwh: float
    energy_month_kwh: float
    energy_year_kwh: float
    energy_total_kwh: float
    updated_at_utc: datetime


@dataclass(slots=True)
class _RawResponse:
    """Internal HTTP response wrapper."""

    status: int
    payload: Any
    url: URL
    headers: dict[str, str]


class FusionSolarApiClient:
    """Client wrapper around FusionSolar private web endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        username: str | None = None,
        password: str | None = None,
        preferred_host: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._preferred_host = _sanitize_host(preferred_host) if preferred_host else None
        self._effective_host = self._preferred_host or DEFAULT_HOST
        self._timeout_seconds = timeout_seconds
        self._verify_ssl = verify_ssl
        self._csrf_token: str | None = None
        self._session_valid = False
        self._recent_statuses: deque[dict[str, str | int]] = deque(maxlen=25)
        self._plant_names: dict[str, str] = {}

    @property
    def effective_host(self) -> str:
        """Return current effective host."""
        return self._effective_host

    def update_credentials(self, username: str, password: str) -> None:
        """Update credentials in memory."""
        self._username = username
        self._password = password

    def set_preferred_host(self, host: str | None) -> None:
        """Set a preferred host and update effective host when provided."""
        self._preferred_host = _sanitize_host(host) if host else None
        if self._preferred_host:
            self._effective_host = self._preferred_host

    def set_timeout_seconds(self, timeout_seconds: int) -> None:
        """Set request timeout in seconds."""
        self._timeout_seconds = timeout_seconds

    async def async_login(
        self,
        username: str | None = None,
        password: str | None = None,
        preferred_host: str | None = None,
    ) -> None:
        """Authenticate and bootstrap web session/cookies."""
        if username is not None:
            self._username = username
        if password is not None:
            self._password = password
        if preferred_host is not None:
            self.set_preferred_host(preferred_host)

        if not self._username or not self._password:
            raise InvalidAuth("Missing credentials")

        host_candidates = _dedupe(
            [self._preferred_host, self._effective_host, DEFAULT_HOST]
        )

        login_payload = {
            "username": self._username,
            "password": self._password,
            "verifycode": "",
        }

        last_error: Exception | None = None

        for host in host_candidates:
            if not host:
                continue

            await self._async_prelogin_probes(host)

            try:
                login_response = await self._request_raw(
                    "POST",
                    VALIDATE_USER_PATH,
                    host=host,
                    params={"service": LOGIN_SERVICE_PARAM},
                    json_data=login_payload,
                    extra_headers={"app-id": LOGIN_APP_ID},
                    allow_auth_retry=False,
                )
            except (CannotConnect, RateLimited) as err:
                last_error = err
                continue

            if not _payload_indicates_login_success(login_response.payload):
                if _payload_requires_verify_code(login_response.payload):
                    raise CannotConnect(
                        "FusionSolar requested verification code challenge"
                    )
                if _payload_indicates_invalid_auth(login_response.payload):
                    raise InvalidAuth("Invalid username or password")
                raise EndpointSchemaChanged("Unexpected login payload")

            ticket = _extract_login_ticket(login_response.payload, login_response.headers)
            if not ticket:
                raise EndpointSchemaChanged("Missing login ticket in FusionSolar response")

            redirect_address = (
                f"https://{host}{LOGIN_REDIRECT_PATH}?isFirst=false"
            )

            await self._request_raw(
                "GET",
                SSO_READY_PATH,
                host=host,
                params={
                    "ticket": ticket,
                    "redirectionAddress": redirect_address,
                },
                extra_headers={
                    "app-id": LOGIN_APP_ID,
                    "login-url-encode": "true",
                },
                allow_auth_retry=False,
            )

            await self._request_raw(
                "GET",
                LOGIN_REDIRECT_PATH,
                host=host,
                params={"isFirst": "false"},
                allow_auth_retry=False,
            )

            self._session_valid = True
            return

        if last_error:
            raise CannotConnect("Could not connect to FusionSolar") from last_error

        raise InvalidAuth("Authentication failed")

    async def _async_prelogin_probes(self, host: str) -> None:
        """Run lightweight pre-login endpoints to warm session cookies."""
        probes: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
            ("GET", VERIFY_CODE_CHECK_PATH, None),
            ("POST", LIST_UNFORBIDDEN_SERVER_PATH, {}),
        )
        for method, endpoint, payload in probes:
            try:
                await self._request_raw(
                    method,
                    endpoint,
                    host=host,
                    json_data=payload,
                    extra_headers={"app-id": LOGIN_APP_ID},
                    allow_auth_retry=False,
                )
            except Exception as err:  # noqa: BLE001 - best-effort probe
                LOGGER.debug("Pre-login probe failed (%s): %s", endpoint, err)

    async def async_refresh_session(self) -> None:
        """Refresh session and fallback to full relogin when needed."""
        if self._session_valid:
            try:
                response = await self._request_raw(
                    "GET",
                    KEEPALIVE_PATH,
                    allow_auth_retry=False,
                )
                if response.status < 400:
                    self._session_valid = True
                    return
            except (CannotConnect, RateLimited):
                pass
            except InvalidAuth:
                self._session_valid = False

        await self.async_login(
            username=self._username,
            password=self._password,
            preferred_host=self._preferred_host,
        )

    async def async_get_plants(self) -> list[PlantInfo]:
        """Fetch plant list from account."""
        if not self._session_valid:
            await self.async_refresh_session()

        response = await self._request_raw(
            "POST",
            STATION_LIST_PATH,
            json_data=_station_list_payload(),
        )
        plants = _parse_station_list(response.payload)
        if not plants:
            raise EndpointSchemaChanged("Unable to parse plants payload")

        self._plant_names = {plant.plant_id: plant.plant_name for plant in plants}
        return plants

    async def async_get_metrics(self, plant_id: str) -> PlantSnapshot:
        """Fetch normalized telemetry metrics for one plant."""
        if not self._session_valid:
            await self.async_refresh_session()

        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        params = {
            "stationDn": plant_id,
            "clientTime": str(now_ms),
            "timeZone": str(_timezone_offset_hours()),
            "_": str(now_ms),
        }

        response = await self._request_raw(
            "GET",
            STATION_REAL_KPI_PATH,
            params=params,
        )

        combined = response.payload
        power_w = _parse_power_w(combined)
        today_kwh = _parse_energy(combined, ENERGY_TODAY_KEYS)
        month_kwh = _parse_energy(combined, ENERGY_MONTH_KEYS)
        year_kwh = _parse_energy(combined, ENERGY_YEAR_KEYS)
        total_kwh = _parse_energy(combined, ENERGY_TOTAL_KEYS)

        if None in (power_w, today_kwh, month_kwh, year_kwh, total_kwh):
            raise EndpointSchemaChanged(
                f"Unable to parse metrics for plant_id={plant_id}"
            )

        return PlantSnapshot(
            plant_id=plant_id,
            plant_name=_extract_plant_name(combined)
            or self._plant_names.get(plant_id)
            or plant_id,
            power_w=power_w,
            energy_today_kwh=today_kwh,
            energy_month_kwh=month_kwh,
            energy_year_kwh=year_kwh,
            energy_total_kwh=total_kwh,
            updated_at_utc=datetime.now(UTC),
        )

    def get_debug_state(self) -> dict[str, Any]:
        """Return diagnostics-safe state."""
        return {
            "effective_host": self._effective_host,
            "preferred_host": self._preferred_host,
            "verify_ssl": self._verify_ssl,
            "timeout_seconds": self._timeout_seconds,
            "session_valid": self._session_valid,
            "username_masked": _mask_username(self._username),
            "known_plants": self._plant_names,
            "recent_statuses": list(self._recent_statuses),
        }

    async def _request_raw(
        self,
        method: str,
        endpoint: str,
        *,
        host: str | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        allow_auth_retry: bool = True,
    ) -> _RawResponse:
        """Perform one HTTP request and parse JSON when available."""
        request_host = host or self._effective_host
        url_obj = URL.build(scheme="https", host=request_host, path=endpoint)
        if params:
            url_obj = url_obj.update_query(params)

        headers = self._build_headers(endpoint, extra_headers, request_host)

        for attempt in range(2):
            try:
                response_ctx = self._session.request(
                    method,
                    str(url_obj),
                    json=json_data,
                    headers=headers,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
                    ssl=self._verify_ssl,
                )
                async with response_ctx as response:
                    payload = await _decode_payload(response)
                    raw = _RawResponse(
                        status=response.status,
                        payload=payload,
                        url=response.url,
                        headers={k.lower(): v for k, v in response.headers.items()},
                    )
            except TimeoutError as err:
                raise CannotConnect("Connection timeout") from err
            except aiohttp.ClientError as err:
                raise CannotConnect("Client error") from err

            self._record_status(endpoint, raw.status)
            self._apply_runtime_from_response(raw)
            self._extract_security_tokens(raw)

            if raw.status in (401, 403):
                self._session_valid = False
                if (
                    allow_auth_retry
                    and attempt == 0
                    and endpoint
                    not in {
                        VALIDATE_USER_PATH,
                        SSO_READY_PATH,
                        LOGIN_REDIRECT_PATH,
                    }
                    and self._username
                    and self._password
                ):
                    await self.async_refresh_session()
                    headers = self._build_headers(endpoint, extra_headers, request_host)
                    continue
                raise InvalidAuth("Unauthorized")

            if raw.status == 429:
                raise RateLimited("FusionSolar rate limit reached")

            if raw.status >= 500:
                raise CannotConnect(f"FusionSolar server error: {raw.status}")

            if raw.status >= 400:
                if endpoint == VALIDATE_USER_PATH:
                    raise InvalidAuth("Invalid username or password")
                raise CannotConnect(f"FusionSolar request failed: HTTP {raw.status}")

            content_type = raw.headers.get("content-type", "")
            if (
                raw.status == 200
                and endpoint.startswith("/rest/")
                and endpoint != LOGIN_REDIRECT_PATH
                and "text/html" in content_type
            ):
                if endpoint == VALIDATE_USER_PATH:
                    raise CannotConnect(
                        "FusionSolar returned HTML challenge page before login"
                    )
                raise InvalidAuth("Session invalid (received HTML on REST endpoint)")

            return raw

        raise CannotConnect("Request retry exhausted")

    def _record_status(self, endpoint: str, status: int) -> None:
        """Keep compact recent status history for diagnostics."""
        self._recent_statuses.append(
            {
                "endpoint": endpoint,
                "status": status,
                "at_utc": datetime.now(UTC).isoformat(),
            }
        )

    def _build_headers(
        self,
        endpoint: str,
        extra_headers: dict[str, str] | None,
        host: str,
    ) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": BROWSER_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }

        if endpoint.startswith("/rest/pvms/web/station/"):
            headers["x-non-renewal-session"] = "true"
            headers["x-timezone-offset"] = str(_timezone_offset_minutes())
            headers["roarand"] = _build_roarand_token()

        if endpoint in {
            VALIDATE_USER_PATH,
            SSO_READY_PATH,
            LOGIN_REDIRECT_PATH,
            VERIFY_CODE_CHECK_PATH,
            LIST_UNFORBIDDEN_SERVER_PATH,
        }:
            headers["Origin"] = f"https://{host}"
            headers["Referer"] = f"https://{host}{LOGIN_PAGE_PATH}"

        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token

        if extra_headers:
            headers.update(extra_headers)

        return headers

    def _apply_runtime_from_response(self, response: _RawResponse) -> None:
        """Update effective host after redirects."""
        if response.url.host:
            self._effective_host = response.url.host

    def _extract_security_tokens(self, response: _RawResponse) -> None:
        """Persist CSRF-like tokens when present in payload/headers."""
        header_token = response.headers.get("x-csrf-token")
        if header_token:
            self._csrf_token = header_token
            return

        payload = response.payload
        token = _find_string(payload, CSRF_KEYS)
        if token:
            self._csrf_token = token


def _sanitize_host(host: str) -> str:
    host = host.strip().lower()
    return host.replace("https://", "").replace("http://", "").rstrip("/")


def _dedupe(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _timezone_offset_minutes() -> int:
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def _timezone_offset_hours() -> int | float:
    minutes = _timezone_offset_minutes()
    hours = minutes / 60
    if float(hours).is_integer():
        return int(hours)
    return round(hours, 2)


def _local_midnight_epoch_ms() -> int:
    now_local = datetime.now().astimezone()
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight_local.timestamp() * 1000)


def _station_list_payload() -> dict[str, Any]:
    return {
        "curPage": 1,
        "pageSize": 100,
        "gridConnectedTime": "",
        "queryTime": _local_midnight_epoch_ms(),
        "timeZone": _timezone_offset_hours(),
        "sortId": "createTime",
        "sortDir": "DESC",
        "locale": "en_US",
    }


def _build_roarand_token() -> str:
    """Generate short request nonce used by FusionSolar web API."""
    now = int(datetime.now(UTC).timestamp() * 1000)
    return f"c-{now:x}"


def _payload_indicates_login_success(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    code = payload.get("code")
    if code is None:
        return False
    return str(code) == "0"


def _payload_indicates_invalid_auth(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    code = payload.get("code") or payload.get("errorCode")
    if code is not None and str(code) in LOGIN_ERROR_CODES:
        return True

    msg = str(payload.get("message") or payload.get("msg") or "").lower()
    if "password" in msg and ("wrong" in msg or "invalid" in msg or "error" in msg):
        return True

    return False


def _payload_requires_verify_code(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("payload")
    if not isinstance(data, dict):
        return False
    return bool(data.get("verifyCodeCreate"))


def _extract_login_ticket(payload: Any, headers: dict[str, str]) -> str | None:
    """Extract SSO ticket from login payload or response headers."""
    if isinstance(payload, dict):
        data = payload.get("payload")
        if isinstance(data, dict):
            ticket = _to_str(data.get("ticket"))
            if ticket:
                return ticket
            redirect_url = _to_str(data.get("redirectURL"))
            ticket = _extract_ticket_from_url(redirect_url)
            if ticket:
                return ticket

    header_redirect = headers.get("redirect_url") or headers.get("location")
    return _extract_ticket_from_url(header_redirect)


def _extract_ticket_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    ticket_values = query.get("ticket")
    if ticket_values:
        return ticket_values[0]
    return None


async def _decode_payload(response: aiohttp.ClientResponse) -> Any:
    """Decode JSON payload; fallback to text and best-effort JSON parsing."""
    try:
        return await response.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError):
        body = await response.text()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}


def _parse_station_list(payload: Any) -> list[PlantInfo]:
    """Extract plant list from station-list response payload."""
    data = _extract_data(payload)
    entries = data.get("list") if isinstance(data, dict) else None

    plants: list[PlantInfo] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            plant_id = _to_str(_find_value_by_keys(entry, PLANT_ID_KEYS))
            if not plant_id:
                continue
            plant_name = _to_str(_find_value_by_keys(entry, PLANT_NAME_KEYS)) or plant_id
            plants.append(PlantInfo(plant_id=plant_id, plant_name=plant_name))

    if plants:
        return plants

    # Fallback for unknown payload variants.
    return _parse_plants_fallback(payload)


def _parse_plants_fallback(payload: Any) -> list[PlantInfo]:
    entries = _walk_payload_entries(payload)
    plants: dict[str, PlantInfo] = {}

    for entry in entries:
        plant_id_value = _find_value_by_keys(entry, PLANT_ID_KEYS)
        plant_name_value = _find_value_by_keys(entry, PLANT_NAME_KEYS)
        plant_id = _to_str(plant_id_value)
        if not plant_id:
            continue
        plant_name = _to_str(plant_name_value) or plant_id
        plants[plant_id] = PlantInfo(plant_id=plant_id, plant_name=plant_name)

    return list(plants.values())


def _walk_payload_entries(payload: Any) -> list[dict[str, Any]]:
    """Return all dictionary entries nested in payload."""
    entries: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        entries.append(payload)
        for value in payload.values():
            entries.extend(_walk_payload_entries(value))
    elif isinstance(payload, list):
        for item in payload:
            entries.extend(_walk_payload_entries(item))
    return entries


def _extract_data(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _extract_plant_name(payload: Any) -> str | None:
    data = _extract_data(payload)
    value = _find_value_by_keys(data, PLANT_NAME_KEYS)
    return _to_str(value) or None


def _parse_power_w(payload: Any) -> float | None:
    data = _extract_data(payload)
    raw_value, key = _find_numeric_value(data, POWER_KEYS)
    if raw_value is None:
        return None

    unit_value = _find_value_by_keys(data, POWER_UNIT_KEYS)
    unit = _to_str(unit_value).lower()
    key_lower = key.lower() if key else ""

    if unit == "kw" or key_lower in {"currentpower", "inverterpower"}:
        return raw_value * 1000
    if unit == "mw":
        return raw_value * 1_000_000
    if unit == "w":
        return raw_value

    # KPI endpoint uses kW for currentPower.
    if key_lower in {"currentpower", "activepower", "realtimepower", "power", "pac"}:
        if abs(raw_value) < 1000:
            return raw_value * 1000

    return raw_value


def _parse_energy(payload: Any, candidate_keys: tuple[str, ...]) -> float | None:
    data = _extract_data(payload)
    value, _ = _find_numeric_value(data, candidate_keys)
    return value


def _find_string(payload: Any, candidate_keys: tuple[str, ...]) -> str | None:
    value = _find_value_by_keys(payload, candidate_keys)
    converted = _to_str(value)
    return converted or None


def _find_numeric_value(payload: Any, candidate_keys: tuple[str, ...]) -> tuple[float | None, str | None]:
    found = _find_value_by_keys(payload, candidate_keys, with_key=True)
    if found is None:
        return None, None
    value, key = found
    return _to_float(value), key


def _find_value_by_keys(
    payload: Any,
    candidate_keys: tuple[str, ...],
    *,
    with_key: bool = False,
) -> Any:
    key_lookup = {key.lower() for key in candidate_keys}

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in key_lookup and value not in (None, ""):
                return (value, key) if with_key else value
        for value in payload.values():
            found = _find_value_by_keys(value, candidate_keys, with_key=with_key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_value_by_keys(item, candidate_keys, with_key=with_key)
            if found is not None:
                return found

    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        if text == "--":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    return None


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mask_username(username: str | None) -> str | None:
    if not username:
        return None
    if len(username) <= 2:
        return "*" * len(username)
    return f"{username[:2]}***{username[-1]}"
