# Spotify Integration — Manual QA Test Plan

Systematic checklist for verifying all parts of the Spotify integration end-to-end.

**Prerequisites:**
- Familiar running (backend + frontend)
- A Spotify account with some saved tracks/playlists
- Spotify API credentials configured (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
- Some local music in your library (ideally with overlap to your Spotify favorites)

---

## 1. Initial State (Not Configured)

**Setup:** Remove or clear the Spotify API credentials from Settings > Admin.

| # | Step | Expected Result |
|---|------|-----------------|
| 1.1 | Go to Settings tab | Spotify section shows amber warning: "Spotify API not configured" |
| 1.2 | Verify no Connect button is visible | Only the warning message and instructions to set env vars appear |
| 1.3 | Re-add valid SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in Admin | Settings save successfully |
| 1.4 | Return to Settings tab | Warning disappears, green "Connect Spotify" button appears |

---

## 2. OAuth Connection Flow

| # | Step | Expected Result |
|---|------|-----------------|
| 2.1 | Click "Connect Spotify" | Browser redirects to Spotify's authorization page |
| 2.2 | Log in to Spotify (if needed) and click "Agree" | Redirected back to Familiar at `/settings?spotify_connected=true&spotify_user=<your_username>` |
| 2.3 | Check the Settings page after redirect | Shows "Connected as **your_username**" with green checkmark icon |
| 2.4 | URL params are cleaned up | URL no longer contains `spotify_connected` or `spotify_user` params |
| 2.5 | Verify Sync and Disconnect buttons appeared | Green "Sync" button and gray "Disconnect" button visible |
| 2.6 | Verify "Favorite matched tracks" checkbox is visible | Checkbox present above the action buttons, checked by default |

**Error case:**
| 2.7 | Open a new tab, manually hit `GET /api/v1/spotify/auth` without a profile header | Returns 401 error |
| 2.8 | Decline authorization on Spotify's page | Redirected back to `/settings?spotify_error=access_denied` with error message shown |

---

## 3. Favorites Sync

| # | Step | Expected Result |
|---|------|-----------------|
| 3.1 | Click "Sync" button | Button changes to "Syncing..." with a spinner |
| 3.2 | Watch the progress area | Progress bar appears with phase text |
| 3.3 | Phase: "Connecting to Spotify..." | Shows briefly as connection is established |
| 3.4 | Phase: "Fetching tracks from Spotify..." | Progress bar pulses, shows "X tracks fetched" counter incrementing |
| 3.5 | Phase: "Matching to local library..." | Progress bar fills with percentage, current track name shown below |
| 3.6 | Stats grid during sync | Three boxes showing New / Matched / Unmatched counts updating in real-time |
| 3.7 | Sync completes | Progress disappears, Sync Statistics card appears/updates |
| 3.8 | Verify Sync Statistics card | Shows Total Favorites, Matched (green), Unmatched (orange), Match Rate % |
| 3.9 | Verify "Last synced" timestamp | Shows current date/time at bottom of stats card |
| 3.10 | Click Sync again | Should run again without error (incremental — new tracks only) |
| 3.11 | Try double-clicking Sync rapidly | Second request returns "already_running" and doesn't start a duplicate |

**With "Favorite matched" option:**
| 3.12 | Ensure "Favorite matched tracks in local library" is checked | Checkbox is checked |
| 3.13 | Run sync | After completion, matched tracks should appear in your Favorites |
| 3.14 | Go to Library, check your favorites | Tracks that matched from Spotify should now be favorited locally |
| 3.15 | Uncheck the option, sync again | New matches should NOT be auto-favorited |

---

## 4. Missing Tracks / Unmatched Favorites

**Precondition:** Sync completed with at least some unmatched tracks (unmatched > 0).

| # | Step | Expected Result |
|---|------|-----------------|
| 4.1 | "Missing from Library" section appears below stats | Shows shopping cart icon, count of unmatched tracks |
| 4.2 | Section is expanded by default | Track list visible |
| 4.3 | Click the header to collapse | Track list hides, chevron changes direction |
| 4.4 | Click again to expand | Track list reappears |
| 4.5 | Check a track row | Shows track name, artist, album |
| 4.6 | Check store search buttons | Each track has colored badge buttons (BC, DC, QB for Bandcamp, Discogs, Qobuz) |
| 4.7 | Click "+N" button on a track (if present) | Remaining store links expand (7D, IT, AZ for 7Digital, iTunes, Amazon) |
| 4.8 | Click a store badge (e.g. BC for Bandcamp) | Opens new tab with a search for that track on that store |
| 4.9 | Verify search URL is correct | URL contains artist and track name as search terms |
| 4.10 | Scroll to bottom of list, click "Load more..." | 20 more tracks load |
| 4.11 | "Sorted by date added" label visible | Small clock icon and label at top of list |

---

## 5. Spotify Playlist Import (API-based)

**Precondition:** Spotify connected with playlists in your account.

| # | Step | Expected Result |
|---|------|-----------------|
| 5.1 | `GET /api/v1/spotify/playlists` via browser/curl | Returns JSON array of your Spotify playlists with id, name, track_count, image_url |
| 5.2 | Pick a playlist ID from step 5.1 | Note the ID |
| 5.3 | `GET /api/v1/spotify/playlists/{id}/tracks` | Returns tracks with in_library (true/false) and local_track_id for matches |
| 5.4 | Check match_rate in response | Shows percentage like "45%" |
| 5.5 | `POST /api/v1/spotify/playlists/{id}/import` with `{"include_missing": true}` | Returns imported playlist with id, name, track_count |
| 5.6 | Go to Playlists tab in the UI | New playlist appears with the Spotify playlist name |
| 5.7 | Open the imported playlist | Shows both local (playable) and external (grayed out) tracks |
| 5.8 | Try playing a matched track | Plays normally from local library |
| 5.9 | Import same playlist again with `{"name": "Custom Name"}` | Creates a second playlist with "Custom Name" |
| 5.10 | Import with `{"include_missing": false}` | Playlist only contains locally-matched tracks |

---

## 6. GDPR Data Export Import

### 6a. Requesting your export

| # | Step | Expected Result |
|---|------|-----------------|
| 6a.1 | Visit spotify.com/account > Privacy > Download your data | Request submitted (takes days to arrive) |
| 6a.2 | **OR** manually create a test `YourLibrary.json` file for testing | See format below |

<details>
<summary>Minimal test YourLibrary.json</summary>

```json
{
  "tracks": [
    {
      "artist": "Radiohead",
      "album": "OK Computer",
      "track": "Paranoid Android",
      "uri": "spotify:track:6LBBufCKErp25KNKPI0rPP"
    },
    {
      "artist": "Boards of Canada",
      "album": "Music Has the Right to Children",
      "track": "Roygbiv",
      "uri": "spotify:track:2M6xSjMdEC0k8q4RYAIOQH"
    }
  ]
}
```
</details>

<details>
<summary>Minimal test Playlist1.json</summary>

```json
{
  "playlists": [
    {
      "name": "Test Playlist",
      "lastModifiedDate": "2024-06-01",
      "items": [
        {
          "track": {
            "trackName": "Everything In Its Right Place",
            "artistName": "Radiohead",
            "albumName": "Kid A",
            "trackUri": "spotify:track:2kSGHg08sCaXNYWnMGJBBm"
          },
          "addedDate": "2024-01-15"
        }
      ],
      "description": "A test playlist",
      "numberOfFollowers": 0
    }
  ]
}
```
</details>

### 6b. Upload and Preview

| # | Step | Expected Result |
|---|------|-----------------|
| 6b.1 | Scroll down in Settings to "Import Spotify Data Export" section | Upload zone visible with drag-and-drop area |
| 6b.2 | Click the link to "spotify.com/account > Privacy > Download your data" | Opens Spotify privacy page in new tab |
| 6b.3 | Click the drop zone | File picker opens, accepts .zip and .json |
| 6b.4 | Select your export .zip or .json file | Spinner shows "Processing export file..." |
| 6b.5 | Wait for processing | Preview appears with found file names |
| 6b.6 | Check stats grid | Shows Saved Tracks count with matched/match rate |
| 6b.7 | If playlists exist in export | Shows Playlists count with total tracks |
| 6b.8 | If streaming history exists | Shows Stream Events count with unique tracks |
| 6b.9 | Check playlist details section | Lists each playlist name with "X/Y matched" |

### 6c. Import Options

| # | Step | Expected Result |
|---|------|-----------------|
| 6c.1 | "Import saved tracks as Spotify favorites" checkbox | Present and checked by default |
| 6c.2 | "Import playlists (matched tracks only)" checkbox | Present and checked by default |
| 6c.3 | "Favorite matched tracks in local library" checkbox | Present and unchecked by default |
| 6c.4 | Uncheck "Import saved tracks" | Will skip favorites import |
| 6c.5 | Uncheck "Import playlists" | Will skip playlist creation |
| 6c.6 | Check "Favorite matched" | Will add matched tracks to local favorites |

### 6d. Execute Import

| # | Step | Expected Result |
|---|------|-----------------|
| 6d.1 | Click "Import" button | Button changes to "Importing..." with spinner |
| 6d.2 | Wait for completion | "Import Complete" message with green checkmark |
| 6d.3 | Check result stats | Shows Favorites imported, Playlists created, Tracks favorited counts |
| 6d.4 | If any errors | Red error section shows at bottom |
| 6d.5 | Click "Import Another" | Resets back to upload zone for another file |
| 6d.6 | Go to Playlists tab | Imported playlists appear |
| 6d.7 | If "Favorite matched" was checked, go to Library favorites | Matched tracks are favorited |

### 6e. Error Cases

| # | Step | Expected Result |
|---|------|-----------------|
| 6e.1 | Upload a .txt or .png file | File picker should reject (accepts only .zip/.json) |
| 6e.2 | Upload an empty .json file (`{}`) | Error: "No recognizable Spotify data found in file" |
| 6e.3 | Upload a random .json that isn't a Spotify export | Error: "No recognizable Spotify data found in file" |
| 6e.4 | Click "Cancel" during preview | Resets to upload zone, no import happens |
| 6e.5 | Drag a file over the drop zone | Border turns green, zone highlights |
| 6e.6 | Drag file away without dropping | Zone returns to normal state |

---

## 7. Disconnect

| # | Step | Expected Result |
|---|------|-----------------|
| 7.1 | Click "Disconnect" button | Button shows loading state briefly |
| 7.2 | Check page state | Returns to "Connect Spotify" button state |
| 7.3 | Sync Statistics card disappears | No stats shown |
| 7.4 | Missing Tracks section disappears | No unmatched tracks section |
| 7.5 | `GET /api/v1/spotify/status` | Returns `connected: false` |
| 7.6 | Click "Connect Spotify" again | OAuth flow works to re-connect |
| 7.7 | Sync after reconnecting | Should re-fetch all favorites (previous data was deleted) |

---

## 8. Edge Cases and Error Handling

| # | Step | Expected Result |
|---|------|-----------------|
| 8.1 | Start a sync, then navigate away from Settings | Sync continues in background |
| 8.2 | Return to Settings while sync is running | Progress polling resumes, shows current progress |
| 8.3 | Start sync with no internet / Spotify down | Error message appears, doesn't crash UI |
| 8.4 | Open Settings on a brand-new profile (never connected) | Shows "Connect Spotify" button, no errors |
| 8.5 | Check Spotify status API with no profile header | Returns `configured: true, connected: false` (no error) |
| 8.6 | Sync with 0 Spotify favorites | Completes quickly with all stats at 0 |
| 8.7 | Sync with a very large library (1000+ tracks) | Progress updates smoothly, pagination works, completes without timeout |

---

## 9. Match Quality Spot-Check

After a sync, manually verify a few matches are correct:

| # | Step | Expected Result |
|---|------|-----------------|
| 9.1 | Pick 3-5 matched tracks from sync stats / API | Note track names |
| 9.2 | Find each in your local library | Correct track matched (same song, same artist) |
| 9.3 | Check a track with "feat." in the Spotify title | Should still match to local version without "feat." |
| 9.4 | Check a track with "(Remastered)" in Spotify title | Should match to local version without annotation |
| 9.5 | Look at unmatched tracks | Verify these genuinely aren't in your local library |

---

## 10. Data Persistence

| # | Step | Expected Result |
|---|------|-----------------|
| 10.1 | Restart the backend server | |
| 10.2 | Go to Settings | Still shows "Connected as username" (tokens persisted in DB) |
| 10.3 | Sync stats still displayed | Total Favorites, Matched, etc. from previous sync |
| 10.4 | Missing tracks section still works | Same unmatched tracks shown |
| 10.5 | Imported playlists still visible | Playlists from import persist in Playlists tab |
| 10.6 | Restart frontend (clear browser) | Same state after page load |

---

## Quick Smoke Test (5 minutes)

If you only have a few minutes, do these steps for a quick sanity check:

1. Go to Settings > Spotify section
2. Verify connected state shows username + stats (or connect if needed)
3. Click Sync, watch progress through to completion
4. Check stats update with new numbers
5. Scroll down to Missing Tracks, verify store links open correctly
6. Scroll down to Import section, upload a test .json file
7. Verify preview, click Import, verify result counts
8. Click Disconnect, verify clean state
9. Reconnect, verify OAuth flow works again
