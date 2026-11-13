from dataclasses import dataclass
from enum import StrEnum

from arvuno_core.robots.models import RobotCapabilityName, RobotRiskLevel


class RobotProfileName(StrEnum):
    DESKTOP_ROBOT = "desktop_robot"
    MOBILE_ROBOT = "mobile_robot"
    LEGACY_MOCK_MOBILE = "legacy_mock_mobile"


@dataclass(frozen=True)
class RobotCapabilityPolicy:
    capability: RobotCapabilityName
    risk_level: RobotRiskLevel
    default_enabled: bool = False
    requires_confirmation: bool = True
    permission: str = "robot_capability_admin"
    spatial_scope: str = "desktop_workspace"
    data_categories: tuple[str, ...] = ()
    safety_approval_required: bool = True


@dataclass(frozen=True)
class RobotProfile:
    name: RobotProfileName
    capabilities: dict[RobotCapabilityName, RobotCapabilityPolicy]
    governance_enabled: bool = True

    def supports(self, capability: RobotCapabilityName) -> bool:
        return capability in self.capabilities

    def policy(self, capability: RobotCapabilityName) -> RobotCapabilityPolicy | None:
        return self.capabilities.get(capability)


def _policy(
    capability: RobotCapabilityName,
    risk_level: RobotRiskLevel,
    *,
    data_categories: tuple[str, ...] = (),
    spatial_scope: str = "desktop_workspace",
) -> RobotCapabilityPolicy:
    return RobotCapabilityPolicy(
        capability=capability,
        risk_level=risk_level,
        data_categories=data_categories,
        spatial_scope=spatial_scope,
    )


_desktop_capabilities = {
    capability.capability: capability
    for capability in (
        _policy(RobotCapabilityName.REPORT_STATUS, "read_only", data_categories=("diagnostics",)),
        _policy(RobotCapabilityName.LOOK_AT, "medium_risk"),
        _policy(
            RobotCapabilityName.OBSERVE_SCENE,
            "read_only",
            data_categories=("camera_image",),
        ),
        _policy(RobotCapabilityName.REQUEST_SAFE_STOP, "read_only"),
        _policy(RobotCapabilityName.ENTER_IDLE_POSE, "medium_risk"),
        _policy(RobotCapabilityName.SPEAK, "low_risk", data_categories=("synthesized_speech",)),
        _policy(
            RobotCapabilityName.LISTEN,
            "read_only",
            data_categories=("microphone_audio",),
        ),
    )
}

_mobile_capabilities = {
    capability.capability: capability
    for capability in (
        _policy(
            RobotCapabilityName.NAVIGATE_TO,
            "medium_risk",
            spatial_scope="approved_navigation_areas",
        ),
        _policy(RobotCapabilityName.OBSERVE, "read_only", data_categories=("camera_image",)),
        _policy(RobotCapabilityName.INSPECT, "read_only", data_categories=("camera_image",)),
        _policy(RobotCapabilityName.SPEAK, "low_risk", data_categories=("synthesized_speech",)),
        _policy(
            RobotCapabilityName.LISTEN,
            "read_only",
            data_categories=("microphone_audio",),
        ),
        _policy(
            RobotCapabilityName.RETURN_TO_DOCK,
            "medium_risk",
            spatial_scope="approved_navigation_areas",
        ),
        _policy(
            RobotCapabilityName.CHARGE,
            "medium_risk",
            spatial_scope="dock",
        ),
        _policy(RobotCapabilityName.REPORT_STATUS, "read_only", data_categories=("diagnostics",)),
    )
}


ROBOT_PROFILES: dict[RobotProfileName, RobotProfile] = {
    RobotProfileName.DESKTOP_ROBOT: RobotProfile(
        RobotProfileName.DESKTOP_ROBOT,
        _desktop_capabilities,
    ),
    RobotProfileName.MOBILE_ROBOT: RobotProfile(
        RobotProfileName.MOBILE_ROBOT,
        _mobile_capabilities,
        governance_enabled=False,
    ),
    RobotProfileName.LEGACY_MOCK_MOBILE: RobotProfile(
        RobotProfileName.LEGACY_MOCK_MOBILE,
        _mobile_capabilities,
    ),
}


def get_robot_profile(name: RobotProfileName | str | None) -> RobotProfile:
    profile_name = RobotProfileName(name or RobotProfileName.DESKTOP_ROBOT)
    return ROBOT_PROFILES[profile_name]


def infer_robot_profile(
    *,
    profile: RobotProfileName | str | None,
    adapter_id: str,
    model: str,
) -> RobotProfileName:
    if profile is not None:
        return RobotProfileName(profile)
    if "desktop" in model.lower() or adapter_id == "mock_robot":
        return RobotProfileName.DESKTOP_ROBOT
    return RobotProfileName.MOBILE_ROBOT


__all__ = [
    "ROBOT_PROFILES",
    "RobotCapabilityPolicy",
    "RobotProfile",
    "RobotProfileName",
    "get_robot_profile",
    "infer_robot_profile",
]
