"""Parsing tests for FusionSolar API payload normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.huawei_fusionsolar.fusion_solar_api import FusionSolarApiClient
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
async def test_async_get_plants_parses_station_list() -> None:
    """Plant list should normalize station DNs and names."""
    plants_payload = json.loads((FIXTURES_DIR / "fusionsolar_plants.json").read_text())

    session = FakeClientSession(
        {
            **_prelogin_routes("la5.fusionsolar.huawei.com"),
            (
                "POST",
                "/rest/pvms/web/station/v1/station/station-list",
            ): [
                StubResponse(
                    status=200,
                    payload=plants_payload,
                    url="https://la5.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
                )
            ],
            (
                "POST",
                "/rest/dp/uidm/unisso/v1/validate-user",
            ): [
                StubResponse(
                    status=200,
                    payload={
                        "code": 0,
                        "payload": {
                            "ticket": "ST-example-ticket",
                            "redirectURL": "/rest/dp/uidm/auth/v1/on-sso-credential-ready?ticket=ST-example-ticket",
                        },
                    },
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

    client = FusionSolarApiClient(session, username="u", password="p")
    plants = await client.async_get_plants()

    assert [plant.plant_id for plant in plants] == ["NE=10000001", "NE=10000002"]
    assert [plant.plant_name for plant in plants] == ["Plant 1", "Plant 2"]


@pytest.mark.asyncio
async def test_async_get_metrics_normalizes_power_and_energy() -> None:
    """KPI payload should normalize currentPower(kW) -> W and expose kWh fields."""
    fixture = json.loads((FIXTURES_DIR / "fusionsolar_metrics.json").read_text())

    session = FakeClientSession(
        {
            **_prelogin_routes("la5.fusionsolar.huawei.com"),
            (
                "GET",
                "/rest/pvms/web/station/v1/overview/station-real-kpi",
            ): [
                StubResponse(
                    status=200,
                    payload=fixture,
                    url="https://la5.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/station-real-kpi",
                )
            ],
            (
                "POST",
                "/rest/dp/uidm/unisso/v1/validate-user",
            ): [
                StubResponse(
                    status=200,
                    payload={
                        "code": 0,
                        "payload": {
                            "ticket": "ST-example-ticket",
                            "redirectURL": "/rest/dp/uidm/auth/v1/on-sso-credential-ready?ticket=ST-example-ticket",
                        },
                    },
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

    client = FusionSolarApiClient(session, username="u", password="p")
    snapshot = await client.async_get_metrics("NE=10000001")

    assert snapshot.plant_id == "NE=10000001"
    assert snapshot.power_w == 190
    assert snapshot.energy_today_kwh == 2.91
    assert snapshot.energy_month_kwh == 105.62
    assert snapshot.energy_year_kwh == 105.62
    assert snapshot.energy_total_kwh == 105.62
