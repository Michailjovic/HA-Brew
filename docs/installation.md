# Installing HA-Brew, step by step

*[Česká verze](installation.cs.md)*

This guide takes you from nothing to an app that updates from Home Assistant. Follow part 1, then the part for your TV: part 2 (Samsung) or part 3 (LG). Part 4 covers everyday use, part 5 problems.

You need:

- Home Assistant 2025.8 or newer with [HACS](https://hacs.xyz/docs/use/) installed.
- The TV and Home Assistant on the same home network. A fixed IP address for the TV (DHCP reservation in your router) saves trouble later.
- Samsung only: a computer in the same network for signing in to your Samsung account once (part 2.3). Nothing is installed on it.

---

## 1. Install the integration

1. In Home Assistant open **HACS**.
2. Open the menu (⋮, top right) → **Custom repositories**.
3. Repository: `https://github.com/Michailjovic/HA-Brew`, type: **Integration** → **Add**.
4. Search HACS for **HA-Brew** → open it → **Download**.
5. Restart Home Assistant: **Settings → System → ⏻ (top right) → Restart Home Assistant**.

After the restart there is a **HA-Brew** item in the sidebar (only for administrators). It stays empty until you add a TV.

---

## 2. Samsung TV (Tizen)

### 2.1 Turn on Developer Mode and point it to Home Assistant

1. Find the IP address of your Home Assistant: **Settings → System → Network**.
2. On the TV open **Apps**.
3. Type `1` `2` `3` `4` `5` on the remote. On remotes without digits, use the virtual remote in the SmartThings app.
4. In the *Developer Mode* window switch **Developer mode** to **On** and enter the IP address of Home Assistant as **Host PC IP**. Confirm.
5. Restart the TV fully: hold the power button on the remote until the Samsung logo appears.

> The TV accepts commands only from the Host PC IP. While it points to Home Assistant, tools on your PC (Apps2Samsung, TizenBrew Installer, Tizen Studio) cannot reach it. To use them, switch the Host PC IP back temporarily.

### 2.2 Add the TV to Home Assistant

1. **Settings → Devices & services → + Add integration** → search **HA-Brew**.
2. TV type: **Samsung (Tizen)**. Name: optional. Host: the IP address of the TV.
3. **Submit**. HA-Brew connects to the TV and reads its model and Tizen version.

If it says it cannot connect, the TV is off, Developer Mode is not on, or the Host PC IP is not the address of Home Assistant (step 2.1).

### 2.3 Add the signing certificate

Samsung TVs accept only signed apps, and **an installed app can only be updated with the same certificate it was first installed with**. Two ways:

#### A. Create a new certificate (recommended for new apps)

You need a free [Samsung account](https://account.samsung.com) with an e-mail address and a computer (Windows, macOS or Linux) in the same network as Home Assistant. Nothing is installed on the computer.

**Overview:** you start in Home Assistant, Home Assistant gives you a command, you run it on your computer and sign in to Samsung in the browser. Home Assistant finishes the rest.

> ⚠️ **The command is not in this guide.** Home Assistant creates it in step 4. It contains your Home Assistant's address and a one-time code, valid for 15 minutes.

**In Home Assistant:**

1. **Settings → Devices & services → HA-Brew** → your TV → **Add certificate**.
2. Choose **Create a new certificate (Samsung account)** → **Submit**.
3. Author name: anything (e.g. your name). Privilege level: leave **Public**. Leave *Other TVs* empty. → **Submit**.
4. A window with **two commands** opens: one for Windows, one for macOS/Linux. Copy the one for your computer (select it, **Ctrl + C**). **Leave this window open.**

**On your computer** (in the same network as Home Assistant):

5. Run the copied command:
   - **Windows**: press **Win + R**, paste (**Ctrl + V**), press **Enter**. A blue PowerShell window opens. Pasting it into an open PowerShell window works too.
   - **macOS / Linux**: open **Terminal**, paste, press **Enter**.
6. Your browser opens the Samsung sign-in page. Sign in. When the page says *Signed in*, close it. The PowerShell/Terminal window closes by itself.

**Back in Home Assistant:**

7. The window from step 4 continues on its own and after a few seconds closes with a success message. The certificate now appears under the TV on the integration page and in the panel under **Certificates**.

If you take longer than 15 minutes, the window times out. Start again at step 1 and you get a new command.

The command has this shape (yours contains a real address and code):

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm 'http://<your-home-assistant>/api/habrew/samsung_login/<one-time-code>/helper.ps1' | iex"
```

The certificate is valid for all your Samsung TVs in HA-Brew and is stored only in Home Assistant. Further certificates reuse the same author key. If port 4794 is busy, close Tizen Studio or another certificate tool and run the command again.

> Apps that are already on the TV were signed with the certificate of the tool you used (e.g. TizenBrew Installer). To update them with the new certificate they must be uninstalled and installed again once, which deletes their data (logins, settings). The panel offers **Uninstall and install again** when the TV refuses an update. To keep the data, upload the old certificate instead (B).

#### B. Upload a certificate you already have

| You installed the app with | File(s) to upload | Where to find them on the PC |
|---|---|---|
| TizenBrew Installer (e.g. Nuvio) | `tizenbrewInstallerConfig.json` | `%USERPROFILE%\share\` |
| Apps2Samsung | `author.p12` + `distributor.p12`, password in `password.txt` | `%APPDATA%\Apps2Samsung\Certificate\<profile>\` |
| Tizen Studio | `author.p12` + `distributor.p12` and their password | your certificate profile folder |

Copy the path from the table into the address bar of Windows Explorer to open the folder.

1. **Settings → Devices & services → HA-Brew** → your TV → **Add certificate**.
2. Choose the format, upload the file(s), fill in the password for `.p12` files → **Submit**.

HA-Brew shows who the certificate belongs to and when it expires. Samsung certificates are valid for about a year.

### 2.4 Add apps

Either in the **HA-Brew panel** (sidebar):

- **TVs** tab → **Other apps on the TV**: apps that are already installed. **Take over** adds one if it is in the catalog or a known app (Nuvio TV).
- **Catalog** tab: about 200 community apps. **Add to TV** → choose the TV and the certificate → optionally *Install right away*.
- **Add from GitHub** on the TV card: any repository with `.wgt` files in its releases.

Or on the integration page: **Add app** → preset (Nuvio TV) or GitHub repository → certificate.

Continue with [part 4](#4-everyday-use).

---

## 3. LG TV (webOS)

No root is needed. HA-Brew uses LG's official Developer Mode, the same way Homebrew Channel does.

### 3.1 Create an LG developer account

1. On a computer or phone open [webostv.developer.lge.com](https://webostv.developer.lge.com/) → **Sign in** → create an account. It is free.

### 3.2 Install and turn on Developer Mode on the TV

1. On the TV open the **LG Content Store** (Apps) and install the app **Developer Mode**.
2. Open **Developer Mode** and sign in with the developer account.
3. Switch **Dev Mode Status** on. The TV restarts.
4. Open **Developer Mode** again. It shows the remaining session time (1000 hours).

If you already use Homebrew Channel, this is done; HA-Brew works alongside it.

### 3.3 Add the TV to Home Assistant

1. On the TV, in the **Developer Mode** app, switch **Key Server** on. A **passphrase** of 6 characters appears on the screen. Keep the app open.
2. In Home Assistant: **Settings → Devices & services → + Add integration** → **HA-Brew**.
3. TV type: **LG (webOS)**. Name: optional. Host: the IP address of the TV → **Submit**.
4. Type the **passphrase** from the TV screen → **Submit**.

HA-Brew downloads the Developer Mode key once and checks it. You can switch **Key Server** off now.

| Message | What to do |
|---|---|
| Key Server is not reachable | Key Server is off, or the Developer Mode app was closed. Switch it on and keep the app open. |
| Wrong passphrase | Type it again exactly as shown (capital letters and digits). |
| TV does not accept SSH connections on port 9922 | Dev Mode Status is off, or the session ran out. Turn it on in the Developer Mode app. |

### 3.4 Add apps

- **HA-Brew panel → TVs**: apps installed through Homebrew Channel are listed under *Other apps on the TV*. **Take over** adds them. Nuvio TV and YouTube AdFree are set up with one click. Updates install over the existing app and keep its data.
- **Catalog** tab → **LG**: the [webOS Homebrew repository](https://repo.webosbrew.org). Apps marked *needs root* do not work on a TV without root.
- **Add from GitHub**: any repository with `.ipk` files in its releases.
- On the integration page: **Add app** → Nuvio TV, YouTube AdFree or GitHub.

### 3.5 The Developer Mode session

LG ends the Developer Mode session after 1000 hours, and the TV then **removes every app installed in Developer Mode** (Homebrew Channel included). HA-Brew restarts the session once a day, also while the TV is off.

- Sensor **Developer Mode remaining** shows the hours left. The panel shows it too, with an **Extend** button.
- If the session cannot be extended or less than 7 days are left, a notice appears under **Settings → Repairs**.
- If you switch Dev Mode off and on again, the TV creates a new key. Home Assistant then shows *Re-authentication required* for HA-Brew: open it, switch Key Server on and type the new passphrase.

---

## 4. Everyday use

- Each app has an entity `update.<tv>_<app>`. New versions show up under **Settings → Updates** together with your other Home Assistant updates. **Install** updates the app.
- The HA-Brew panel shows all apps with the installed and the available version, and lets you install, launch (▶) and remove them.
- Removing an app (🗑) offers **Only stop managing** (the app stays on the TV) or **Uninstall from TV**.
- Each app has a button `button.<tv>_launch_<app>` that starts it on the TV, handy in automations (e.g. "start the launcher when the TV turns on"). It wakes the TV first if a wake-up method is set.
- Samsung TVs have `sensor.<tv>_active_app`: the name of the HA-Brew app on screen, **Other app** (Samsung Home, Netflix, HDMI …) or **Off** when the TV does not answer. The attribute `running` lists HA-Brew apps running in the background. On LG the built-in LG webOS integration already shows the current app (media player source).

### Turning the TV on for updates

A TV in standby does not answer. On the integration page choose **Configure** and pick how HA-Brew wakes the TV before installing:

- **Wake-on-LAN**: enter the MAC address of the TV (router or TV menu *About this TV*). Samsung: also switch on *Settings → General → Network → Expert Settings → Power On with Mobile*.
- **Turn on an entity**: the `media_player` of the TV from another integration (Samsung Smart TV, SamsungTV Smart, LG webOS TV). HA-Brew calls *turn on* on it.

HA-Brew then waits up to 60 seconds for the TV.

---

## 5. Problems

| Message | Cause and fix |
|---|---|
| Author certificate not match (Samsung) | The app was installed with another certificate. Add that certificate (part 2.3). If you do not have it, the panel offers **Uninstall and install again**; the app loses its data (logins, settings). |
| Certificate / signature refused (Samsung) | Wrong or expired certificate. Check the expiry in the panel's *Certificates* tab. |
| Creating a certificate: Samsung account has no e-mail address | Add one in your [Samsung account profile](https://account.samsung.com/membership/getProfileInfo.do) and start again. |
| Creating a certificate: too many requests | Samsung limits how often certificates can be issued. Try again in an hour. |
| Creating a certificate: the dialog keeps waiting | The command must run on a computer in the same network as Home Assistant, and you must finish the sign-in in the browser it opened. Windows: if the window closed at once, port 4794 is busy (Tizen Studio). |
| This package needs Tizen X or newer | The app does not support your TV's Tizen version. |
| TV not reachable | TV off and no wake-up method set, Developer Mode off, or (Samsung) the Host PC IP was changed. |
| The TV did not remove the app | Some Samsung TVs from 2021 on ignore uninstall commands. Remove the app on the TV: *Apps* → select it → *Delete*. |
| Developer Mode notice in Repairs (LG) | Turn the TV on, open Developer Mode and press *Extend*, or press **Extend Developer Mode** in Home Assistant. If Dev Mode is off, sign in again and switch it on. |

### Reporting a problem

1. **Settings → Devices & services → HA-Brew** → ⋮ next to your TV → **Download diagnostics**. Have the TV switched on, so the file also contains what the TV reports.
2. Open an [issue on GitHub](https://github.com/Michailjovic/HA-Brew/issues), describe what you did and attach the file.

The diagnostics file contains the TV model and system version, the apps and their versions, and the last error messages. IP and MAC addresses, the DUID, serial number, keys, passphrase and certificate details are removed.
