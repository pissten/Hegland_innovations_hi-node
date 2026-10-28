# HI-node

Home Assistant-integrasjon for Hegland Innovations anlegg (dør, lys, ovn m.m.) med booking-hjerne over LAN.

Integrasjonen lever i `custom_components/hi_node/` og er klar for installasjon via **HACS** som *custom repository* (ikke i den offentlige HACS-default-listen).

## Viktig: HACS og privat repo

**HACS kan kun hente fra offentlige GitHub-repositorier.** Et privat repo kan ikke legges til i HACS.

Anbefalt modell mens løsningen fortsatt er «intern»:

| Mål | Hva du gjør |
| --- | --- |
| Skjult for tilfeldige (ikke i HACS-store) | Hold repoet **utenfor** default HACS-katalog. Bruk bare *Custom repositories* med URL. |
| Fungerer i HACS | Sett GitHub-repoet til **Public**. |
| Strengt privat (ingen HACS) | La repoet være Private og installer manuelt (se under). |

Når du er klar for HACS hos kunder/egne HA-instanser:

```bash
gh repo edit pissten/Hegland_innovations_hi-node --visibility public
```

(eller Settings → Change visibility → Public på GitHub.)

## Installasjon via HACS (krever Public-repo)

1. Installer [HACS](https://www.hacs.xyz/) i Home Assistant hvis det ikke allerede er gjort.
2. Gå til **HACS** → de tre prikkene øverst til høyre → **Custom repositories**.
3. Legg inn:
   - **Repository:** `https://github.com/pissten/Hegland_innovations_hi-node`
   - **Type:** `Integration`
4. Trykk **Add**.
5. Søk etter **HI-node** i HACS og installer.
6. **Restart** Home Assistant.
7. Gå til **Innstillinger → Enheter og tjenester → Legg til integrasjon** og velg **HI-node**.

### Hurtiglenke (My Home Assistant)

Når repoet er Public, kan du åpne:

[Legg til HI-node i HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=pissten&repository=Hegland_innovations_hi-node&category=integration)

## Manuell installasjon (fungerer med Private-repo)

1. Klon eller last ned dette repoet (med GitHub-tilgang hvis privat).
2. Kopier mappen `custom_components/hi_node` til Home Assistant sin `config/custom_components/hi_node`.
3. Restart Home Assistant.
4. Legg til integrasjonen under **Innstillinger → Enheter og tjenester**.

Eksempel fra en maskin med tilgang til repoet:

```bash
# Tilpass stien til din HA config
git clone https://github.com/pissten/Hegland_innovations_hi-node.git /tmp/hi-node
cp -a /tmp/hi-node/custom_components/hi_node /config/custom_components/
```

## Oppdateringer

- Med **HACS**: oppdater fra HACS når ny release finnes (eller fra default branch hvis du ikke bruker releases).
- Manuelt: `git pull` i klonen og kopier `custom_components/hi_node` på nytt, deretter restart HA.

## Ikon / merkevare

- **I Home Assistant** (Innstillinger → Integrasjoner, enhetssider m.m.): ikonet kommer fra `custom_components/hi_node/brand/` (støttet fra HA 2026.3). Etter install/oppdatering: restart HA og hard refresh i nettleseren.
- **I HACS-oversikten**: HACS henter fortsatt ikon fra den gamle brands-CDN-en. Home Assistant tar **ikke lenger imot** nye custom-ikoner der. Resultatet er at HACS ofte viser grått plassholder-ikon selv om HI-node har riktig merkevare lokalt. Dette er en kjent HACS-begrensning (fikses i Marketplace / HA 2026.11). Det betyr ikke at integrasjonen mangler ikon i selve Home Assistant.

## Repo-struktur (HACS)

```
hacs.json
README.md
brand/icon.png                         # HACS-sjekk / merkevare i repo-rot
custom_components/hi_node/brand/       # Ikon i selve HA-integrasjonen
custom_components/hi_node/manifest.json
...
```

## Krav

- Home Assistant **2024.8** eller nyere (se `hacs.json`)
- Nettverkstilgang fra HA til booking-API / anlegg etter oppsett i config flow

## Modulbasert oppsett

HI-node settes opp per anlegg. Dør, lys og ovn er grunnleggende I/O, mens øvrige funksjoner velges som moduler. Dermed får hvert anlegg bare logikken og entitetene det faktisk bruker.

Ved første oppsett:

1. Oppgi anleggsnavn, iCal-adresse og `/health`-adresse fra HI Booking.
2. Velg **Eksisterende brytere** eller **HKL-ER6**.
3. Koble bryterne for ovn, dør og lys, eller fullfør HKL-ER6-oppsettet.
4. Velg aktuelle moduler.
5. Koble modulene til eksisterende Home Assistant-entiteter og angi eventuelle tider og temperaturer.

| Modul | Binding/oppsett | Funksjon |
| --- | --- | --- |
| Climate-styring | Climate-entitet | Setter booking-, grunnvarme- eller standardtemperatur etter hvorfor ovnen skal kjøre. |
| Frostvakt | Climate-entitet eller temperatursensor | Lokal frostsikring med innslag, hysterese og egen av-temperatur. Uten gyldig temperatur slår frostvakten ikke inn. |
| Grunnvarme-kvote | Timer per dag | Lar ovnen fylle en daglig grunnvarmekvote når booking ikke krever varme. |
| Grunnvarme-timeplan | Ukedager, fra og til | Tillater lokal grunnvarme i valgte tidsvinduer. Tidsrom over midnatt støttes. |
| Harvia 12-timers sikring | Harvia strømbryter og valgfri sensor for gjenstående tid | Nullstiller Harvia lokalt med en kontrollert dual-cycle. Bruker lokal 12-timers teller når gjenstående-tid-sensor ikke finnes. |

Calendar fallback er alltid aktiv og trenger ikke velges som egen modul. Booking har prioritet foran grunnvarme, mens frostvakt og Harvia-sikring fortsetter å virke lokalt.

### Endre moduler senere

Åpne **Innstillinger → Enheter og tjenester → HI-node → Konfigurer** og velg **Oppdater funksjoner og bindinger**. Her kan moduler aktiveres eller deaktiveres, bindinger byttes og timeplan/temperaturer oppdateres uten å slette anlegget. Integrasjonen lastes automatisk på nytt etter lagring.

Entiteter som tilhører en deaktivert modul blir ikke opprettet. Grunnvarmebryteren vises når kvote eller timeplan er aktivert, mens tallet **Grunnvarme timer per dag** bare vises for kvotemodulen.

## UI-bokser i Home Assistant

Enhetssiden deles automatisk i faste bokser:

- **Anlegg:** bookingstatus, aktiv styringskilde, booking stengt, stengevarighet og stengt til.
- **Dør:** manuell overstyring, ønsket tilstand og marginer.
- **Lys:** manuell overstyring, ønsket tilstand og marginer.
- **Ovn:** overstyring, ønsket tilstand, status, marginer og bare de valgte climate-, grunnvarme- og frostfeltene.
- **Harvia:** siste reset og manuell resetknapp. Boksen vises bare når Harvia-modulen er aktiv og nødvendige bindinger finnes.

Etter installasjon eller oppdatering må Home Assistant restartes. Bruk hard refresh i nettleseren hvis boksene ikke oppdateres med en gang.

## Booking og fallback til iCal

Normal drift bruker webhook-kommandoer fra HI Booking. HI-node kontrollerer samtidig `/health` hvert minutt:

1. Så lenge health svarer, viser **Styring** `webhook`.
2. Etter tre sammenhengende health-feil, med minst ett minutt mellom feilene, går anlegget til `ical`.
3. I fallback beregnes dør, lys og ovn fra iCal-bookinger og lokale før-/etter-marginer.
4. Når health svarer igjen, går styringen automatisk tilbake til webhook.

iCal hentes ved oppstart og deretter hvert 15. minutt. Ved en midlertidig iCal-feil beholdes sist gyldige bookingliste. Grunnvarme-timeplan, frostvakt og Harvia 12-timers sikring kjører lokalt og er ikke avhengige av at bookingtjenesten er tilgjengelig.

## Migrering fra Væmt

HI-node kan overta den sentrale Væmt-logikken, slik at booking, fallback, climate, frost, grunnvarme og Harvia ikke lenger trenger separate YAML-automasjoner.

| Væmt | HI-node |
| --- | --- |
| Ovn / HKL `output1` | Ovn-bryter under **Eksisterende brytere**, eller `output1` i HKL-ER6-profilen |
| Dør / HKL `output2` | Dør-bryter, eller `output2` i HKL-ER6-profilen |
| Lys / HKL `output3` | Lys-bryter, eller `output3` i HKL-ER6-profilen |
| `climate.vaemt_thermostat` eller tilsvarende | Climate-modulens **Climate-entitet** |
| Væmt temperatursensor | Frostmodulens **Temperatursensor** når climate ikke leverer temperatur |
| `switch.vaemt_power_switch` eller tilsvarende | Harvia-modulens **Harvia strømbryter** |
| Væmt `remaining_time` | Harvia-modulens valgfrie **Gjenstående tid**-sensor |
| Væmt iCal/health-adresser | iCal-adresse og health-adresse i HI-node-oppsettet |

Anbefalt migreringsrekkefølge:

1. Noter dagens Væmt-entiteter, marginer, temperaturer og timeplan.
2. Installer HI-node via HACS custom repository eller manuelt.
3. Legg til anlegget med **Eksisterende brytere** hvis eksisterende Væmt/HKL-entiteter skal gjenbrukes.
4. Aktiver aktuelle moduler og map entitetene etter tabellen over.
5. Kontroller boksene og ønsket tilstand i Home Assistant før fysisk styring overlates til HI-node.
6. Deaktiver gamle Væmt-automasjoner og scripts som styrer de samme bryterne. To parallelle styringer kan ellers slå utgangene av og på mot hverandre.

Plejd, undervannslys, nøkkelbryter-puls, 1-times overstyringstimer og runtime-alarm er ikke del av denne versjonen. Behold eventuell Væmt-logikk for slike funksjoner til de finnes som egne HI-node-moduler.

## Utvikling

```bash
cd /opt/hegland-innovations/hi-node
python3 -m unittest discover -s tests -v
```

## Lisens / tilgang

Internt Hegland Innovations-prosjekt. Ikke sendt inn til offisiell HACS-default-katalog. Deling skjer via custom repository-URL eller manuell kopi.
