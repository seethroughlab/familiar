# Installing Familiar on Your Mac

This guide walks you through every step. No prior experience with Terminal or Docker is needed.

You'll need about 20 minutes and a Wi-Fi connection.

---

## What You'll Be Installing

Familiar is a music player that uses AI to help you explore your personal music collection. It runs on your Mac using a tool called Docker, which keeps everything self-contained and easy to remove later if you want.

---

## Step 1: Check Your Mac

Click the Apple menu () in the top-left corner of your screen and choose **About This Mac**.

- **Chip**: You'll see either "Apple M1/M2/M3/M4" or "Intel." Both work.
- **Memory**: Look for "8 GB", "16 GB", etc. We'll need this number in a later step.

Leave this window open for reference.

---

## Step 2: Install Docker Desktop

Docker is the app that runs Familiar behind the scenes.

1. Go to [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) and click **Download for Mac**.
   - If asked to choose between "Apple Chip" and "Intel Chip," pick the one that matches what you saw in Step 1.
2. Open the downloaded `.dmg` file and drag the Docker icon into your Applications folder (just like installing any other app).
3. Open **Docker Desktop** from your Applications folder.
   - macOS may ask for your permission the first time. Click **OK** or **Allow**.
   - A whale icon will appear in your menu bar at the top of the screen. Wait until it stops animating — this means Docker is ready.

### If Your Mac Has 8GB of Memory

Open Docker Desktop's settings (click the whale icon in the menu bar, then the gear icon), go to **Resources**, and leave memory at the default (it should be around 4-6 GB). Don't increase it — we'll adjust Familiar's settings instead in a later step.

### If Your Mac Has 16GB or More

Open Docker Desktop's settings (whale icon > gear icon), go to **Resources > Advanced**, and drag the **Memory** slider to **8 GB** or higher. Click **Apply & restart**.

---

## Step 3: Open Terminal

Terminal is a built-in app that lets you type commands. Don't worry — we'll tell you exactly what to type.

1. Press **Command + Space** to open Spotlight Search.
2. Type **Terminal** and press **Enter**.
3. A window will appear with a blinking cursor. This is where you'll type commands.

**Tip:** After typing (or pasting) each command, press **Enter** to run it. Wait for it to finish before typing the next one — you'll know it's done when you see the blinking cursor again on a new line.

---

## Step 4: Download Familiar

1. In your browser, go to: **https://github.com/seethroughlab/familiar/archive/refs/heads/master.zip**
   - This will download a ZIP file to your Downloads folder.
2. Double-click the ZIP file in Finder to unzip it. You'll get a folder called `familiar-master`.
3. Rename the folder to `familiar` (right-click > Rename), then drag it into your **home folder**. To find your home folder in Finder: click **Go** in the menu bar, then **Home** (or press **Shift + Command + H**).

Now, in Terminal, type:

```
cd ~/familiar/docker
```

This moves you into Familiar's folder.

---

## Step 5: Find Your Music Folder

Before the next step, you need to know where your music files are on your Mac. Here's how to find out:

1. Open **Finder** (the blue smiley face in your Dock).
2. Look in the sidebar for **Music** under Favorites, or go to your home folder and look for a **Music** folder.
3. If you use **Apple Music** (or the old iTunes), your actual music files are usually inside a subfolder. A common location is:
   ```
   ~/Music/Music/Media.localized/Music
   ```
4. If your music is on an **external drive**, it will be something like:
   ```
   /Volumes/MyDriveName/Music
   ```

**Important:** Familiar can only play files you own (MP3, M4A, FLAC, etc.). Songs you stream from Apple Music or Spotify that you don't own as files won't appear.

Not sure about your path? You can drag your music folder from Finder into the Terminal window — it will paste the full path for you.

---

## Step 6: Set Up Your Configuration

Type this command to create your configuration file (it copies a template):

```
cp .env.example .env
```

Now you need to edit it. Type:

```
open -e .env
```

This opens the file in TextEdit. Find the line that says:

```
MUSIC_LIBRARY_PATH=
```

Type your music folder path from Step 5 after the `=`.

**The easiest and most reliable way** to get the correct path is to drag your music folder from Finder directly into the Terminal window — it will paste the full absolute path for you. Then copy that path into your `.env` file.

For example, your line might look like one of these:

```
MUSIC_LIBRARY_PATH=/Users/yourname/Music
```
```
MUSIC_LIBRARY_PATH=~/Music/Music/Media.localized/Music
```

Both formats work. (`~/` is a shorthand for your home folder — Familiar expands it automatically.)

### If Your Mac Has 8GB of Memory

Add this line anywhere in the file (on its own line):

```
DISABLE_CLAP_EMBEDDINGS=true
```

This turns off the most memory-hungry feature (AI-powered music similarity search) so Familiar runs smoothly on your Mac. Everything else — BPM detection, key detection, energy, mood analysis — still works.

### Save and Close

Press **Command + S** to save, then **Command + W** to close TextEdit.

---

## Step 7: Start Familiar

Back in Terminal, type:

```
./start.sh
```

The first time you run this, Docker will download Familiar's components (~4 GB). This may take several minutes depending on your internet speed — it only happens once.

After the download finishes, the script checks that everything is set up correctly and starts Familiar. You should see:

