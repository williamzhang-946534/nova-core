from pathlib import Path

from arvuno_core.robots.models import RobotCapabilityName
from tests.test_robot_safety_chain import HEADERS, robot_environment


def test_robot_management_api_requires_authentication(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        response = environment.client.get(f"/api/robots/{environment.robot_id}/consents")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_web_console_can_manage_capability_governance(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        desktop_only = environment.client.post(
            f"/api/robots/{environment.robot_id}/capabilities/navigate_to/governance",
            headers=HEADERS,
            json={"enabled": True},
        )
        assert desktop_only.status_code == 409
        assert desktop_only.json()["error"]["code"] == "ROBOT_CAPABILITY_GOVERNANCE_INVALID"

        enabled = environment.client.post(
            f"/api/robots/{environment.robot_id}/capabilities/speak/governance",
            headers=HEADERS,
            json={"enabled": True},
        )
        assert enabled.status_code == 200
        capability = next(item for item in enabled.json()["data"] if item["capability"] == "speak")
        assert capability["enabled"] is True
        assert capability["approved"] is False
        assert capability["executable"] is False

        disabled = environment.client.post(
            f"/api/robots/{environment.robot_id}/capabilities/speak/governance",
            headers=HEADERS,
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        capability = next(item for item in disabled.json()["data"] if item["capability"] == "speak")
        assert capability["enabled"] is False
        assert capability["executable"] is False


def test_web_console_can_grant_list_and_revoke_robot_consents(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        granted = environment.client.post(
            f"/api/robots/{environment.robot_id}/consents",
            headers=HEADERS,
            json={
                "capability": "speak",
                "data_category": "speaker",
                "space_id": environment.space_id,
                "grant_source": "web-console",
                "granted_by": "console-user",
            },
        )
        assert granted.status_code == 201
        consent = granted.json()
        assert consent["status"] == "granted"
        assert consent["space_id"] == environment.space_id

        active = environment.client.get(
            f"/api/robots/{environment.robot_id}/consents",
            headers=HEADERS,
            params={"active_only": "true"},
        )
        assert active.status_code == 200
        assert [item["id"] for item in active.json()] == [consent["id"]]

        agent_query = environment.client.post(
            "/api/tools/robot_consents/execute",
            headers=HEADERS,
            json={
                "input": {
                    "robot_id": environment.robot_id,
                    "capability": RobotCapabilityName.SPEAK.value,
                    "active_only": True,
                }
            },
        )
        assert agent_query.status_code == 200
        output = agent_query.json()["data"]["output"]
        assert output["robot_id"] == environment.robot_id
        assert [item["id"] for item in output["consents"]] == [consent["id"]]

        revoked = environment.client.post(
            f"/api/robots/{environment.robot_id}/consents/{consent['id']}/revoke",
            headers=HEADERS,
            json={"revoked_by": "console-user"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        remaining = environment.client.get(
            f"/api/robots/{environment.robot_id}/consents",
            headers=HEADERS,
            params={"active_only": "true"},
        )
        assert remaining.status_code == 200
        assert remaining.json() == []


def test_legacy_robot_write_endpoints_remain_locked(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        requests = [
            (f"/api/robots/{environment.robot_id}/enable", {}),
            (
                f"/api/robots/{environment.robot_id}/task-requests",
                {
                    "capability": "speak",
                    "parameters": {"text": "bypass"},
                    "requested_by": "console-user",
                    "origin_type": "user",
                    "confirmed": True,
                    "idempotency_key": "management-lock-01",
                },
            ),
            ("/api/robots/task-requests/request-id/confirm", {"confirmed": True}),
            (
                "/api/robots/task-requests/request-id/cancel",
                {"cancelled_by": "console-user"},
            ),
        ]

        for path, payload in requests:
            response = environment.client.post(path, headers=HEADERS, json=payload)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"
