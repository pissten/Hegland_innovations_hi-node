"""Konstanter for HI-node."""

DOMAIN = "hi_node"
PLATFORMS = [
    "binary_sensor",
    "button",
    "calendar",
    "number",
    "select",
    "sensor",
    "switch",
]

ROLES = ("oven", "door", "light")

DEFAULT_MARGINS = {
    "oven": (90, 0),
    "door": (5, 10),
    "light": (5, 10),
}

ROLE_ALIASES = {
    "oven": "oven",
    "ovn": "oven",
    "heater": "oven",
    "door": "door",
    "dor": "door",
    "dør": "door",
    "light": "light",
    "lys": "light",
}

HEALTH_GAP = 60
HEATER_LIMIT_HOURS = 12
RESET_HOLD_SECONDS = 15
