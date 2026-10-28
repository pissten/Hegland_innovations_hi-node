"""HI-node. Oppsettet lastes uten å trekke inn Home Assistant før noden starter."""

import logging
from pathlib import Path

from .const import DOMAIN, PLATFORMS

__all__ = ["DOMAIN", "PLATFORMS"]

_LOGGER = logging.getLogger(__name__)
_OVERVIEW_URL = "/hi_node_static/device-groups.js?v=7"


async def async_setup(hass, config):
    """Registrer visningen som deler enhetssiden i Dør, Lys og Ovn."""
    await _async_register_overview(hass)
    return True


async def _async_register_overview(hass) -> None:
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    folder = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/hi_node_static", str(folder), False)]
        )
    except Exception:
        _LOGGER.exception("Kunne ikke legge ut enhetsvisningen")
    add_extra_js_url(hass, _OVERVIEW_URL)


async def async_setup_entry(hass, entry):
    """Start booking-hjernen og enhetene for ett anlegg."""
    from .runtime import HiNodeRuntime

    runtime = HiNodeRuntime(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    try:
        await runtime.async_start()
    except Exception:
        await runtime.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_drop_group_devices()
    return True


async def async_unload_entry(hass, entry):
    """Stopp anlegget når oppføringen fjernes."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        await runtime.async_stop()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
