"""Authentication and session tests for FusionSolar API client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.huawei_fusionsolar.fusion_solar_api import (
    FusionSolarApiClient,
    InvalidAuth,
)
from tests._fake_http import FakeClientSession, StubResponse

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _prelogin_routes(host: str) -> dict[tuple[str, str], list[StubResponse]]:
    return {
        ("GET", "/pvmswebsite/login/build/index.html"): [
            StubResponse(
                status=200,
                payload={"raw": "<html></html>"},
                url=f"https://{host}/pvmswebsite/login/build/index.html",
                headers={"content-type": "text/html; charset=UTF-8"},
            )
        ],
        ("GET", "/rest/pvms/web/security/v1/language"): [
            StubResponse(
                status=200,
                payload={"success": True},
                url=f"https://{host}/rest/pvms/web/security/v1/language",
            )
        ],
        ("GET", "/rest/dp/pvms/pvmswebsite/v1/deployment"): [
            StubResponse(
                status=200,
                payload={"success": True},
                url=f"https://{host}/rest/dp/pvms/pvmswebsite/v1/deployment",
            )
        ],
        ("GET", "/rest/dp/uidm/unisso/v1/is-check-verify-code"): [
            StubResponse(
                status=200,
                payload={"code": 0, "payload": {"verifyCodeCreate": False}},
                url=f"https://{host}/rest/dp/uidm/unisso/v1/is-check-verify-code",
            )
        ],
        ("POST", "/rest/pvms/web/server/v1/servermgmt/list-unforbidden-server"): [
            StubResponse(
                status=200,
                payload={"success": True},
                url=f"https://{host}/rest/pvms/web/server/v1/servermgmt/list-unforbidden-server",
            )
        ],
    }


@pytest.mark.asyncio
async def test_async_login_completes_sso_flow_and_sets_session() -> None:
    """Client should execute validate-user -> on-sso -> redirecturl flow."""
    fixture = json.loads((FIXTURES_DIR / "fusionsolar_login.json").read_text())

    session = FakeClientSession(
        {
            **_prelogin_routes(fixture["host"]),
            (
                "POST",
                "/rest/dp/uidm/unisso/v1/validate-user",
            ): [
                StubResponse(
                    status=200,
                    payload=fixture["validate_user"],
                    url=(
                        f"https://{fixture['host']}"
                        "/rest/dp/uidm/unisso/v1/validate-user"
                    ),
                )
            ],
            (
                "GET",
                "/rest/dp/uidm/auth/v1/on-sso-credential-ready",
            ): [
                StubResponse(
                    status=302,
                    payload={},
                    url=(
                        f"https://{fixture['host']}"
                        "/rest/dp/uidm/auth/v1/on-sso-credential-ready"
                    ),
                    headers={"location": f"https://{fixture['host']}/rest/pvms/web/login/v1/redirecturl?isFirst=false"},
                )
            ],
            (
                "GET",
                "/rest/pvms/web/login/v1/redirecturl",
            ): [
                StubResponse(
                    status=302,
                    payload={},
                    url=(
                        f"https://{fixture['host']}"
                        "/rest/pvms/web/login/v1/redirecturl"
                    ),
                    headers={"location": "/uniportal/pvmswebsite/assets/build/cloud.html"},
                )
            ],
        }
    )

    client = FusionSolarApiClient(
        session,
        username="user@example.com",
        password="secret",
        preferred_host=fixture["host"],
    )

    await client.async_login()

    assert client.effective_host == fixture["host"]
    assert client.get_debug_state()["session_valid"] is True


@pytest.mark.asyncio
async def test_async_get_plants_retries_after_401_with_relogin() -> None:
    """Client should relogin once and retry station-list after auth failure."""
    plants_payload = json.loads((FIXTURES_DIR / "fusionsolar_plants.json").read_text())
    login_fixture = json.loads((FIXTURES_DIR / "fusionsolar_login.json").read_text())

    session = FakeClientSession(
        {
            **_prelogin_routes("la5.fusionsolar.huawei.com"),
            (
                "POST",
                "/rest/pvms/web/station/v1/station/station-list",
            ): [
                StubResponse(
                    status=401,
                    payload={"code": 401, "message": "Unauthorized"},
                    url="https://la5.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
                ),
                StubResponse(
                    status=200,
                    payload=plants_payload,
                    url="https://la5.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
                ),
            ],
            (
                "POST",
                "/rest/dp/uidm/unisso/v1/validate-user",
            ): [
                StubResponse(
                    status=200,
                    payload=login_fixture["validate_user"],
                    url="https://la5.fusionsolar.huawei.com/rest/dp/uidm/unisso/v1/validate-user",
                )
            ],
            (
                "GET",
                "/rest/dp/uidm/auth/v1/on-sso-credential-ready",
            ): [
                StubResponse(
                    status=302,
                    payload={},
                    url="https://la5.fusionsolar.huawei.com/rest/dp/uidm/auth/v1/on-sso-credential-ready",
                    headers={"location": "https://la5.fusionsolar.huawei.com/rest/pvms/web/login/v1/redirecturl?isFirst=false"},
                )
            ],
            (
                "GET",
                "/rest/pvms/web/login/v1/redirecturl",
            ): [
                StubResponse(
                    status=302,
                    payload={},
                    url="https://la5.fusionsolar.huawei.com/rest/pvms/web/login/v1/redirecturl",
                    headers={"location": "/uniportal/pvmswebsite/assets/build/cloud.html"},
                )
            ],
        }
    )

    client = FusionSolarApiClient(
        session,
        username="user@example.com",
        password="secret",
    )

    plants = await client.async_get_plants()

    assert len(plants) == 2
    assert plants[0].plant_id == "NE=10000001"
    assert session.calls.count(("POST", "/rest/dp/uidm/unisso/v1/validate-user")) == 1


@pytest.mark.asyncio
async def test_async_login_raises_invalid_auth() -> None:
    """Invalid auth payload must raise InvalidAuth."""
    session = FakeClientSession(
        {
            **_prelogin_routes("la5.fusionsolar.huawei.com"),
            (
                "POST",
                "/rest/dp/uidm/unisso/v1/validate-user",
            ): [
                StubResponse(
                    status=200,
                    payload={"code": "100001", "message": "password invalid"},
                    url="https://la5.fusionsolar.huawei.com/rest/dp/uidm/unisso/v1/validate-user",
                )
            ]
        }
    )

    client = FusionSolarApiClient(
        session,
        username="user@example.com",
        password="secret",
    )

    with pytest.raises(InvalidAuth):
        await client.async_login()
