# Instalace HA-Brew krok po kroku

*[English version](installation.md)*

Návod vás provede od začátku až k aplikaci, která se aktualizuje z Home Assistantu. Projděte část 1 a pak část pro svou televizi: část 2 (Samsung) nebo část 3 (LG). Část 4 popisuje běžné používání, část 5 řešení problémů.

Potřebujete:

- Home Assistant 2025.8 nebo novější s nainstalovaným [HACS](https://hacs.xyz/docs/use/).
- Televizi a Home Assistant ve stejné domácí síti. Pevná IP adresa televize (rezervace DHCP v routeru) ušetří starosti.
- Jen Samsung: počítač ve stejné síti kvůli jednorázovému přihlášení k účtu Samsung (část 2.3). Nic se na něj neinstaluje.

---

## 1. Instalace integrace

1. V Home Assistantu otevřete **HACS**.
2. Otevřete menu (⋮ vpravo nahoře) → **Vlastní repozitáře** (Custom repositories).
3. Repozitář: `https://github.com/Michailjovic/HA-Brew`, typ: **Integrace** → **Přidat**.
4. V HACS vyhledejte **HA-Brew** → otevřete → **Stáhnout**.
5. Restartujte Home Assistant: **Nastavení → Systém → ⏻ (vpravo nahoře) → Restartovat Home Assistant**.

Po restartu přibude v postranní liště položka **HA-Brew** (jen pro administrátory). Dokud nepřidáte televizi, je prázdná.

---

## 2. Televize Samsung (Tizen)

### 2.1 Zapnutí Developer Mode s adresou Home Assistantu

1. Zjistěte IP adresu Home Assistantu: **Nastavení → Systém → Síť**.
2. Na televizi otevřete **Aplikace**.
3. Na ovladači zadejte `1` `2` `3` `4` `5`. U ovladače bez číslic použijte virtuální ovladač v aplikaci SmartThings.
4. V okně *Developer Mode* přepněte **Developer mode** na **On** a jako **Host PC IP** zadejte IP adresu Home Assistantu. Potvrďte.
5. Televizi úplně restartujte: držte tlačítko napájení na ovladači, dokud se neobjeví logo Samsung.

> Televize přijímá příkazy jen z adresy Host PC IP. Dokud ukazuje na Home Assistant, nástroje na počítači (Apps2Samsung, TizenBrew Installer, Tizen Studio) se k ní nepřipojí. Pokud je chcete použít, přepněte Host PC IP dočasně zpět.

### 2.2 Přidání televize do Home Assistantu

1. **Nastavení → Zařízení a služby → + Přidat integraci** → vyhledejte **HA-Brew**.
2. Typ televize: **Samsung (Tizen)**. Název: nepovinný. Adresa: IP adresa televize.
3. **Odeslat**. HA-Brew se připojí k televizi a přečte model a verzi Tizenu.

Když hlásí, že se nemůže připojit: televize je vypnutá, Developer Mode není zapnutý, nebo Host PC IP není adresa Home Assistantu (krok 2.1).

### 2.3 Přidání podpisového certifikátu

Televize Samsung přijímají jen podepsané aplikace a **nainstalovanou aplikaci lze aktualizovat jen stejným certifikátem, kterým byla poprvé nainstalována**. Jsou dvě možnosti:

#### A. Vytvořit nový certifikát (doporučeno pro nové aplikace)

Potřebujete bezplatný [účet Samsung](https://account.samsung.com) s e-mailovou adresou a počítač (Windows, macOS nebo Linux) ve stejné síti jako Home Assistant. Na počítač se nic neinstaluje.

1. **Nastavení → Zařízení a služby → HA-Brew** → vaše televize → **Přidat certifikát**.
2. Vyberte **Vytvořit nový certifikát (účet Samsung)** → **Odeslat**.
3. Jméno autora: cokoli (třeba vaše jméno). Úroveň oprávnění: **Public**. *Další televize*: jen pro televize Samsung, které v HA-Brew nejsou. **Odeslat**.
4. Po odeslání se otevře další okno se **dvěma příkazy vytvořenými jen pro vás** (Windows a macOS/Linux). Příkaz vypadá zhruba takto, ale adresa a kód jsou pokaždé jiné, takže ho vždy zkopírujte z okna v Home Assistantu:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm 'http://192.168.1.2:8123/api/habrew/samsung_login/Xy12…/helper.ps1' | iex"
   ```

   Na počítači ho spusťte:
   - **Windows**: stiskněte **Win + R**, vložte příkaz, **Enter**.
   - **macOS / Linux**: vložte ho do **Terminálu**.
5. V prohlížeči se otevře přihlášení Samsungu. Přihlaste se. Stránka pak napíše *Přihlášeno*; zavřete ji.
6. V Home Assistantu dialog pokračuje sám a certifikát vytvoří (pár sekund).

Certifikát platí pro všechny vaše televize Samsung v HA-Brew a je uložený jen v Home Assistantu. Další certifikáty používají stejný autorský klíč. Když je port 4794 obsazený, zavřete Tizen Studio nebo jiný nástroj na certifikáty a spusťte příkaz znovu.

> Aplikace, které už v televizi jsou, podepsal certifikát nástroje, kterým jste je instalovali (např. TizenBrew Installer). Aby šly aktualizovat novým certifikátem, je nutné je jednou odinstalovat a nainstalovat znovu, čímž přijdou o svá data (přihlášení, nastavení). Panel nabídne **Odinstalovat a nainstalovat znovu**, když televize aktualizaci odmítne. Chcete-li data zachovat, nahrajte místo toho původní certifikát (B).

#### B. Nahrát certifikát, který už máte

| Aplikaci jste instalovali přes | Soubor(y) k nahrání | Kde je najdete na počítači |
|---|---|---|
| TizenBrew Installer (např. Nuvio) | `tizenbrewInstallerConfig.json` | `%USERPROFILE%\share\` |
| Apps2Samsung | `author.p12` + `distributor.p12`, heslo v `password.txt` | `%APPDATA%\Apps2Samsung\Certificate\<profil>\` |
| Tizen Studio | `author.p12` + `distributor.p12` a jejich heslo | složka vašeho certifikačního profilu |

Cestu z tabulky zkopírujte do adresního řádku Průzkumníka Windows a složka se otevře.

1. **Nastavení → Zařízení a služby → HA-Brew** → vaše televize → **Přidat certifikát**.
2. Vyberte formát, nahrajte soubor(y), u `.p12` vyplňte heslo → **Odeslat**.

HA-Brew ukáže, komu certifikát patří a kdy vyprší. Certifikáty Samsung platí zhruba rok.

### 2.4 Přidání aplikací

Buď v **panelu HA-Brew** (postranní lišta):

- Záložka **Televize** → **Další aplikace v televizi**: aplikace, které už v televizi jsou. **Převzít do správy** je přidá, pokud jsou v katalogu nebo jde o známou aplikaci (Nuvio TV).
- Záložka **Katalog**: asi 200 komunitních aplikací. **Přidat do TV** → vyberte televizi a certifikát → případně *Rovnou nainstalovat*.
- **Přidat z GitHubu** na kartě televize: libovolný repozitář, který má v release soubory `.wgt`.

Nebo na stránce integrace: **Přidat aplikaci** → předvolba (Nuvio TV) nebo GitHub repozitář → certifikát.

Pokračujte [částí 4](#4-běžné-používání).

---

## 3. Televize LG (webOS)

Root není potřeba. HA-Brew používá oficiální Developer Mode od LG, stejně jako Homebrew Channel.

### 3.1 Vývojářský účet LG

1. Na počítači nebo telefonu otevřete [webostv.developer.lge.com](https://webostv.developer.lge.com/) → **Sign in** → založte účet. Je zdarma.

### 3.2 Instalace a zapnutí Developer Mode v televizi

1. Na televizi otevřete **LG Content Store** (Aplikace) a nainstalujte aplikaci **Developer Mode**.
2. Otevřete **Developer Mode** a přihlaste se vývojářským účtem.
3. Zapněte **Dev Mode Status**. Televize se restartuje.
4. Otevřete **Developer Mode** znovu. Ukazuje zbývající čas relace (1000 hodin).

Pokud už používáte Homebrew Channel, máte tohle hotové; HA-Brew funguje vedle něj.

### 3.3 Přidání televize do Home Assistantu

1. V televizi v aplikaci **Developer Mode** zapněte **Key Server**. Na obrazovce se objeví **passphrase** (6 znaků). Aplikaci nechte otevřenou.
2. V Home Assistantu: **Nastavení → Zařízení a služby → + Přidat integraci** → **HA-Brew**.
3. Typ televize: **LG (webOS)**. Název: nepovinný. Adresa: IP adresa televize → **Odeslat**.
4. Opište **passphrase** z obrazovky televize → **Odeslat**.

HA-Brew si jednou stáhne klíč Developer Mode a ověří ho. **Key Server** pak můžete vypnout.

| Hláška | Co udělat |
|---|---|
| Key Server na televizi není dostupný | Key Server je vypnutý nebo se aplikace Developer Mode zavřela. Zapněte ho a nechte aplikaci otevřenou. |
| Špatná passphrase | Opište ji znovu přesně podle obrazovky (velká písmena a číslice). |
| Televize nepřijímá SSH spojení na portu 9922 | Dev Mode Status je vypnutý nebo relace vypršela. Zapněte ho v aplikaci Developer Mode. |

### 3.4 Přidání aplikací

- **Panel HA-Brew → Televize**: aplikace nainstalované přes Homebrew Channel jsou v sekci *Další aplikace v televizi*. **Převzít do správy** je přidá. Nuvio TV a YouTube AdFree jsou předvyplněné, stačí jedno kliknutí. Aktualizace se nainstaluje přes stávající aplikaci a data zůstanou.
- Záložka **Katalog** → **LG**: [repozitář webOS Homebrew](https://repo.webosbrew.org). Aplikace označené *vyžaduje root* na televizi bez rootu nefungují.
- **Přidat z GitHubu**: libovolný repozitář, který má v release soubory `.ipk`.
- Na stránce integrace: **Přidat aplikaci** → Nuvio TV, YouTube AdFree nebo GitHub.

### 3.5 Relace Developer Mode

LG ukončí relaci Developer Mode po 1000 hodinách a televize pak **smaže všechny aplikace nainstalované přes Developer Mode** (včetně Homebrew Channel). HA-Brew relaci jednou denně obnoví, i když je televize vypnutá.

- Senzor **Zbývá Developer Mode** ukazuje zbývající hodiny. Panel je ukazuje taky, s tlačítkem **Prodloužit**.
- Když se relaci nepodaří prodloužit nebo zbývá méně než 7 dní, objeví se upozornění v **Nastavení → Opravy**.
- Když Dev Mode vypnete a znovu zapnete, televize vytvoří nový klíč. Home Assistant pak u HA-Brew ukáže *Je vyžadováno opětovné ověření*: otevřete ho, zapněte Key Server a opište novou passphrase.

---

## 4. Běžné používání

- Každá aplikace má entitu `update.<televize>_<aplikace>`. Nové verze se objeví v **Nastavení → Aktualizace** spolu s ostatními aktualizacemi Home Assistantu. **Instalovat** aplikaci aktualizuje.
- Panel HA-Brew ukazuje všechny aplikace s nainstalovanou a dostupnou verzí a umí je instalovat, spouštět (▶) a odebírat.
- Při odebrání aplikace (🗑) si vyberete **Jen přestat spravovat** (aplikace v televizi zůstane) nebo **Odinstalovat z TV**.

### Zapnutí televize kvůli aktualizaci

Televize v pohotovostním režimu neodpovídá. Na stránce integrace dejte **Konfigurovat** a vyberte, jak ji má HA-Brew před instalací probudit:

- **Wake-on-LAN**: zadejte MAC adresu televize (router nebo menu televize *O televizi*). Samsung: zapněte i *Nastavení → Obecné → Síť → Nastavení pro odborníky → Zapnutí pomocí mobilu*.
- **Zapnout entitu**: `media_player` televize z jiné integrace (Samsung Smart TV, SamsungTV Smart, LG webOS TV). HA-Brew na ní zavolá *zapnout*.

HA-Brew pak na televizi čeká až 60 sekund.

---

## 5. Řešení problémů

| Hláška | Příčina a řešení |
|---|---|
| Author certificate not match (Samsung) | Aplikace byla nainstalována jiným certifikátem. Přidejte ten certifikát (část 2.3). Pokud ho nemáte, panel nabídne **Odinstalovat a nainstalovat znovu**; aplikace přijde o svá data (přihlášení, nastavení). |
| Certifikát / podpis odmítnut (Samsung) | Špatný nebo prošlý certifikát. Zkontrolujte platnost v záložce *Certifikáty* v panelu. |
| Vytvoření certifikátu: účet Samsung nemá e-mail | Doplňte ho v [profilu účtu Samsung](https://account.samsung.com/membership/getProfileInfo.do) a začněte znovu. |
| Vytvoření certifikátu: příliš mnoho požadavků | Samsung omezuje, jak často lze certifikáty vydávat. Zkuste to za hodinu. |
| Vytvoření certifikátu: dialog pořád čeká | Příkaz musí běžet na počítači ve stejné síti jako Home Assistant a přihlášení v otevřeném prohlížeči je potřeba dokončit. Windows: když se okno hned zavřelo, je obsazený port 4794 (Tizen Studio). |
| Tento balíček vyžaduje Tizen X nebo novější | Aplikace vaši verzi Tizenu nepodporuje. |
| Televize není dostupná | Televize je vypnutá a není nastavené probuzení, Developer Mode je vypnutý nebo (Samsung) se změnila Host PC IP. |
| Televize aplikaci neodinstalovala | Některé televize Samsung od roku 2021 příkaz k odinstalaci ignorují. Odstraňte aplikaci přímo v televizi: *Aplikace* → vyberte ji → *Odstranit*. |
| Upozornění na Developer Mode v Opravách (LG) | Zapněte televizi, otevřete Developer Mode a dejte *Extend*, nebo v Home Assistantu stiskněte **Prodloužit Developer Mode**. Pokud je Dev Mode vypnutý, přihlaste se znovu a zapněte ho. |

### Nahlášení problému

1. **Nastavení → Zařízení a služby → HA-Brew** → ⋮ u vaší televize → **Stáhnout diagnostiku**. Mějte televizi zapnutou, aby soubor obsahoval i to, co hlásí televize.
2. Založte [issue na GitHubu](https://github.com/Michailjovic/HA-Brew/issues), popište, co jste dělali, a přiložte soubor.

Soubor s diagnostikou obsahuje model televize a verzi systému, aplikace a jejich verze a poslední chybová hlášení. IP a MAC adresy, DUID, sériové číslo, klíče, passphrase a údaje certifikátů jsou z něj odstraněné.
