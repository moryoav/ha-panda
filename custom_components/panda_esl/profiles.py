"""Supported PANDA ESL display profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PandaEslDeviceProfile:
    """Geometry and identity for a supported PANDA ESL variant."""

    key: str
    family: str
    tag_prefix: str
    model: str
    screen_size_inches: str
    width: int
    height: int

    @property
    def plane_byte_count(self) -> int:
        """Return bytes required for one column-major display plane."""
        return self.width * ((self.height + 7) // 8)


ETAG_525_PROFILE = PandaEslDeviceProfile(
    key="etag_525",
    family="525",
    tag_prefix="ETAG-525",
    model='2.13" BLE price tag',
    screen_size_inches="2.13",
    width=256,
    height=128,
)

ETAG_526_PROFILE = PandaEslDeviceProfile(
    key="etag_526",
    family="526",
    tag_prefix="ETAG-526",
    model='2.66" BLE price tag',
    screen_size_inches="2.66",
    width=296,
    height=152,
)

DEFAULT_DEVICE_PROFILE = ETAG_525_PROFILE
SUPPORTED_DEVICE_PROFILES = (ETAG_525_PROFILE, ETAG_526_PROFILE)
_PROFILES_BY_FAMILY = {profile.family: profile for profile in SUPPORTED_DEVICE_PROFILES}
_ETAG_ID_PATTERN = re.compile(
    r"^ETAG-(?P<family>525|526)[0-9A-F]{7}$",
    re.IGNORECASE,
)


def device_profile_from_tag_id(tag_id: str | None) -> PandaEslDeviceProfile | None:
    """Return the supported profile encoded by an advertised ETAG identifier."""
    if not tag_id:
        return None
    match = _ETAG_ID_PATTERN.fullmatch(tag_id.strip())
    if match is None:
        return None
    return _PROFILES_BY_FAMILY[match.group("family")]


def device_profile_from_names(
    *tag_ids: str | None,
) -> PandaEslDeviceProfile | None:
    """Return the first supported profile found in candidate device names."""
    for tag_id in tag_ids:
        profile = device_profile_from_tag_id(tag_id)
        if profile is not None:
            return profile
    return None
