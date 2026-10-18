# Steam Deck Rocket League Kit

**BakkesMod and custom training maps for Rocket League on the Steam Deck.**

[![Steam Deck](https://img.shields.io/badge/Steam%20Deck-SteamOS%203-1a9fff?logo=steamdeck&logoColor=white)](#step-by-step-setup-on-the-steam-deck)
[![Rocket League](https://img.shields.io/badge/Rocket%20League-Epic%20via%20Heroic-ff7a00)](#1-install-heroic-and-rocket-league)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Cash App](https://img.shields.io/badge/tip%20on%20Cash%20App-%24areolite2-00d632?logo=cashapp&logoColor=white)](https://cash.app/$areolite2)

**Quick start** (Desktop Mode → Konsole), once Rocket League is installed in Heroic:

```bash
git clone https://github.com/Areolite1/steamdeck-rl-kit.git ~/steamdeck-rl-kit && bash ~/steamdeck-rl-kit/install.sh
```

New to Desktop Mode? Follow the [step-by-step guide](#step-by-step-setup-on-the-steam-deck) below.

> 💚 **Free and open source. If it saved you an afternoon, a tip keeps it maintained:
> [Cash App $areolite2](https://cash.app/$areolite2)** · ⭐ Starring the repo helps other Deck players find it.

---

Works with **Rocket League (Epic Games version)** on the **Steam Deck**, running through the
**Heroic Games Launcher** in Desktop Mode.

Getting BakkesMod to work on the Deck is fiddly. The obvious ways either never start the game or
start BakkesMod in a separate Proton container where it can't see the game. This kit does it the
way that works, and adds:

- **BakkesMod**, installed into Rocket League's own Proton prefix with a start-menu shortcut.
- **Custom maps** (Lethamyr's ring courses, pinch and air-dribble maps) with a one-click map picker.

---

## Step-by-step setup on the Steam Deck

Everything happens in **Desktop Mode**. You don't need a `sudo` password or any system changes.
A mouse and keyboard help, but the Deck's controls work too:

| Need to... | On the Deck |
|---|---|
| Switch to Desktop Mode | Press **Steam** → **Power** → **Switch to Desktop** |
| Bring up the on-screen keyboard | Press **Steam + X** |
| Left / right click | Right trackpad click / **L2** tap, or **R2** / **L2** |
| Paste into Konsole | **Ctrl + Shift + V** (or right-click → Paste) |
| Open the start menu | Click the **Steam Deck logo** at the bottom-left of the taskbar |
| Go back to Game Mode | Double-click **Return to Gaming Mode** on the desktop |

### 1. Install Heroic and Rocket League

1. In Desktop Mode, open **Discover** (the shopping-bag icon on the taskbar).
2. Search for **Heroic Games Launcher**, click **Install** and wait for it to finish.
3. Open **Heroic** from the start menu, go to **Log in**, and sign in with your **Epic Games**
   account (the one with Rocket League on it).
4. In Heroic's **Library**, find **Rocket League**, click **Install**, keep the default folder,
   and wait for the download (about 25 GB).
5. Set Rocket League to use **GE-Proton**:
   - In Heroic's left menu, open **Wine Manager** → **GE-Proton** and click the download
     arrow next to the newest version.
   - Go back to the Library, open **Rocket League** → **⚙ Settings** → **Wine** (or
     **Wine/Proton**), and choose that **GE-Proton** version.
6. Click **Play** once, wait for the main menu, then quit the game. This creates the game's
   Proton setup, which the installer needs.

### 2. Download this kit

**Option A: with Konsole (recommended).**
Open the start menu → **System** → **Konsole**, then paste these lines and press Enter after each:

```bash
git clone https://github.com/Areolite1/steamdeck-rl-kit.git ~/steamdeck-rl-kit
cd ~/steamdeck-rl-kit
bash install.sh
```

**Option B: without typing commands.**
1. On this GitHub page, click the green **Code** button → **Download ZIP**.
2. Open **Dolphin** (the folder icon), go to **Downloads**, right-click
   `steamdeck-rl-kit-main.zip` → **Extract** → **Extract archive here**.
3. Rename the extracted folder to `steamdeck-rl-kit` and move it to your **Home** folder.
4. Open that folder, right-click an empty spot → **Open Terminal Here**, type `bash install.sh` and
   press Enter.

Either way, the installer prints what it finds and finishes with **Done**. If it stops with a
message instead, it says what's missing. Usually Rocket League hasn't been launched once yet, or
isn't set to GE-Proton. Fix that and run `bash install.sh` again.

### 3. Download the maps (optional, about 1.4 GB)

In Konsole:

```bash
~/steamdeck-rl-kit/maps/download-maps.sh
```

Wait until it prints `Maps are in ...`. Maps it already has are skipped, so you can run it again
any time, for example after new maps are added to the list.

### 4. Play

Launch Rocket League from Heroic, then use the new start-menu shortcuts. Sections below explain
each one. The kit lives in Desktop Mode: the shortcuts don't work in Game Mode.

### Updating the kit

```bash
cd ~/steamdeck-rl-kit && git pull && bash install.sh
```

(With Option B, download the ZIP again and replace the folder.)

### What the installer does

1. Finds Rocket League, its Wine prefix and its Proton version in Heroic's settings.
2. Downloads the latest **official BakkesMod release** from
   [github.com/bakkesmodorg](https://github.com/bakkesmodorg/BakkesModInjectorCpp/releases), checks
   the SHA-256 checksums, and installs it into the game's prefix.
3. Adds two start-menu shortcuts: **BakkesMod** and **Rocket League Maps**.

Nothing outside your home folder is changed, and SteamOS updates don't remove it.

---

## BakkesMod

1. Launch Rocket League from Heroic as usual.
2. At the main menu, open the start menu (the Steam Deck logo at the bottom-left) → **BakkesMod**.
   Its small window stays behind the game. That's normal.
3. Go into Free Play and press **F2** for the BakkesMod menu, or **F6** for its console.

Tips:

- Free Play settings such as **unlimited flips** (`sv_soccar_unlimitedflips 1`) only apply when
  Free Play starts. Change them, leave Free Play, and start it again.
- On a controller, map **F2** to a back button in Steam Input.
- BakkesMod only works offline: Free Play, training, private matches, workshop maps and replays.
  It switches itself off in online matches.

**Why not Heroic's "script before launch"?** It waits for the script and the game never starts.
**Why not a second `umu-run`?** BakkesMod would start in its own container, can't reach the
game's Wine server, and quits right away. The shortcut runs BakkesMod inside Heroic's flatpak
with the game's own Proton `wine`, which joins the running game.

---

## Custom maps

Epic's version has no Steam Workshop, so custom maps load **in place of Underpass**.

```bash
~/steamdeck-rl-kit/maps/download-maps.sh                # all maps (~1.4 GB)
~/steamdeck-rl-kit/maps/download-maps.sh "Ice Rings"    # or just some
```

Then:

1. Open **Rocket League Maps** from the start menu and pick a map. Do this while the game is
   closed or at the main menu.
2. In Rocket League, start **Free Play** on **Underpass**. The custom map loads instead.
3. Pick **Normal Underpass** in the list to undo it. The original file is backed up in
   `~/Games/RL-Maps/_original`.

Included in `maps/maps.txt`. Each map downloads from its creator's own page and is **not**
redistributed here. All credit goes to the creators:

| Map | What it trains | Creator |
|---|---|---|
| Neon Heights / Ice / Lava / Medieval Rings | aerial car control through ring courses | [Lethamyr](https://lethamyr.com) ([Patreon](https://www.patreon.com/Lethamyr)) |
| Pinch Distance, Pinch Distance Challenge, Pinch Map | pinches (distance and accuracy) | [BakkesPlugins](https://bakkesplugins.com/maps) creators |
| Air Dribble Hoops, Air Dribble Challenge, Air Dribble Length Map | air dribbles and height | [BakkesPlugins](https://bakkesplugins.com/maps) creators |

To add another map, add a line to `maps/maps.txt`, or drop a folder with a `.udk`/`.upk` file into
`~/Games/RL-Maps`.

---

## FAQ

**Can I get banned for this?**
BakkesMod has been tolerated by Psyonix for years because it only works offline: it switches itself
off in online matches. The custom maps also only load offline (Free Play, LAN or private matches).
Use at your own risk; nobody can promise how a game company will treat third-party tools.

**Does it work in Game Mode?**
Not yet. The shortcuts need Desktop Mode. Rocket League itself runs fine in
Desktop Mode, and with Heroic in fullscreen it feels the same.

**I have Rocket League on Steam, not Epic. Does it work?**
No. The kit is built for the Epic version through Heroic, which is how most Deck players run the
game now. The Steam version uses different folders and launch steps.

**Does it work on a regular Linux PC?**
Probably, if you use Heroic as a flatpak and Rocket League runs on Proton. It's only tested on the
Steam Deck (SteamOS 3.8).

**Can I play custom maps with friends?**
Yes, but everyone needs the same map loaded, the **Rocket Plugin** for BakkesMod
([bakkesplugins.com/plugins/view/26](https://bakkesplugins.com/plugins/view/26)), and a shared
VPN such as Hamachi. Lethamyr's [FAQ](https://lethamyr.com/faq) has the full steps.

**Why aren't the maps and BakkesMod included in the repo?**
They belong to their creators. The kit downloads them from the official pages instead, so you
always get the real, latest files and the creators get the credit (and the downloads).

**Rocket League updated and BakkesMod stopped working.**
That's normal after a game patch: BakkesMod needs its own update, which usually comes within a day
or two. Run `bash install.sh` again afterwards to grab the newest release.

**A Rocket League update reset my custom map.**
Updates restore the original Underpass. Open **Rocket League Maps** and pick your map again.

**Can I add my own maps?**
Yes. Put a folder with the map's `.udk` or `.upk` file in `~/Games/RL-Maps`, or add a line to
`maps/maps.txt` and run `download-maps.sh`.

**How can I support this?**
Star the repo, share it with other Deck players, and if it helped, tips on Cash App are very
welcome: **[$areolite2](https://cash.app/$areolite2)**. Please support the map makers too (for
example [Lethamyr on Patreon](https://www.patreon.com/Lethamyr)).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| BakkesMod shortcut does nothing | Start it only when the game is at the main menu. Check `~/Games/Heroic/rl-deck-kit/bakkesmod.log`. Re-run `install.sh` after changing Proton versions. |
| F2 does nothing | BakkesMod may be updating, or out of date after a game patch. Wait for a BakkesMod update. |
| Rocket League won't launch from Heroic | Make sure Heroic's *Script before launch* for Rocket League is empty. |
| Custom map doesn't load | Pick it while the game is in the menu, then start **Underpass**. After a game update, pick the map again. |

## Uninstall

```bash
rm -rf ~/steamdeck-rl-kit ~/Games/Heroic/rl-deck-kit ~/.config/rl-deck-kit
rm -f ~/.local/share/applications/rlkit-*.desktop
~/Games/RL-Maps   # delete it if you don't want the maps; run "restore" in the map picker first
```

BakkesMod lives in the game's prefix (`drive_c/Program Files/BakkesMod`). Delete that folder to
remove it.

---

## Support

If this saved you an afternoon of fiddling, tips are appreciated:

**Cash App: [$areolite2](https://cash.app/$areolite2)** 🙏

## Credits and disclaimer

- [BakkesMod](https://bakkesmod.com) by the BakkesMod team. Downloaded from their official
  releases, not included here.
- Maps by their creators (see the table above). Downloaded from their pages, not included here.

Not affiliated with Psyonix, Epic Games, Valve, BakkesMod, or any map creator. Use
BakkesMod and custom maps offline only, and follow Rocket League's terms of service. The code in
this repo is MIT-licensed (see `LICENSE`).