```
Familiar is running!

  Open http://localhost:4400 in your browser

  First time? Set API keys in your .env file, then open
  Settings (gear icon) to configure your library.
```

If you see an error instead, check the [Troubleshooting](#troubleshooting) section below.

---

## Step 8: Open Familiar in Your Browser

1. Open **Safari** (or any browser you prefer).
2. Go to: **http://localhost:4400**

   (`localhost` means "this computer" — it's not on the internet, just running privately on your Mac.)

You should see the Familiar interface.

---

## Step 9: Initial Setup

1. Open your `.env` file (in the `docker` folder) with a text editor. If you followed the earlier steps, it should already exist.
2. Add your **Anthropic API key**. This is what lets Familiar use Claude (an AI assistant) to create playlists from natural language descriptions like "something upbeat for a road trip."
   - Find the line that says `ANTHROPIC_API_KEY=` and paste your key after the `=` sign (e.g., `ANTHROPIC_API_KEY=sk-ant-...`)
   - If you don't have one, you can get one at [console.anthropic.com](https://console.anthropic.com/). You'll need to create an account and add a payment method. Usage is pay-as-you-go — typically a few cents per conversation.
3. Optionally add **Last.fm** API keys (`LASTFM_API_KEY` and `LASTFM_API_SECRET`). These help with scrobbling and additional track information, but aren't required.
4. Save the file, then restart Docker (run `./stop.sh` then `./start.sh` in Terminal).
5. Open **http://localhost:4400**, click the **gear icon** to open Settings, go to **Library**, and click **Scan Library**.

The initial scan analyzes all your music files. This can take a while depending on your library size — a few minutes for a small collection, potentially an hour or more for thousands of tracks. You can use Familiar while it scans.

---

## Running Automatically (Recommended)

You can set things up so Familiar starts on its own whenever you turn on your Mac — no Terminal needed after the initial setup.

1. Open **Docker Desktop** (click the whale icon in your menu bar, or find it in Applications).
2. Click the **gear icon** to open Settings.
3. Under **General**, check **Start Docker Desktop when you log in**.
4. Click **Apply & restart**.

That's it. Familiar's containers are configured to start automatically whenever Docker is running. So the next time you restart your Mac, just open **http://localhost:4400** in your browser — it will already be there after a minute or so.

To temporarily stop Familiar without turning off auto-start, open Terminal and type:
```
cd ~/familiar/docker
./stop.sh
```

To start it again: `./start.sh` — or just restart Docker Desktop.

---

## Day-to-Day Usage (Manual Start/Stop)

If you prefer not to run Familiar automatically, here's how to start and stop it by hand.

**Starting Familiar:** Open Docker Desktop (if it's not already running), then open Terminal and type:

```
cd ~/familiar/docker
./start.sh
```

Then open **http://localhost:4400** in your browser.

**Stopping Familiar:** In Terminal, type:

```
cd ~/familiar/docker
./stop.sh
```

You can also just quit Docker Desktop, which stops everything.

**Tip:** You don't need to keep Terminal open while using Familiar. Once it's started, you can close the Terminal window and keep using it in your browser.

---

## Updating Familiar

When a new version is available, open Terminal and type:

```
cd ~/familiar/docker
./update.sh
```

That's all. `update.sh` downloads the new version, refreshes the setup scripts, and restarts Familiar automatically. Your music library, settings, and API keys are never touched.

---

## Troubleshooting

**"Docker is not running"**
Open the Docker Desktop app from your Applications folder and wait for the whale icon in the menu bar to stop animating. Then try `./start.sh` again.

**"MUSIC_LIBRARY_PATH does not exist"**
The music folder path in your `.env` file doesn't match a real folder on your Mac. Open the file with `open -e .env` and double-check the path. Remember: you can drag a folder from Finder into Terminal to get the exact path.

**Familiar started but the browser shows a blank page**
Wait a minute and refresh. The first startup takes longer because it needs to download components. If it still doesn't load after 2 minutes, go back to Terminal and type:
```
cd ~/familiar/docker
./stop.sh
./start.sh --logs
```
This will show detailed output that can help diagnose the issue.

**"Container killed" or the app keeps crashing**
Your Mac is running out of memory. Open `.env` with `open -e .env` and make sure this line is present:
```
DISABLE_CLAP_EMBEDDINGS=true
```
Then restart: `./stop.sh` followed by `./start.sh`.

**Scanned my library but no music appears**
- Double-check your `MUSIC_LIBRARY_PATH` in the `.env` file (inside the `docker` folder). Open it with `open -e .env` and confirm the path points to the folder containing your actual audio files
- After changing the path, you must restart Familiar: run `./stop.sh` then `./start.sh` so Docker picks up the new location
- Make sure the path points to the folder containing actual audio files (`.mp3`, `.m4a`, `.flac`), not the Apple Music app itself
- Apple Music streaming-only tracks (ones you don't own) won't appear
- DRM-protected files (`.m4p`) are skipped

---

## Removing Familiar

If you want to uninstall everything:

1. Open Terminal and type: `cd ~/familiar/docker && ./stop.sh`
2. In Finder, drag the `familiar` folder from your home folder to the Trash.
3. Open Docker Desktop > Settings > scroll down to **Troubleshoot** > click **Clean / Purge data**. This removes Familiar's database and cached data.
4. If you no longer need Docker for anything else, drag Docker Desktop from Applications to the Trash to uninstall it.
