"""Home Assistant demo acceptance for Arvuno Core.

Two phases, run in order:

1. Verify Home Assistant itself (virtual demo entities):
       python scripts/acceptance/ha_demo_acceptance.py ha

2. Verify Arvuno's Home Assistant Adapter (requires an Arvuno backend configured
   with the same HA URL/token/allowlist):
       python scripts/acceptance/ha_demo_acceptance.py arvuno [--write]

Environment variables:
    HA_URL               Home Assistant base URL, e.g. http://localhost:8123
    HA_TOKEN             Home Assistant long-lived access token
    ARVUNO_BASE_URL      Arvuno backend URL, default http://127.0.0.1:8000
    ARVUNO_API_TOKEN     Arvuno API token

The script never writes unless `--write` is passed. Read-only checks are the
default and are safe against a demo instance.
"""

from __future__ import annotations

import argparse
import os

import httpx

DEMO_LIGHT = "light.bed_light"
DEMO_ENTITIES = {
    DEMO_LIGHT,
    "light.ceiling_lights",
    "light.kitchen_lights",
    "switch.ac",
}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f" | {name} | {detail}")


def require_env(*names: str) -> dict[str, str]:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        raise SystemExit(2)
    return {name: os.environ[name] for name in names}


def verify_home_assistant() -> int:
    env = require_env("HA_URL", "HA_TOKEN")
    base = env["HA_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {env['HA_TOKEN']}"}

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        health = client.get(f"{base}/api/", headers=headers)
        check(
            "Home Assistant API is reachable",
            health.status_code == 200
            and health.json().get("message") == "API running.",
            f"status={health.status_code}",
        )

        states = client.get(f"{base}/api/states", headers=headers)
        check(
            "state API authorized",
            states.status_code == 200,
            f"status={states.status_code}",
        )
        if states.status_code != 200:
            print(f"\n{len(results) - 1}/{len(results)} passed")
            return 1

        entities = {item["entity_id"]: item for item in states.json()}
        missing = sorted(DEMO_ENTITIES - set(entities))
        check(
            "demo entities are present",
            not missing,
            f"missing={missing}"
            if missing
            else f"found={len(DEMO_ENTITIES)} demo entities",
        )

        light = entities.get(DEMO_LIGHT)
        check(
            "demo light exposes a readable state",
            light is not None and light.get("state") in {"on", "off"},
            f"state={light.get('state') if light else None}",
        )

    failed = [item for item in results if not item[1]]
    print(f"\nHA checks: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def verify_arvuno(write: bool) -> int:
    env = require_env("HA_URL", "ARVUNO_API_TOKEN")
    base = (env.get("ARVUNO_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {env['ARVUNO_API_TOKEN']}"}

    with httpx.Client(base_url=base, timeout=60.0, trust_env=False) as client:
        settings = client.get("/api/settings", headers=headers).json()["data"][
            "runtime"
        ]
        check(
            "Arvuno is configured for Home Assistant",
            settings.get("home_assistant_configured") is True,
            f"configured={settings.get('home_assistant_configured')}",
        )
        check(
            "Home Assistant writes stay disabled by default",
            settings.get("home_assistant_write_enabled") is False or write,
            f"write_enabled={settings.get('home_assistant_write_enabled')}",
        )

        devices = client.get("/api/devices", headers=headers).json()["data"]
        ha_device = next(
            (device for device in devices if device.get("external_id") == DEMO_LIGHT),
            None,
        )
        check(
            "demo light is projected into Arvuno",
            ha_device is not None,
            f"external_id={DEMO_LIGHT}",
        )
        if ha_device is None:
            print(
                f"\nArvuno checks: {len(results) - sum(not item[1] for item in results)}/{len(results)} passed"
            )
            return 1

        device_id = ha_device["id"]
        state = client.get(f"/api/devices/{device_id}/state", headers=headers).json()[
            "data"
        ]
        check(
            "Arvuno reads the demo light state",
            state.get("state") in {"on", "off"},
            f"state={state.get('state')}",
        )

        environment = client.get("/api/environment", headers=headers).json()["data"]
        check(
            "environment includes the projected device",
            device_id in environment.get("environment", {}).get("devices", {}),
            "device present in environment context",
        )

        if not write:
            print(
                "\nRead-only phase complete. Re-run with --write after enabling writes."
            )
            print(
                "(Arvuno write operations require ARVUNO_HOME_ASSISTANT_WRITE_ENABLED=true)"
            )
        else:
            target = "off" if state.get("state") == "on" else "on"
            task = client.post(
                "/api/tasks",
                headers=headers,
                json={
                    "task_type": "device_control",
                    "title": f"HA demo {target}",
                    "steps": [
                        {
                            "name": f"set_{target}",
                            "tool_name": "control_device",
                            "input": {
                                "device_id": device_id,
                                "action": "turn_on" if target == "on" else "turn_off",
                                "expected_state": target,
                            },
                        }
                    ],
                },
            ).json()["data"]
            check(
                "control task completed",
                task.get("status") == "completed",
                task.get("status"),
            )
            detail = client.get(f"/api/tasks/{task['id']}", headers=headers).json()[
                "data"
            ]
            verified = (detail["executions"][0]["validation"] or {}).get("verified")
            check("control was verified", verified is True, f"verified={verified}")
            new_state = client.get(
                f"/api/devices/{device_id}/state", headers=headers
            ).json()["data"]
            check(
                "device reached the requested state",
                new_state.get("state") == target,
                new_state.get("state"),
            )

    failed = [item for item in results if not item[1]]
    print(f"\nArvuno checks: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ha", help="Verify Home Assistant demo entities")
    arvuno = subparsers.add_parser(
        "arvuno", help="Verify Arvuno Home Assistant Adapter"
    )
    arvuno.add_argument(
        "--write", action="store_true", help="Also run a verified control round-trip"
    )
    args = parser.parse_args()

    if args.command == "ha":
        return verify_home_assistant()
    return verify_arvuno(args.write)


if __name__ == "__main__":
    raise SystemExit(main())
