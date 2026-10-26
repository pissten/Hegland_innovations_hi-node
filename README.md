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

## Repo-struktur (HACS)

```
hacs.json
README.md
brand/icon.png          # HACS / merkevare
custom_components/hi_node/
  manifest.json
  ...
```

## Krav

- Home Assistant **2024.8** eller nyere (se `hacs.json`)
- Nettverkstilgang fra HA til booking-API / anlegg etter oppsett i config flow

## Utvikling

```bash
cd /opt/hegland-innovations/hi-node
python -m pytest tests/
```

## Lisens / tilgang

Internt Hegland Innovations-prosjekt. Ikke sendt inn til offisiell HACS-default-katalog. Deling skjer via custom repository-URL eller manuell kopi.
