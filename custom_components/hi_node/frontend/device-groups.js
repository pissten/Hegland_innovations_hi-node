// Deler HI-node-enhetssiden i boksene Anlegg, Dør, Lys og Ovn.

const TITLES = { site: "Anlegg", door: "Dør", light: "Lys", oven: "Ovn" };
const BOX_ORDER = ["site", "door", "light", "oven"];
const SUFFIX_GROUP = {
  booking_online: "site",
  mode: "site",
  booking_closed: "site",
  availability_duration: "site",
  closed_until: "site",
  desired_door: "door",
  margin_door_pre: "door",
  margin_door_post: "door",
  override_door: "door",
  desired_light: "light",
  margin_light_pre: "light",
  margin_light_post: "light",
  override_light: "light",
  desired_oven: "oven",
  oven_status: "oven",
  booking_c: "oven",
  grunnvarme_c: "oven",
  default_c: "oven",
  margin_oven_pre: "oven",
  margin_oven_post: "oven",
  override_oven: "oven",
  grunnvarme: "oven",
  grunnvarme_schedule_active: "oven",
  grunnvarme_hours_per_day: "oven",
  frostvakt: "oven",
  frost_c: "oven",
  frost_hysteresis_c: "oven",
  frost_off_c: "oven",
};
const SUFFIX_ORDER = {
  site: [
    "booking_online",
    "mode",
    "booking_closed",
    "availability_duration",
    "closed_until",
  ],
  door: ["override_door", "desired_door", "margin_door_pre", "margin_door_post"],
  light: ["override_light", "desired_light", "margin_light_pre", "margin_light_post"],
  oven: [
    "override_oven",
    "desired_oven",
    "oven_status",
    "booking_c",
    "grunnvarme_c",
    "default_c",
    "grunnvarme",
    "grunnvarme_schedule_active",
    "grunnvarme_hours_per_day",
    "frostvakt",
    "frost_c",
    "frost_hysteresis_c",
    "frost_off_c",
    "margin_oven_pre",
    "margin_oven_post",
  ],
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
    ["door", "override_door", ["manuell_dor"]],
    ["light", "override_light", ["manuell_lys"]],
    ["oven", "override_oven", ["manuell_ovn"]],
    ["door", "desired_door", ["dor_skal"]],
    ["light", "desired_light", ["lys_skal"]],
    ["oven", "desired_oven", ["ovn_skal"]],
    ["oven", "booking_c", ["booking_temperatur"]],
    ["oven", "grunnvarme_c", ["grunnvarme_temperatur"]],
    ["oven", "default_c", ["standard_temperatur"]],
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
  ];
  for (const [group, key, needles] of rules) {
    if (needles.some((needle) => id.includes(needle))) {
      return { group, suffix: key };
    }
  }
  return null;
}

function groupedEntities(page) {
  const device = page.hass?.devices?.[page.deviceId];
  if (!device || typeof page._entities !== "function") {
    return null;
  }
  const entities = page._entities(page.deviceId, page._entityReg || [], page.hass.devices) || [];
  const buckets = { site: [], door: [], light: [], oven: [] };
  let matched = 0;
  for (const entity of entities) {
    if (entity.platform && entity.platform !== "hi_node") {
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
