"""HI-node. Oppsettet lastes uten å trekke inn Home Assistant før noden starter."""

from .const import DOMAIN, PLATFORMS

__all__ = ["DOMAIN", "PLATFORMS"]


async def async_setup(hass, config):
    """Integrasjonen startes bare fra oppsettsflyten."""
    return True


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
