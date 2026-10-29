// Deler HI-node-enhetssiden i boksene Anlegg, Dør, Lys, Ovn og Harvia.

const TITLES = {
  site: "Anlegg",
  door: "Dør",
  light: "Lys",
  oven: "Ovn",
  climate: "Termostat",
  harvia: "Harvia",
};
const BOX_ORDER = ["site", "door", "light", "oven", "climate", "harvia"];
const SUFFIX_GROUP = {
  booking_online: "site",
  mode: "site",
  booking_closed: "site",
  availability_duration: "site",
  closed_until: "site",
  override_minutes: "site",
  desired_door: "door",
  margin_door_pre: "door",
  margin_door_post: "door",
  override_door: "door",
  override_remaining_door: "door",
  desired_light: "light",
  margin_light_pre: "light",
  margin_light_post: "light",
  override_light: "light",
  override_remaining_light: "light",
  desired_oven: "oven",
  oven_status: "oven",
  margin_oven_pre: "oven",
  margin_oven_post: "oven",
  override_oven: "oven",
  override_remaining_oven: "oven",
  oven_mismatch: "oven",
  alarm_delay_seconds: "oven",
  grunnvarme: "oven",
  grunnvarme_schedule_active: "oven",
  grunnvarme_calendar: "oven",
  grunnvarme_hours_per_day: "oven",
  frostvakt: "oven",
  frost_c: "oven",
  frost_hysteresis_c: "oven",
  frost_off_c: "oven",
  booking_c: "climate",
  grunnvarme_c: "climate",
  default_c: "climate",
  harvia_remaining: "harvia",
  harvia_last_reset: "harvia",
  harvia_reset: "harvia",
};
const SUFFIX_ORDER = {
  site: [
    "booking_online",
    "mode",
    "booking_closed",
    "availability_duration",
    "closed_until",
    "override_minutes",
  ],
  door: [
    "override_door",
    "override_remaining_door",
    "desired_door",
    "margin_door_pre",
    "margin_door_post",
  ],
  light: [
    "override_light",
    "override_remaining_light",
    "desired_light",
    "margin_light_pre",
    "margin_light_post",
  ],
  oven: [
    "override_oven",
    "override_remaining_oven",
    "desired_oven",
    "oven_mismatch",
    "alarm_delay_seconds",
    "oven_status",
    "grunnvarme",
    "grunnvarme_schedule_active",
    "grunnvarme_calendar",
    "grunnvarme_hours_per_day",
    "frostvakt",
    "frost_c",
    "frost_hysteresis_c",
    "frost_off_c",
    "margin_oven_pre",
    "margin_oven_post",
  ],
  climate: ["linked_climate", "booking_c", "grunnvarme_c", "default_c"],
  harvia: ["harvia_remaining", "harvia_last_reset", "harvia_reset"],
};

function suffixOf(uniqueId) {
  const cut = String(uniqueId || "").indexOf("_");
  return cut < 0 ? "" : String(uniqueId).slice(cut + 1);
}

function isTemplate(value) {
  return Boolean(
    value &&
      typeof value === "object" &&
      value._$litType$ != null &&
      Array.isArray(value.strings) &&
      Array.isArray(value.values)
  );
}

function isHiNodeDevice(device) {
  return (device?.identifiers || []).some((item) => {
    const domain = Array.isArray(item) ? item[0] : "";
    const value = Array.isArray(item) ? String(item[1] || "") : "";
    return domain === "hi_node" && !/_(oven|door|light)$/.test(value);
  });
}

function isCardList(node) {
  if (!Array.isArray(node) || node.length === 0) {
    return false;
  }
  const templates = node.filter(isTemplate);
  return (
    templates.length > 0 &&
    templates.every((item) => item.strings.join("").includes("ha-device-entities-card"))
  );
}

function findCardList(node, seen = new Set()) {
  if (!node || typeof node !== "object" || seen.has(node)) {
    return null;
  }
  seen.add(node);
  if (isCardList(node)) {
    return node;
  }
  const children = isTemplate(node) ? node.values : Array.isArray(node) ? node : null;
  if (!children) {
    return null;
  }
  for (const child of children) {
    const found = findCardList(child, seen);
    if (found) {
      return found;
    }
  }
  return null;
}

