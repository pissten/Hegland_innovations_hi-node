# Node availability (nød-stenging) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Start now. Do not redeploy docker; user builds images. Commit + push when scoped work is done. Reply in Norwegian to Christian.

**Goal:** Fra HA (HI-node) kan drift sette badstuen utilgjengelig for booking med varighet, og toggle av når som helst — via samme node-kanal som `/node/margins`.

**Architecture:** Booking eier `resource_unavailability` (kunden ser bare vanlig utilgjengelig). HI-node er HA-UX (bryter + varighet) og kaller tilbake med `slug`+`token` fra iCal-URL. Audit i backoffice-logg, ikke kundetekst på kalenderen.

**Tech Stack:** booking `server/index.mjs` + Postgres; HI-node `custom_components/hi_node` (Python HA integration).

**Kontekst / beslutning (fra booking-chat):**
- Ikke staff-REST fra HA.
- Ikke egen logikk i `brain.py` for ovn/dør/lys.
- Speil `/node/margins`: samme vert, `slug`, `token`.
- Kundekalender: ingen «Akutt stenging fra HA» — bare utilgjengelig som ellers.
- Backoffice: logg at det kom fra node/HA + varighet.
- Toggle av må fjerne aktiv nød-stenging med én gang.

---

### Task 1: Booking — `/node/availability`

**Files:**
- Modify: `booking/server/index.mjs` (ved siden av `handleNodeMargins` ~3914 og route ~4155)
- Optional helper: `booking/server/availability.mjs` hvis det blir ryddigere
- Test: utvid eksisterende node-tester hvis finnes; ellers manuell curl-sjekkliste i slutten

**API (samme auth som margins):**
- URL: `/node/availability?slug=…&token=…`
- Auth: samme `CALENDAR_FEED_TOKEN` / token-sjekk som `handleNodeMargins`

| Method | Body | Effekt |
|--------|------|--------|
| `GET` | — | Status: `{ active: bool, startsAt?, endsAt?, blockId?, durationMinutes? }` for aktiv node-blokk på ressursen |
| `PUT` / `POST` | `{ durationMinutes: number }` eller `{ until: ISO }` | Sett/erstatt én aktiv **node**-stenging fra `now` til `now+duration` / `until` |
| `DELETE` | — | Fjern aktiv node-stenging (toggle av) |

**Datamodell:**
- Bruk eksisterende `resource_unavailability`.
- Marker node-blokker så clear bare treffer dem: f.eks. `comment` internt med stabil prefix `__node__` **eller** ny kolonne `source text` (`node` / `staff`). Preferer kolonne hvis enkel; ellers comment-prefix som ikke vises til kunder.
- **Kunden / public calendar:** ikke vis comment / ikke spesialtekst — samme «opptatt/utilgjengelig» som andre blokker.
- **Backoffice / plant_command_log (eller tilsvarende):** ved set/clear logg f.eks. `availability on 120m` / `availability off` med site/slug — synlig i automatiseringslogger, ikke på kundekalender.

**Regler:**
- Ved ny PUT: slett/erstatt tidligere aktiv node-blokk for samme `resource_id` (én aktiv nød-stenging).
- Ikke slett staff-blokker laget i Kalenderstyring.
- `durationMinutes` forslag: 60, 120, 240, 480, eller til midnatt (beregn i node eller API).
- Eksisterende booking-konflikter: stenging er OK selv om bookinger finnes (nød); ikke kanseller bookinger automatisk i v1.

**Step:** Implementer handler + wire i `handle()`. Speil stil fra `handleNodeMargins`.

---

### Task 2: HI-node — klient mot `/node/availability`

**Files:**
- Create: `hi-node/custom_components/hi_node/availability.py` (URL-bygging ala `margins_url` i `margins.py`)
- Modify: `hi-node/custom_components/hi_node/runtime.py` (GET/PUT/DELETE, lagre lokal status)
- Modify: `hi-node/tests/test_hi_node.py`

**Step:**
- `availability_url(ical_url)` → `/node/availability?slug&token`
- Runtime-metoder: `async_get_availability`, `async_set_unavailable(duration_minutes)`, `async_clear_unavailable`
- Ved ON: kall PUT. Ved OFF: DELETE.
- Cache `active` + `ends_at` i `runtime.data` for UI.
- Periodisk GET (samme rytme som margins/health er ok) så HA speiler booking hvis noen fjernet blokk i backoffice.

---

### Task 3: HI-node — HA-enheter (UX som manuell ovn/dør/lys)

**Files:**
- Modify: `hi-node/custom_components/hi_node/switch.py` — bryter «Booking stengt» / «Utilgjengelig for booking»
- Modify: `hi-node/custom_components/hi_node/number.py` eller ny `select.py` — varighet (f.eks. 1t / 2t / 4t / resten av dagen)
- Modify: `hi-node/custom_components/hi_node/sensor.py` — valgfri sensor «Stengt til …»
- Modify: `hi-node/custom_components/hi_node/dashboard.py` hvis grupper/kort trenger ny seksjon (f.eks. gruppe `booking` / `availability`)
- Modify: `__init__.py` / platforms hvis ny platform (`select`)

**Oppførsel:**
- Bryter ON → bruk valgt varighet → PUT
- Bryter OFF → DELETE (opphør med en gang)
- Skru ON på nytt med ny varighet → erstatt periode
- Feilet API-kall → logg warning, ikke late som det er stengt

**Ikke:** bland inn i `decide()` / oven/door/light overrides.

---

### Task 4: Kundervisning vs backoffice

**Verify:**
- Public/guest calendar og booking-flyt: blokk blokkerer nye bookinger; ingen «Akutt…»-tekst.
- Backoffice «Sett utilgjengelig» / kalender: perioden synes som vanlig utilgjengelig (tom eller nøytral comment for kunde).
- Plant/automation log: node-set/clear synlig.

Hvis public UI viser `comment`: sørg for at node-blokker har tom/nøytral comment til kunde, og at audit kun ligger i logg / intern source-markering.

---

### Task 5: Tester + commit

**Tests:**
- `availability_url` bygger riktig path fra ical_url
- Booking handler: set → GET active → clear → GET inactive (unit/integration etter prosjektets stil)
- HI-node: switch on/off kaller runtime (mock session)

**Commit (to repos hvis nødvendig):**
- booking: `feat(node): availability endpoint for nød-stenging`
- hi-node: `feat: HA-bryter for booking utilgjengelig via /node/availability`

**Ikke** docker deploy. Brukeren bygger selv.

---

## Kickoff-melding (lim inn i HI-node-chatten)

```
Implementer planen i hi-node/docs/plans/2026-10-26-node-availability.md nå.
Kjør task-by-task. Booking API /node/availability + HI-node bryter/varighet.
Ikke deploy. Commit/push når ferdig. Svar på norsk.
```
