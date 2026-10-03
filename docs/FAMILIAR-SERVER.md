# Familiar Server

Familiar Server is the Mac form of the Familiar server: a menu-bar app with the server, its
database, ffmpeg and the analysis models inside it. No Docker and no terminal. Your phone and the
Familiar player connect to it the same way they would to a server on a NAS
([ADR-0131](decisions/ADR-0131-the-server-is-its-own-app.md)).

For Docker on a Mac, or on anything else, see [INSTALLATION.md](INSTALLATION.md).

## What you need

- A Mac with **Apple Silicon** (M1 or later). Intel Macs are not supported.
- **macOS 14** (Sonoma) or later.
- About 1 GB for the app, plus room for its database beside your music.
- A Mac that stays on while you want to listen from elsewhere. A laptop works; analysis pauses on
  battery (below).

## Install

1. Open the [releases page](https://github.com/seethroughlab/familiar/releases), and under the newest
   release's **Assets** download `Familiar-Server-<version>.dmg`.
2. Open it and drag **Familiar Server** to **Applications**.
3. Open Familiar Server from Applications. It has no window and no Dock icon: it lives in the menu
   bar, as a house with a music note.
4. Click that icon and choose **Choose Music Folder…**. Pick the folder your music is in. It can be
   on this Mac or on a network share.

   If the folder is on a network share, or in Desktop, Documents or Downloads, macOS asks whether
   Familiar Server may read it. Allow it.
5. Wait for the menu to say the server is running, then choose **Open Admin**. Your browser opens
   the admin at `http://127.0.0.1:4400`, already signed in.

The first library sync starts on its own. Familiar reads your files where they are and never
writes to the folder: it runs under a macOS sandbox profile that refuses any write there
([ADR-0140](decisions/ADR-0140-familiar-server-enforces-zero-touch-with-a-seatbelt-profile.md)).

## Living with it

- **Updates** arrive by themselves, or from **Check for Updates…** in the menu.
- **Start at Login** in the menu keeps the server running after a restart.
- **Analysis pauses** on battery, in Low Power Mode and when the Mac runs hot, and the menu says
  why. **Analyse Anyway for an Hour** overrides that, and **Pause Analysis** pauses it by hand.
  Playing music never pauses.
- **Quitting** Familiar Server, however you quit it, stops the server.
- **Phones** reach the server only after **Allow Phones to Connect** is on. Until then nothing on
  your network can reach it.

## Where its data lives

`~/Library/Application Support/Familiar Server`: the database, settings, analysis models and
`server.log`. Deleting the app leaves this folder; delete it too to start over. Your music is not
in it.

## If it will not start

- **"Could not start the database: Operation not permitted"** on a Mac that ever ran
  `v0.2.0-beta8`: macOS remembers that build as sandboxed. Run `sfltool resetbtm` in Terminal and
  restart. It resets every app's background items, which then ask again.
- Anything else: the menu shows the error, and `server.log` in the data folder above has the
  detail.