function blankChildDevices(node, seen = new Set()) {
  if (!node || typeof node !== "object" || seen.has(node)) {
    return;
  }
  seen.add(node);
  if (isTemplate(node)) {
    node.values.forEach((value, index) => {
      if (isTemplate(value) && value.strings.join("").includes("ha-device-child-devices-card")) {
        node.values[index] = "";
      } else {
        blankChildDevices(value, seen);
      }
    });
    return;
  }
  if (Array.isArray(node)) {
    node.forEach((value) => blankChildDevices(value, seen));
  }
}

function classify(entity) {
  const suffix = suffixOf(entity.unique_id);
  if (SUFFIX_GROUP[suffix]) {
    return { group: SUFFIX_GROUP[suffix], suffix };
  }
  const id = entity.entity_id || "";
  const rules = [
    ["site", "booking_online", ["booking_svarer"]],
    ["site", "mode", ["_styring"]],
    ["site", "booking_closed", ["booking_stengt"]],
    ["site", "availability_duration", ["stengevarighet"]],
    ["site", "closed_until", ["stengt_til"]],
    ["site", "override_minutes", ["overstyringstid"]],
    ["door", "override_door", ["manuell_dor"]],
    ["door", "override_remaining_door", ["manuell_dor_gjenstar"]],
    ["light", "override_light", ["manuell_lys"]],
    ["light", "override_remaining_light", ["manuell_lys_gjenstar"]],
    ["oven", "override_oven", ["manuell_ovn"]],
    ["oven", "override_remaining_oven", ["manuell_ovn_gjenstar"]],
    ["oven", "oven_mismatch", ["ovn_avvik"]],
    ["oven", "alarm_delay_seconds", ["alarmforsinkelse"]],
    ["door", "desired_door", ["dor_skal"]],
    ["light", "desired_light", ["lys_skal"]],
    ["oven", "desired_oven", ["ovn_skal"]],
    ["climate", "booking_c", ["booking_temperatur"]],
    ["climate", "grunnvarme_c", ["grunnvarme_temperatur"]],
    ["climate", "default_c", ["standard_temperatur"]],
    ["door", "margin_door_pre", ["_dor_for"]],
    ["door", "margin_door_post", ["_dor_etter"]],
    ["light", "margin_light_pre", ["_lys_for"]],
    ["light", "margin_light_post", ["_lys_etter"]],
    ["oven", "margin_oven_pre", ["_ovn_for"]],
    ["oven", "margin_oven_post", ["_ovn_etter"]],
    ["oven", "grunnvarme_hours_per_day", ["grunnvarme_timer"]],
    ["oven", "grunnvarme_schedule_active", ["timeplan_aktiv_na"]],
    ["oven", "grunnvarme", ["grunnvarme"]],
    ["oven", "frost_hysteresis_c", ["frostvakt_hysterese"]],
    ["oven", "frost_off_c", ["frostvakt_av_temperatur"]],
    ["oven", "frost_c", ["frostvakt_temperatur"]],
    ["oven", "frostvakt", ["frostvakt"]],
    ["harvia", "harvia_remaining", ["harvia_gjenstar"]],
    ["harvia", "harvia_last_reset", ["siste_harvia_reset"]],
    ["harvia", "harvia_reset", ["nullstill_harvia_12t"]],
  ];
  for (const [group, key, needles] of rules) {
    if (needles.some((needle) => id.includes(needle))) {
      return { group, suffix: key };
    }
  }
  return null;
}

function registryEntry(page, entityId) {
  if (!entityId || typeof entityId !== "string") {
    return null;
  }
  const fromReg = (page._entityReg || []).find((entry) => entry.entity_id === entityId);
  if (fromReg) {
    return fromReg;
  }
  const fromHass = page.hass?.entities?.[entityId];
  if (fromHass) {
    return fromHass;
  }
  return { entity_id: entityId };
}

function linkedClimateEntry(page, deviceEntities) {
  const mode = deviceEntities.find(
    (entity) =>
      suffixOf(entity.unique_id) === "mode" ||
      String(entity.entity_id || "").includes("_styring")
  );
  const entityId = page.hass?.states?.[mode?.entity_id]?.attributes?.climate_entity;
  return registryEntry(page, entityId);
}

const HIDDEN_SUFFIXES = new Set([
  "climate_entity",
  "climate_current",
  "climate_target",
]);

