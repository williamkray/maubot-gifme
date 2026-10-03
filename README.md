# gifme
[![Chat on Matrix](https://img.shields.io/badge/chat_on_matrix-%23dev:mssj.me-green)](https://matrix.to/#/#dev:mssj.me)

A maubot plugin that saves gifs, memes, or optionally any other message, associates tags with it, and returns a random match when those tags are used. Written because GIPHY has gone downhill and a private collection is more reliable for a community’s expectations.

NOTE: this bot has only been tested with SQLite as the plugin database engine. it theoretically now has PostgreSQL support added but it is untested. please let me know if it works!

**Fallback:** when the local database has no (or too few) hits, the bot can fall back to **GIPHY**, **Klipy**, or **DuckDuckGo**. GIPHY and Klipy need an API key in config; DuckDuckGo needs none (it uses DuckDuckGo's unofficial image search, so it may break if they change it). **Tenor is no longer supported.** Google acquired Tenor and later deprecated the public Tenor API with the kind of opaque deprecation notice that’s become typical og Google. We’ve switched to [Klipy](https://klipy.com) as the alternative, which offers a Tenor-compatible API.

**Web archive & widget:** the bot can serve a private, searchable web gallery of everything it has saved, and that same page can be embedded as a Matrix **widget** so you can click a gif to send it straight to the room — no commands needed. See [Web archive & widget](#web-archive--widget) below.

The plugin works with **PostgreSQL** (untested, see note above) or **SQLite**.

---

## Installation

Install like any other maubot plugin: create a `.zip` of this repository and upload it, or use `mbc build` to generate and upload a package to your maubot server.

---

## Commands

| Command | Description |
|--------|-------------|
| `!gifme <phrase>` | Return a random image that matches the phrase. Prefers the local database; falls back to GIPHY, Klipy, or DuckDuckGo if enabled and the DB has too few results. |
| `!gifme giphy <phrase>` | Skip the DB and fetch directly from GIPHY. |
| `!gifme klipy <phrase>` | Skip the DB and fetch directly from Klipy. |
| `!gifme ddg <phrase>` / `!gifme duckduckgo <phrase>` | Skip the DB and fetch directly from DuckDuckGo image search (no API key). |
| `!gifme save <phrase>` | In **reply** to a message: save it and tag it with the phrase. If it’s already stored, new tags are merged and duplicates ignored. |
| `!gifme tags` | In **reply** to a message the bot sent: show the tags for that stored entry. |
| `!gifme delete` | In **reply** to a message the bot sent: remove that entry from the database. |
| `!gifme magiclink` | DM you a private, one-time link to browse the saved-gif web archive in your browser. |
| `!gifme addwidget` | Add the web archive as a **widget** in the current room (the bot names it "GIF Archive"). Requires the bot to have enough power level to edit widgets. |
| `!gifme getwidgetinfo` | Show the widget URL so you can add it manually with `/addwidget`. |

---

## Reactions and saving

### Saving with reactions

- **💾 (floppy only)** on **any** message: save that message. Tags are taken from the filename (for media) or the body (for text). Subject to `restrict_users` / `allowed_users` if set.

- **💾 SAVE** on a **bot** message that came from GIPHY, Klipy, or DuckDuckGo: save that image with filename‑derived tags. The bot replies with a **✅ SAVED!** reaction when it’s done. Further **💾 SAVE** on the same message are ignored.

### Searching by reaction

React to **any plain-text message** with one of the configured `react_search_triggers` (default `🖼️`, `🎬`, or the text `gif`) and the bot runs a search using that message's text as the query — exactly as if you'd typed `!gifme <that text>`. Leave the list empty to disable this.

### What the bot adds to its own messages

- **From GIPHY:** reactions `Powered by GIPHY` and `💾 SAVE` (attribution and a one‑click save).
- **From Klipy:** reactions `Powered by KLIPY` and `💾 SAVE`.
- **From DuckDuckGo:** reactions `Powered by DuckDuckGo` and `💾 SAVE`.
- **From the local DB:** reaction `🗃️ from my archives` so it’s clear the image was already saved.
- **On every result:** `♻️ RETRY` (redo the search for a different result) and `🗑️ TRASH` (silently remove the bot's message). Only the person who made the original request can use these.

---

## Web archive & widget

The plugin can serve a **web gallery** of every saved entry — a paginated, searchable grid of your gifs/images (plus saved text quotes) — over maubot's built-in web server. Enable it with `web_enabled` and make sure your `maubot.yaml`/instance has the web app available (`webapp: true`, included in this plugin).

**Two ways to view it:**

- **In your browser** — run `!gifme magiclink`. The bot DMs you a private, single-use link that signs you in and drops you on the gallery. Search by tag and page through results; no login form, no password.
- **As a Matrix widget** — run `!gifme addwidget` (or add it manually via `!gifme getwidgetinfo`). Inside a Matrix client the widget shows the same gallery with a **"Send to room"** button on each item, so you can search and fire a gif into the chat with one click — no `!gifme` command required. Sending works in clients that implement the widget send-event API (e.g. Element, gomuks); other clients still get full browse/search.

**Authentication.** Nobody can view the archive anonymously:

- The browser link uses a one-time token (valid for `web_magiclink_ttl` seconds) that's exchanged for a session (valid for `web_session_ttl` seconds). Tokens travel in the URL — never cookies — so the same session works inside a widget iframe.
- The widget authenticates you with Matrix's **OpenID** handshake: the bot verifies your identity with your homeserver and confirms you **share a room with the bot** before granting access. Set `web_restrict_to_allowed_users` to further limit viewing to `allowed_users`.

**Public URL.** Links and the widget use maubot's configured `public_url` by default. If the bot is behind a reverse proxy with a different external hostname, set `base_url` explicitly. For widget use the URL must be **https** (browsers block an `http` widget embedded in an `https` client as mixed content).

---

## Config

| Option | Description |
|--------|-------------|
| `command_aliases` | List of command names. The first is the main one (e.g. `gifme`, `gif`). |
| `allow_fallback` | Fallback when the DB has too few hits: `giphy`, `klipy`, `duckduckgo`, or blank to disable. |
| `fallback_threshold` | Minimum number of DB matches before using fallback. `0` = always use fallback. Default `1`. |
| `giphy_api_key` | GIPHY API key; needed if `allow_fallback` is `giphy`. |
| `klipy_api_key` | [Klipy](https://klipy.com) API key; needed if `allow_fallback` is `klipy`. |
| `duckduckgo_force_gif` | Bias DuckDuckGo results toward gif-typed images (`type:gif`). Default `true`. |
| `duckduckgo_size` | Preferred DuckDuckGo image size: `Small`, `Medium`, `Large`, `Wallpaper`, or blank for any. |
| `duckduckgo_safesearch` | Enable DuckDuckGo strict safesearch. Default `true`. |
| `duckduckgo_result_pool` | Randomly pick from the top N relevance-ranked DuckDuckGo results. `1` = strict best match. |
| `allow_non_files` | Allow saving and returning plain‑text messages (quoted, with sender). *Privacy:* this stores body and sender in the DB even in encrypted rooms. |
| `restrict_users` | If `true`, only `allowed_users` can save (commands and 💾 / 💾 SAVE reactions). |
| `allowed_users` | List of Matrix IDs allowed to save when `restrict_users` is `true`. |
| `decryption_for_save` | If `true`, the bot will decrypt image events in encrypted rooms when saving. Decrypted files are re‑uploaded **unencrypted** to the homeserver and stored/resent as normal. Requires mautrix crypto (E2EE). Default `false`. |
| `react_search_triggers` | Reaction keys (emoji or text) that trigger a gif search on a text message. Empty list disables it. Default `🖼️`, `🎬`, `gif`. |
| `web_enabled` | Enable the web archive gallery and widget endpoints. Default `true`. |
| `web_page_size` | Number of entries shown per page in the gallery. Default `60`. |
| `web_magiclink_ttl` | How long a `!gifme magiclink` login link stays valid, in seconds (single-use). Default `300`. |
| `web_session_ttl` | How long a browser/widget session stays valid once authenticated, in seconds. Default `604800` (7 days). |
| `web_restrict_to_allowed_users` | If `true`, only `allowed_users` may view the web archive (`restrict_users` also implies this). Default `false`. |
| `base_url` | Override the public base URL for links/widget. Blank = auto-detect from maubot's `public_url`. Set this if behind a reverse proxy with a different external hostname. |

---

