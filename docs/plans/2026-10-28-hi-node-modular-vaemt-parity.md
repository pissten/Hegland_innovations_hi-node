# HI-node modulbasert oppsett + Væmt-paritet — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Start now. Ikke docker-deploy; commit + push når scoped arbeid er ferdig. Svar på norsk til Christian.

**Goal:** HI-node skal ved oppsett settes sammen av **moduler** (I/O, climate, Harvia, frost, grunnvarme-timeplan, …) slik at et nytt HA-anlegg blir like sikkert og oversiktlig som Væmt — og kan erstatte dagens Væmt-YAML fullt ut, med like god (eller bedre) fallback når booking/webhook er nede.

**Architecture:** Config entry lagrer `modules_enabled` + entity-bindings. `brain.py` forblir single source of truth for ovn/dør/lys. Nye «capabilities» (climate-settpunkt, Harvia 12t-reset, frost med hysterese, ekte timeplan) aktiveres kun når modulen er valgt og bindings finnes. UI-boksene (Anlegg / Dør / Lys / Ovn / evt. Harvia) styres fortsatt via `device-groups.js` + entity `group` — utvides, ikke erstattes. Booking-kanal: webhook + health + iCal (uendret prinsipp).

**Tech Stack:** Home Assistant custom component `custom_components/hi_node` (Python), config flow / options flow, `brain.py` + `runtime.py`, frontend `device-groups.js`. Referanse: [pissten/vaemt](https://github.com/pissten/vaemt) templates/automations/scripts.

**Produktprinsipper:**
- Ikke alle anlegg er like → modulvalg i oppsett.
- Samme visuelle mønster: avgrensede bokser per objekt + felles Anlegg-boks.
- Fallback uten booking skal styre etter iCal + lokale sikringer (frost, grunnvarme, 12t) uten YAML-automasjoner hos kunden.
- Væmt site-spesifikt (Plejd, undervannslys, nøkkelpuls) er **utenfor** v1 med mindre det blir egen valgfri modul senere.

---

## Målbilde: modul-katalog

| Modul-ID | Velges i oppsett | Bindinger | Eksponerte entiteter (boks) | Logikk |
|---|---|---|---|---|
| `io_switches` | Alltid / eksisterende / HKL-ER6 | oven, door, light switches | Dør, Lys, Ovn (marginer, desired, override) | Booking-vindu + webhook |
| `calendar_fallback` | Alltid (implisitt) | ical_url, health_url | Anlegg: Booking svarer, Styring | Health→iCal |
| `booking_close` | Alltid | — | Anlegg: Booking stengt, varighet | `/node/availability` |
| `climate` | Valgfri | `climate_entity` | Ovn: settpunkt-status / tall | Sett climate temp (booking / GV / default) |
| `frost` | Valgfri (krever tempkilde) | climate **eller** `temperature_entity` | Ovn: Frostvakt, frost_c, (hysterese) | Hysterese som Væmt |
| `grunnvarme_quota` | Valgfri | — | Ovn: timer per dag | Som i dag |
| `grunnvarme_schedule` | Valgfri | ukedager + fra/til (i entry data) | Ovn: Timeplan på/av + schedule-entiteter | Erstatter «bare boolean» |
| `harvia_12h` | Valgfri («Bruker Harvia?») | `heater_power_entity`, valgfri `remaining_time_entity` | Ny boks **Harvia** eller under Ovn | Dual-cycle reset a la `sauna_reset_cycle` |
| `override_timers` | Valgfri / fase 2 | — | Manuell + gjenstående tid | 1t auto-av som Væmt |
| `runtime_alarm` | Valgfri / fase 2 | — | Anlegg/Ovn: alarm | desired≠actual |

Config entry `data` (skisse):

```python
{
  "name": "...",
  "slug": "...",
  "ical_url": "...",
  "health_url": "...",
  "features": {
    "climate": True,
    "frost": True,
    "grunnvarme_quota": True,
    "grunnvarme_schedule": True,
    "harvia_12h": True,
  },
  "bindings": {
    "climate_entity": "climate.xxx",          # valgfri
    "temperature_entity": "sensor.xxx",       # frost fallback hvis ikke climate
    "heater_power_entity": "switch.xxx",      # Harvia sky/strøm
    "remaining_time_entity": "sensor.xxx",    # valgfri preemptiv 12t
  },
  "schedule": {  # grunnvarme_schedule
    "weekdays": [0,1,2,3,4,5,6],  # 0=man
    "start": "06:00",
    "end": "22:00",
  },
  "temps": {
    "booking_c": 110,
    "grunnvarme_c": 40,
    "default_c": 110,
    "frost_c": 20,
    "frost_hysteresis_c": 1,
    "frost_off_c": 40,  # typisk = grunnvarme_c
  },
  "modules": [ /* eksisterende I/O-kort */ ],
}
```

Reconfigure/options: «Endre moduler og bindinger» uten å slette anlegget.

---

## UI-bokser (behold + utvid)

Nåværende: `Anlegg` | `Dør` | `Lys` | `Ovn` via `frontend/device-groups.js`.

Planlagt `BOX_ORDER` / `SUFFIX_*`:

1. **Anlegg** — booking online, mode, booking stengt, stengevarighet, stengt til, (senere alarm)
2. **Dør** — som i dag
3. **Lys** — som i dag
4. **Ovn** — override, desired, status, climate-settpunkter (hvis modul), grunnvarme kvote + **timeplan**, frost, marginer
5. **Harvia** (kun hvis `harvia_12h`) — status siste reset, power-binding synlig, evt. «Nullstill nå», remaining

Bump `device-groups.js?v=` ved hver UI-endring.

---

## Fallback-krav (paritet med Væmt offline)

Når `health` feiler 3× → `fallback=True` (allerede):

| Sikring | Krav i HI-node |
|---|---|
| iCal + marginer | Allerede; behold events ved hentefeil |
| Grunnvarme kvote | Allerede |
| Grunnvarme timeplan | Må kjøre lokalt fra lagret schedule (ikke avhengig av booking) |
| Frost | Må kjøre lokalt fra climate/sensor |
| 12t Harvia | Må kjøre lokalt (preemptiv/feedback) uavhengig av booking |
| Climate-settpunkt | Sett lokalt basert på decision.reason |

Webhook-kommandoer ignoreres/overstyres i fallback slik i dag (iCal-vindu).

---

### Task 1: Features + bindings i config data (migrering)

**Files:**
- Create: `custom_components/hi_node/features.py` (defaults, normalize, has_feature)
- Modify: `custom_components/hi_node/__init__.py` / `runtime.py` — les normalized features ved start
- Modify: `custom_components/hi_node/manifest.json` — bump version `0.2.0`
- Test: `tests/test_features.py`

**Step 1:** Skriv tester for `normalize_entry_data(old)` → fyller `features`/`bindings` bakoverkompatibelt (`temperature_entity` fra gammel flat key).

**Step 2:** Implementer `features.py`.

**Step 3:** Kjør `python -m pytest tests/test_features.py -v` → PASS.

**Step 4:** Commit `feat(hi-node): normaliser features/bindings i entry data`.

---

### Task 2: Config flow — modulvalg + bindinger

**Files:**
- Modify: `custom_components/hi_node/config_flow.py`
- Modify: `strings.json`, `translations/nb.json`
- Test: manuell sjekkliste + evt. unit for schema helpers

**Oppsettssteg (ny rekkefølge):**

1. `user` — site_name, ical_url, health_url (som i dag)
2. `io` — profil HKL-ER6 / Eksisterende brytere (som i dag)
3. `switches` / `hkl_er6` — I/O (som i dag)
4. **`modules`** — boolean-valg: Climate, Frost, Grunnvarme-kvote, Grunnvarme-timeplan, Harvia 12t
5. **`bindings`** — betingede EntitySelectors:
   - Climate: `climate` domain
   - Frost uten climate: `sensor` (temp device_class)
   - Harvia: `heater_power` switch (+ optional remaining_time sensor)
6. **`schedule`** (hvis timeplan) — weekdays multi-select + time start/end
7. **`temps`** (hvis climate/frost) — booking/grunnvarme/default/frost tall med fornuftige defaults fra Væmt

**Options flow:** «Oppdater moduler og bindinger» → samme steg uten å rekreate unique_id; deretter `async_reload`.

**Step 1:** Utvid flow + strings.

**Step 2:** Commit `feat(hi-node): modulbasert config flow med climate/Harvia/frost-bindinger`.

---

### Task 3: Grunnvarme-timeplan (ekte schedule)

**Files:**
- Modify: `brain.py` — `_grunnvarme`: timeplan = schedule aktiv *nå*, ikke bare boolean
- Modify: `runtime.py` — lagre schedule; eval `schedule_active(now)`
- Modify: `switch.py` — skill «Grunnvarme timeplan» (enable) vs kvote; evt. sensor «Timeplan aktiv nå»
- Modify: `number.py` — behold timer/dag
- Modify: `device-groups.js` — nye suffixer under Ovn
- Test: `tests/test_hi_node.py` — schedule innenfor/utenfor vindu

**Oppførsel (Væmt-paritet):**
- Timeplan enable + innenfor ukedag/tid → ovn kan gå på grunnvarme (uten booking).
- Kvote (`hours_per_day`) → etter siste booking til kvote fylt (som i dag).
- Booking vinner alltid over grunnvarme.

**Step 1–4:** TDD + implementer + bump JS `?v=`.

**Step 5:** Commit `feat(hi-node): eksponert grunnvarme-timeplan med ukedag/tid`.

---

### Task 4: Frost med climate/sensor + hysterese

**Files:**
- Modify: `runtime.py` `_temperature()` — prefer climate `current_temperature`, else sensor
- Modify: `brain.py` / frost state — hysterese: call ON under `frost_c + hyst`, OFF ved `frost_off_c` (eller grunnvarme_c); lagre `frost_calling` i data
- Modify: `number.py` — frost_c, frost_hysteresis (valgfri), frost_off
- Modify: entiteter kun hvis `features.frost`
- Test: hysterese + «ingen temp → frost aldri ON» + unavailable-advarsel i attributter

**Step 1–4:** TDD + UI.

**Step 5:** Commit `feat(hi-node): frostvakt med hysterese mot climate/sensor`.

---

### Task 5: Climate-settpunkt-modul

**Files:**
- Create: `custom_components/hi_node/climate_control.py` — map `decision.reason` → target °C
- Modify: `runtime.py` `_apply` — etter decide, hvis climate-modul: `climate.set_temperature`
- Modify: `number.py` — booking_c, grunnvarme_c, default_c (gruppe oven)
- Modify: `device-groups.js`
- Test: reason booking→110, grunnvarme→40, default_off→default, ingen climate→noop

**Regel (fra Væmt):**
- booking / upcoming-i-premargin → `booking_c`
- grunnvarme → `grunnvarme_c`
- ellers → `default_c` (eller la stå — dokumenter valg; prefer sett default for forutsigbarhet)

**Step 5:** Commit `feat(hi-node): climate-settpunkt styrt av booking-hjernen`.

---

### Task 6: Harvia 12t-modul (kritisk Væmt-paritet)

**Files:**
- Create: `custom_components/hi_node/harvia_reset.py` — async cycle (HKL oven off → power off → delay → power on → delay → oven on), tider som constants/config
- Modify: `runtime.py` — erstatt/utvid enkel 15s-hold når `harvia_12h`:
  - preemptiv: remaining_time ≤ 5 min og oven desired on
  - feedback: power gikk off mens desired on / grunnvarme/booking
  - periodisk sjekk remaining == 00:00
  - fallback: egen 12t lokal teller hvis ingen remaining-sensor (dagens oven_on_since)
- Modify: `switch.py` / `sensor.py` — «Harvia reset» status, evt. knapp via button-entity `button.hi_node_harvia_reset`
- Modify: `device-groups.js` — boks `harvia`
- Test: cycle kall-rekkefølge med mocks; ingen cycle hvis modul av

**Viktig:** Kun å cycle oven-switch er **ikke** nok (Væmt-kommentar). Power-entitet er påkrevd når Harvia-modul er valgt.

**Step 5:** Commit `feat(hi-node): Harvia 12t reset-modul med dual-cycle`.

---

### Task 7: Entity-gating + device-groups for nye felt

**Files:**
- Modify: `switch.py`, `number.py`, `sensor.py`, `binary_sensor.py` — opprett entiteter kun for enabled features
- Modify: `frontend/device-groups.js` — TITLES/BOX_ORDER/SUFFIX_*
- Modify: `__init__.py` — bump static `?v=`

**Step:** Verifiser manuelt at bokser matcher screenshot-mønster (Anlegg/Dør/Lys/Ovn + Harvia).

**Commit:** `feat(hi-node): gated entiteter og utvidede UI-bokser`.

---

### Task 8: Options «Endre moduler» + README

**Files:**
- Modify: `config_flow.py` OptionsFlowHandler
- Modify: `README.md` — moduloppsett, Harvia, frost, fallback, migrering fra Væmt

**Commit:** `docs(hi-node): moduloppsett og Væmt-erstatning`.

---

### Task 9 (fase 2, etter v0.2): Override-timere + runtime-alarm

- 1t override-timer + detect fra fysisk toggle (context.user_id) — port fra Væmt override-* automations
- Alarm binary_sensor når desired oven on men power/HKL off i X sekunder + notify-hook (valgfri notify service i bindings)

Egne commits; ikke blokker v0.2-leveranse.

---

## Testplan (samlet)

```bash
cd /opt/hegland-innovations/hi-node
python -m pytest tests/ -v
```

Manuelt på test-HA:
1. Ny integrasjon med Climate + Frost + Harvia + timeplan → bindinger → se 5 bokser.
2. Frost PÅ uten temp → frost aldri desired; med climate kald → desired on.
3. Timeplan innenfor vindu, ingen booking → Status Grunnvarme.
4. Bryt health_url → mode ical; ovn følger iCal; Harvia-reset fortsatt lokal.
5. Simuler remaining_time lav → dual-cycle kjører (logg/rekkefølge).
6. Anlegg uten Harvia/climate → ingen Harvia-boks; ovn som i dag.

---

## Migrasjon fra eksisterende HI-node / Væmt

| Fra | Til |
|---|---|
| Gammel HI-node entry | `normalize_entry_data`: frost/grunnvarme on hvis entiteter fantes; Harvia av til options |
| Væmt YAML | Ny HI-node: Eksisterende brytere → map output1/2/3; climate.vaemt_thermostat; vaemt_power_switch; remaining_time; slå av sauna-automasjoner |

---

## Rekkefølge / estimat

| Task | Prioritet | Avhengighet |
|---|---|---|
| 1 Features schema | P0 | — |
| 2 Config flow | P0 | 1 |
| 3 Timeplan | P0 | 1–2 |
| 4 Frost hysterese | P0 | 1–2 |
| 5 Climate settpunkt | P0 | 1–2 |
| 6 Harvia 12t | P0 | 1–2 |
| 7 UI gating | P0 | 3–6 |
| 8 Options + docs | P0 | 7 |
| 9 Override/alarm | P1 | etter v0.2 |

---

## Explicit non-goals (v0.2)

- Plejd / undervannslys / nøkkelbryter-puls
- Full audit-logbook som Væmt
- Testmodus med falske iCal-events (kan komme senere)
- Innsending til HACS default store