function groupedEntities(page) {
  const device = page.hass?.devices?.[page.deviceId];
  if (!device || typeof page._entities !== "function") {
    return null;
  }
  const entities = page._entities(page.deviceId, page._entityReg || [], page.hass.devices) || [];
  const buckets = { site: [], door: [], light: [], oven: [], climate: [], harvia: [] };
  let matched = 0;
  for (const entity of entities) {
    if (entity.platform && entity.platform !== "hi_node") {
      continue;
    }
    if (HIDDEN_SUFFIXES.has(suffixOf(entity.unique_id))) {
      continue;
    }
    const found = classify(entity);
    if (!found) {
      if (!isHiNodeDevice(device)) {
        continue;
      }
      buckets.site.push({ entity, suffix: "mode" });
      matched += 1;
      continue;
    }
    buckets[found.group].push({ entity, suffix: found.suffix });
    matched += 1;
  }
  const linked = linkedClimateEntry(page, entities);
  if (linked) {
    const already = buckets.climate.some(
      (item) => item.entity.entity_id === linked.entity_id
    );
    if (!already) {
      // Kun visning — endrer ikke device_id / flytter ikke enheten.
      buckets.climate.unshift({ entity: linked, suffix: "linked_climate" });
      matched += 1;
    }
  }
  const ours =
    isHiNodeDevice(device) || entities.some((entity) => entity.platform === "hi_node");
  if (!matched || !ours) {
    return null;
  }
  for (const group of BOX_ORDER) {
    const order = SUFFIX_ORDER[group];
    buckets[group].sort(
      (left, right) => order.indexOf(left.suffix) - order.indexOf(right.suffix)
    );
    buckets[group] = buckets[group].map((item) => item.entity);
  }
  return { device, buckets };
}

function cardFrom(sample, page, header, entities, device) {
  const headerAt = sample.strings.findIndex((part) => part.includes(".header="));
  const entitiesAt = sample.strings.findIndex((part) => part.includes(".entities="));
  if (headerAt < 0 || entitiesAt < 0) {
    return null;
  }
  const values = sample.values.slice();
  const hassAt = sample.strings.findIndex((part) => part.includes(".hass="));
  const nameAt = sample.strings.findIndex((part) => part.includes(".deviceName="));
  const hiddenAt = sample.strings.findIndex((part) => part.includes(".showHidden="));
  if (hassAt >= 0) {
    values[hassAt] = page.hass;
  }
  values[headerAt] = header;
  if (nameAt >= 0) {
    values[nameAt] = device.name_by_user || device.name || "";
  }
  values[entitiesAt] = entities;
  if (hiddenAt >= 0) {
    values[hiddenAt] = Boolean(device.disabled_by);
  }
  return { _$litType$: sample._$litType$, strings: sample.strings, values };
}

function regroup(page, result) {
  const grouped = groupedEntities(page);
  if (!grouped) {
    return result;
  }
  const cards = findCardList(result);
  const sample = cards?.find(isTemplate);
  if (!sample) {
    return result;
  }
  const next = [];
  for (const group of BOX_ORDER) {
    const list = grouped.buckets[group];
    if (!list.length) {
      continue;
    }
    const card = cardFrom(sample, page, TITLES[group], list, grouped.device);
    if (!card) {
      return result;
    }
    next.push(card);
  }
  if (!next.length) {
    return result;
  }
  cards.length = 0;
  cards.push(...next);
  blankChildDevices(result);
  return result;
}

function install(ctor) {
  const proto = ctor?.prototype;
  if (!proto || proto._hiGrouped || typeof proto.render !== "function") {
    return;
  }
  proto._hiGrouped = true;
  const render = proto.render;
  proto.render = function () {
    const result = render.call(this);
    try {
      return regroup(this, result);
    } catch (error) {
      console.error("HI-node kunne ikke dele enhetssiden", error);
      return result;
    }
  };
}

const defineElement = customElements.define.bind(customElements);
customElements.define = function (name, ctor, options) {
  if (name === "ha-config-device-page") {
    install(ctor);
  }
  return defineElement(name, ctor, options);
};
customElements.whenDefined("ha-config-device-page").then(() => {
  install(customElements.get("ha-config-device-page"));
});
