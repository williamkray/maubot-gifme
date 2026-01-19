# gifme
[![Chat on Matrix](https://img.shields.io/badge/chat_on_matrix-%23dev:mssj.me-green)](https://matrix.to/#/#dev:mssj.me)

A maubot plugin that saves gifs, memes, or optionally any other message, associates tags with it, and returns a random match when those tags are used. Written because GIPHY has gone downhill and a private collection is more reliable for a community’s expectations.

NOTE: this bot has only been tested with SQLite as the plugin database engine. it theoretically now has PostgreSQL support added but it is untested. please let me know if it works!

**Fallback:** when the local database has no (or too few) hits, the bot can fall back to **GIPHY** or **Klipy**. Add the relevant API key(s) in config. **Tenor is no longer supported.** Google acquired Tenor and later deprecated the public Tenor API with the kind of opaque deprecation notice that’s become typical og Google. We’ve switched to [Klipy](https://klipy.com) as the alternative, which offers a Tenor-compatible API.

The plugin works with **PostgreSQL** (untested, see note above) or **SQLite**.

---

## Installation

Install like any other maubot plugin: create a `.zip` of this repository and upload it, or use `mbc build` to generate and upload a package to your maubot server.

---

## Commands

| Command | Description |
|--------|-------------|
| `!gifme <phrase>` | Return a random image that matches the phrase. Prefers the local database; falls back to GIPHY or Klipy if enabled and the DB has too few results. |
| `!gifme giphy <phrase>` | Skip the DB and fetch directly from GIPHY. |
| `!gifme klipy <phrase>` | Skip the DB and fetch directly from Klipy. |
| `!gifme save <phrase>` | In **reply** to a message: save it and tag it with the phrase. If it’s already stored, new tags are merged and duplicates ignored. |
| `!gifme tags` | In **reply** to a message the bot sent: show the tags for that stored entry. |
| `!gifme delete` | In **reply** to a message the bot sent: remove that entry from the database. |

---

## Reactions and saving

### Saving with reactions

- **💾 (floppy only)** on **any** message: save that message. Tags are taken from the filename (for media) or the body (for text). Subject to `restrict_users` / `allowed_users` if set.

- **💾 SAVE?** on a **bot** message that came from GIPHY or Klipy: save that image with filename‑derived tags. The bot replies with a **✅ SAVED!** reaction when it’s done. Further **💾 SAVE?** on the same message are ignored.

### What the bot adds to its own messages

- **From GIPHY:** reactions `Powered by GIPHY` and `💾 SAVE?` (attribution and a one‑click save).
- **From Klipy:** reactions `Powered by KLIPY` and `💾 SAVE?`.
- **From the local DB:** reaction `🗃️ from my archives` so it’s clear the image was already saved.

---

## Config

| Option | Description |
|--------|-------------|
| `command_aliases` | List of command names. The first is the main one (e.g. `gifme`, `gif`). |
| `allow_fallback` | Fallback when the DB has too few hits: `giphy`, `klipy`, or blank to disable. |
| `fallback_threshold` | Minimum number of DB matches before using fallback. `0` = always use fallback (GIPHY/Klipy only). Default `1`. |
| `giphy_api_key` | GIPHY API key; needed if `allow_fallback` is `giphy`. |
| `klipy_api_key` | [Klipy](https://klipy.com) API key; needed if `allow_fallback` is `klipy`. |
| `allow_non_files` | Allow saving and returning plain‑text messages (quoted, with sender). *Privacy:* this stores body and sender in the DB even in encrypted rooms. |
| `restrict_users` | If `true`, only `allowed_users` can save (commands and 💾 / 💾 SAVE? reactions). |
| `allowed_users` | List of Matrix IDs allowed to save when `restrict_users` is `true`. |
| `decryption_for_save` | If `true`, the bot will decrypt image events in encrypted rooms when saving. Decrypted files are re‑uploaded **unencrypted** to the homeserver and stored/resent as normal. Requires mautrix crypto (E2EE). Default `false`. |

---

