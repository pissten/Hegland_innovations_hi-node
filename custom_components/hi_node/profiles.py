"""Profilkatalog og utfylling av ESPHome-oppsett."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml


def profiles_dir() -> Path:
    """Profilene følger komponenten, så de er med når mappa kopieres inn i noden."""
    return Path(__file__).resolve().parent / "profiles"


def load_manifest() -> dict:
    """Valgene som oppsettsskjemaet viser."""
    with (profiles_dir() / "manifest.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def profile_by_id(profile_id: str) -> dict:
    for item in load_manifest()["profiles"]:
        if item["id"] == profile_id:
            return item
    raise KeyError(profile_id)


_FOLD = str.maketrans(
    {
        "æ": "ae",
        "Æ": "Ae",
        "ø": "o",
        "Ø": "O",
        "å": "a",
        "Å": "A",
        "ä": "a",
        "ö": "o",
        "é": "e",
    }
)


def slugify(name: str) -> str:
    """Anleggsnavn til enhetsnavn. Væmt blir vaemt."""
    text = name.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "anlegg"


def entity_id_for(device_name: str, output: str) -> str:
    """Samme navnemønster som ESPHome bruker i Home Assistant."""
    return f"switch.{device_name.replace('-', '_')}_{output}"


def device_name_for(slug: str, index: int = 1) -> str:
    base = f"hi-{slug}"[:24].strip("-")
    if index <= 1:
        return base
    suffix = f"-{index}"
    return f"{base[: 24 - len(suffix)]}{suffix}"


def render_profile(
    profile_id: str,
    device_name: str,
    friendly_name: str,
    api_key: str,
    ota_password: str,
    ap_password: str,
    static_ip: str | None = None,
    gateway: str | None = None,
    subnet: str | None = None,
) -> str:
    """Fyll profilen med navn og nye nøkler. LAN står foran WiFi."""
    template_path = profiles_dir() / f"{profile_id}.yaml"
    text = template_path.read_text(encoding="utf-8")
    manual = _manual_ip(static_ip, gateway, subnet)
    ap_ssid = f"{device_name} fallback"[:32]
    replacements = {
        "__DEVICE_NAME__": device_name,
        "__FRIENDLY_NAME__": friendly_name.replace('"', "'"),
        "__API_KEY__": api_key,
        "__OTA_PASSWORD__": ota_password,
        "__AP_SSID__": ap_ssid,
        "__AP_PASSWORD__": ap_password,
        "__MANUAL_IP__": manual,
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    return text


def _manual_ip(static_ip: str | None, gateway: str | None, subnet: str | None) -> str:
    values = [static_ip or "", gateway or "", subnet or ""]
    if not any(values):
        return ""
    if not all(values):
        raise ValueError("static_ip")
    return (
        "  manual_ip:\n"
        f"    static_ip: {static_ip}\n"
        f"    gateway: {gateway}\n"
        f"    subnet: {subnet}\n"
    )
