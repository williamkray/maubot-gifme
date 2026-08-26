# gifme - a maubot plugin to overcome the fact that giphy kinda sucks

from typing import Awaitable, Type, Optional, Tuple
import asyncio
import re
import random
import urllib.parse

from mautrix.client import Client
from mautrix.types import (Event, MessageType, EventID, UserID, FileInfo, EventType, RoomID,
                            MediaMessageEventContent, TextMessageEventContent, ContentURI,
                            ReactionEvent, RedactionEvent, ImageInfo, RelationType, Format)
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

# Optional: for decrypting images in encrypted rooms
try:
    from mautrix.types import EncryptedEvent
except ImportError:
    class _EncryptedEventPlaceholder:
        pass
    EncryptedEvent = _EncryptedEventPlaceholder  # isinstance never matches

try:
    from mautrix.crypto.attachments import decrypt_attachment
except ImportError:
    decrypt_attachment = None

# database table related things
from .db import upgrade_table

# DuckDuckGo has no official API and blocks requests without a realistic browser
# User-Agent, so we send one on every request (token, i.js, image download). The
# vqd token is bound to this UA, so it must stay static.
_DDG_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")



class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("command_aliases")
        helper.copy("allow_fallback")
        helper.copy("fallback_threshold")
        helper.copy("giphy_api_key")
        helper.copy("klipy_api_key")
        helper.copy("duckduckgo_force_gif")
        helper.copy("duckduckgo_safesearch")
        helper.copy("duckduckgo_result_pool")
        helper.copy("allow_non_files")
        helper.copy("restrict_users")
        helper.copy("allowed_users")
        helper.copy("decryption_for_save")


class GifMe(Plugin):

    async def start(self) -> None:
        self.config.load_and_update()
        self._saved_reaction_event_ids: set = set()

    def get_command_name(self) -> str:
        return self.config["command_aliases"][0]

    def is_alias(self, command: str) -> bool:
        return command in self.config["command_aliases"]

    def sanistring(self, query: str) -> str:
        sani = re.sub(r'(\.[a-zA-Z0-9]+)$', '', query) # strip file suffixes first
        sani = re.sub(r'(_|-|\.)', ' ', sani) # substitute common delimiters with normal spaces
        sani = re.sub(r'[^a-zA-Z0-9\s]', '', sani).lower() # strip out any other special characters and make lowercase
        return sani

    def _mimetype_to_suffix(self, mimetype: Optional[str]) -> str:
        """Map mimetype to a file suffix. Default .bin for unknown."""
        if not mimetype:
            return ".bin"
        m = (mimetype or "").strip().lower()
        return {
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/svg+xml": ".svg",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
        }.get(m, ".bin")

    def _resolve_filename_for_media(self, content) -> str:
        """
        Resolve a filename for image/video content. Matrix uses body for captions
        now; prefer an explicit filename, else treat body as caption and derive.
        - If content.filename is set: use as-is.
        - Else if body ends in a suffix matching the mimetype: use body as-is.
        - Else: sanitize body and append the mimetype-derived suffix.
        """
        explicit = getattr(content, "filename", None)
        if explicit and str(explicit).strip():
            return str(explicit).strip()
        body = getattr(content, "body", None) or ""
        info = getattr(content, "info", None)
        mime = getattr(info, "mimetype", None) if info else None
        suffix = self._mimetype_to_suffix(mime)
        if body and suffix and body.lower().endswith(suffix.lower()):
            return body
        base = self.sanistring(body) or "image"
        return base + suffix

    async def get_giphy(self, evt: MessageEvent, query: str) -> None:

        #query = query.replace('"', '') # remove quotes to pass raw terms to giphy
        query = self.sanistring(query)
        api_data = None
        info = {}
        imgdata = None
        url_params = urllib.parse.urlencode({"q": query, "api_key": self.config["giphy_api_key"], "limit": 5})

        ## first we get a json response from giphy with our query parameters
        async with self.http.get(
            "http://api.giphy.com/v1/gifs/search?{}".format(url_params)
        ) as api_response:
            if api_response.status != 200:
                await evt.reply(f"Something went wrong, I got the following response from \
                            the Giphy search API: {api_response.status}")
                return None

            api_data = await api_response.json()

        ## pick a random gif from the list of results returned
        try:
            picked_gif = random.choice(api_data['data'])
        except Exception as e:
            await evt.reply(f"Oops, I had an accident trying to pick a random Gif from Giphy: {e}")

        ## get the info for the gif we've picked
        gif_link = picked_gif['images']['original']['url']
        info['width'] = int(picked_gif['images']['original']['width']) or 480
        info['height'] = int(picked_gif['images']['original']['height']) or 270
        info['size'] = int(picked_gif['images']['original']['size'])
        info['mimetype'] = 'image/gif'
        info['filename'] = f"{query}.gif"

        ## download the image, and upload it to the matrix media repository
        async with self.http.get(gif_link) as response:
            if response.status != 200:
                await evt.reply(f"Something went wrong, I got the following response when \
                                downloading the image from Giphy: {response.status}")
                return None

            imgdata = await response.read()

        try:
            info["original"] = await self.client.upload_media(
                imgdata, mime_type=info["mimetype"], filename=info["filename"]
            )
        except Exception as e:
            await evt.reply(f"Oops, I had an accident uploading my image to matrix: {e}")
            return None

        info["source"] = "giphy"
        return info

    async def get_klipy(self, evt: MessageEvent, query: str) -> None:

        #query = query.replace('"', '') # remove quotes to pass raw terms to klipy
        query = self.sanistring(query)
        api_data = None
        info = {}
        imgdata = None
        url_params = urllib.parse.urlencode({"q": query, "key": self.config["klipy_api_key"], 
                                             "limit": 5})

        ## first we get a json response from klipy with our query parameters
        async with self.http.get(
            "https://api.klipy.com/v2/search?{}".format(url_params)
        ) as api_response:
            if api_response.status != 200:
                await evt.reply(f"Something went wrong, I got the following response from \
                            the Klipy search API: {api_response.status}")
                return None

            api_data = await api_response.json()

        ## pick a random gif from the list of results returned
        try:
            picked_gif = random.choice(api_data['results'])["media_formats"]["gif"]
        except Exception as e:
            await evt.reply(f"Oops, I had an accident trying to pick a random Gif from Klipy: {e}")
            return None

        ## get the info for the gif we've picked
        gif_link = picked_gif['url']
        info['width'] = int(picked_gif['dims'][0]) or 480
        info['height'] = int(picked_gif['dims'][1]) or 270
        info['size'] = int(picked_gif['size'])
        info['mimetype'] = 'image/gif'
        info['filename'] = f"{query}.gif"

        ## download the image, and upload it to the matrix media repository
        async with self.http.get(gif_link) as response:
            if response.status != 200:
                await evt.reply(f"Something went wrong, I got the following response when \
                                downloading the image from Klipy: {response.status}")
                return None

            imgdata = await response.read()

        try:
            info["original"] = await self.client.upload_media(
                imgdata, mime_type=info["mimetype"], filename=info["filename"]
            )
        except Exception as e:
            await evt.reply(f"Oops, I had an accident uploading my image to matrix: {e}")
            return None

        info["source"] = "klipy"
        return info

    async def get_duckduckgo(self, evt: MessageEvent, query: str) -> None:

        query = self.sanistring(query)
        info = {}
        imgdata = None
        self.log.debug("duckduckgo: searching for %r (force_gif=%s)", query,
                       self.config["duckduckgo_force_gif"])

        ## DuckDuckGo has no official API. We first fetch a "vqd" token from the
        ## HTML page, then use it to query the unofficial i.js JSON endpoint.
        ## Accept-Language is part of the browser fingerprint DDG's bot blocker
        ## checks, so send it alongside the User-Agent.
        ddg_headers = {"User-Agent": _DDG_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

        ## step 1: get the vqd token from the image-search page.
        token_params = urllib.parse.urlencode({"q": query, "iax": "images", "ia": "images"})
        async with self.http.get(
            "https://duckduckgo.com/?{}".format(token_params), headers=ddg_headers
        ) as token_response:
            if token_response.status != 200:
                self.log.warning("duckduckgo: token endpoint returned %s", token_response.status)
                await evt.reply(f"Something went wrong, I got the following response from \
                            the DuckDuckGo token endpoint: {token_response.status}")
                return None
            html = await token_response.text()

        ## the token page embeds vqd="4-123..." (or vqd=4-123... unquoted); it may
        ## contain letters, so match word characters and hyphens.
        vqd_match = re.search(r'vqd=["\']?([\w-]+)["\']?', html)
        if not vqd_match:
            self.log.warning("duckduckgo: could not extract vqd token (API may have changed)")
            await evt.reply("Oops, I couldn't get a search token from DuckDuckGo \
                        (their unofficial API may have changed).")
            return None
        vqd = vqd_match.group(1)
        self.log.debug("duckduckgo: got vqd token %s", vqd)

        ## step 2: query the i.js endpoint with a minimal, browser-like param set
        ## (extra params trip DDG's bot blocker with a 403).
        ## the f param is positional: timelimit,size,color,type_image,layout,license
        ## so forcing gif-typed images puts "type:gif" in the 4th slot; otherwise
        ## an unfiltered ",,," is sent.
        force_gif = self.config["duckduckgo_force_gif"]
        params = {
            "l": "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",,,type:gif,," if force_gif else ",,,",
            "p": "1" if self.config["duckduckgo_safesearch"] else "-2",
        }
        url_params = urllib.parse.urlencode(params)

        async with self.http.get(
            "https://duckduckgo.com/i.js?{}".format(url_params),
            headers={**ddg_headers, "Referer": "https://duckduckgo.com/"},
        ) as api_response:
            if api_response.status != 200:
                self.log.warning("duckduckgo: i.js returned %s", api_response.status)
                await evt.reply(f"Something went wrong, I got the following response from \
                            the DuckDuckGo search API: {api_response.status}")
                return None
            try:
                ## DDG serves the JSON under a non-JSON content-type, so bypass the
                ## aiohttp content-type check.
                api_data = await api_response.json(content_type=None)
            except Exception as e:
                self.log.warning("duckduckgo: could not parse i.js JSON (rate-limited?): %s", e)
                await evt.reply(f"Oops, I couldn't read the DuckDuckGo search results \
                            (they may be rate-limiting me): {e}")
                return None

        ## pick a random gif from the top N relevance-ranked results
        results = api_data.get("results") or []
        self.log.debug("duckduckgo: got %d results", len(results))
        if not results:
            await evt.reply("i couldn't find anything on DuckDuckGo for that, sorry.")
            return None
        try:
            pool = min(int(self.config["duckduckgo_result_pool"]), len(results))
            pool = max(pool, 1)
            picked = random.choice(results[:pool])
        except Exception as e:
            await evt.reply(f"Oops, I had an accident trying to pick a Gif from DuckDuckGo: {e}")
            return None

        ## get the info for the image we've picked. DDG gives no byte size and no
        ## reliable mimetype, so we guess from the URL and correct after download.
        gif_link = picked["image"]
        self.log.debug("duckduckgo: picked image %s", gif_link)
        info['width'] = int(picked.get('width') or 0) or 480
        info['height'] = int(picked.get('height') or 0) or 270
        url_path = urllib.parse.urlparse(gif_link).path.lower()
        ext_map = {
            ".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp",
        }
        info['mimetype'] = next(
            (mt for ext, mt in ext_map.items() if url_path.endswith(ext)),
            "image/gif" if force_gif else "image/jpeg",
        )
        info['filename'] = f"{query}{self._mimetype_to_suffix(info['mimetype'])}"

        ## download the image, and upload it to the matrix media repository
        async with self.http.get(gif_link, headers=ddg_headers) as response:
            if response.status != 200:
                await evt.reply(f"Something went wrong, I got the following response when \
                                downloading the image from DuckDuckGo: {response.status}")
                return None
            imgdata = await response.read()
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        ## prefer the real mimetype from the download when it's an image/video
        if content_type.startswith(("image/", "video/")):
            info['mimetype'] = content_type
            info['filename'] = f"{query}{self._mimetype_to_suffix(info['mimetype'])}"
        if not re.match(r"^(image|video)/.+", info['mimetype']):
            await evt.reply("DuckDuckGo gave me something that isn't an image, sorry.")
            return None

        info['size'] = len(imgdata)

        try:
            info["original"] = await self.client.upload_media(
                imgdata, mime_type=info["mimetype"], filename=info["filename"]
            )
        except Exception as e:
            await evt.reply(f"Oops, I had an accident uploading my image to matrix: {e}")
            return None

        info["source"] = "duckduckgo"
        return info

    def _row_get(self, row, key, default=None):
        """Get value from a DB row (works with sqlite3.Row and asyncpg Record)."""
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default

    def row_to_info(self, row) -> dict:
        """Build the info dict expected by send_msg from an entries row."""
        info = {
            "original": row["original"],
            "source": self._row_get(row, "source") or "upload",
        }
        if self._row_get(row, "msgtype") in ("image", "video"):
            info["mimetype"] = self._row_get(row, "mime_type") or "image/gif"
            info["width"] = self._row_get(row, "width") or 480
            info["height"] = self._row_get(row, "height") or 270
            info["size"] = self._row_get(row, "size") or 0
            info["filename"] = self._row_get(row, "filename") or "image.gif"
        else:
            info["body"] = self._row_get(row, "body") or ""
            info["formatted_body"] = self._row_get(row, "formatted_body")
            info["sender"] = self._row_get(row, "sender") or ""
        return info

    async def store_msg(self, info: dict, tags: str) -> list:
        if not tags:
            if "filename" in info:
                tags = self.sanistring(info["filename"])
            else:
                tags = self.sanistring(info.get("body") or "")
        else:
            tags = self.sanistring(tags)

        if info.get("msgtype"):
            msgtype = info["msgtype"]
        elif info.get("body") or info.get("sender"):
            msgtype = "text"
        elif (info.get("mimetype") or "").lower().startswith("video"):
            msgtype = "video"
        else:
            msgtype = "image"

        if info.get("source"):
            source = info["source"]
        elif msgtype == "text":
            source = "custom"
        else:
            source = "upload"

        await self.database.execute(
            """INSERT INTO entries (
                original, source, msgtype, mime_type, width, height, size,
                filename, body, formatted_body, sender, tags
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            info["original"],
            source,
            msgtype,
            info.get("mimetype"),
            info.get("width"),
            info.get("height"),
            info.get("size"),
            info.get("filename"),
            info.get("body"),
            info.get("formatted_body"),
            info.get("sender"),
            tags,
        )
        return tags

    async def update_tags(self, tags: str, entry_id: int) -> None:
        tags = self.sanistring(tags)
        await self.database.execute(
            "UPDATE entries SET tags = $1 WHERE id = $2", tags, entry_id
        )

    async def get_all_entries(self, tags: str) -> list:
        tags = self.sanistring(tags)
        if not tags:
            return []
        
        # Split into words for all-words matching
        words = [w for w in tags.split() if w]
        if not words:
            return []
        
        results = []
        seen_ids = set()
        
        # Try exact phrase match first (best rank = 1)
        try:
            exact_rows = await self.database.fetch(
                """SELECT *, 1 as _rank FROM entries
                   WHERE LOWER(COALESCE(tags, '')) LIKE LOWER('%' || $1 || '%')""",
                tags,
            )
            for row in exact_rows:
                row_id = self._row_get(row, "id")
                if row_id not in seen_ids:
                    seen_ids.add(row_id)
                    results.append(row)
        except Exception:
            pass
        
        # Try all-words match (good rank = 2) - only if multiple words
        # For single word, exact phrase and all-words are the same, so skip
        # Use LIKE-only for all-words (both SQLite and PostgreSQL): order-independent,
        # no FTS stemmer quirks. Each word must appear in tags, but not adjacent.
        if len(words) > 1:
            try:
                conditions = " AND ".join([
                    f"LOWER(COALESCE(tags, '')) LIKE ${i+1}"
                    for i in range(len(words))
                ])
                params = [f"%{w}%" for w in words]
                query = f"SELECT *, 2 as _rank FROM entries WHERE {conditions}"
                all_words_rows = await self.database.fetch(query, *params)
                for row in all_words_rows:
                    row_id = self._row_get(row, "id")
                    if row_id not in seen_ids:
                        seen_ids.add(row_id)
                        results.append(row)
            except Exception:
                pass
        
        # Sort by rank (1 = exact phrase, 2 = all-words)
        results.sort(key=lambda r: self._row_get(r, "_rank", 999))
        return results

    async def get_row(self, original: str):
        return await self.database.fetchrow(
            "SELECT * FROM entries WHERE original = $1", original
        )

    async def delete_row(self, entry_id: int) -> None:
        await self.database.execute("DELETE FROM entries WHERE id = $1", entry_id)

    def parse_original(self, body: str):
        orig = re.search(r'mxorig://(.+)">', body).group(1)
        return orig


    async def _decrypt_event_if_needed(self, evt):
        """If evt is EncryptedEvent and decryption_for_save is on, decrypt and return the event to use."""
        if not isinstance(evt, EncryptedEvent):
            return evt
        if not self.config.get("decryption_for_save"):
            return None
        crypto = getattr(self.client, "crypto", None)
        if not crypto:
            return None
        decrypted = None
        if hasattr(self.client, "decrypt_event"):
            try:
                d = self.client.decrypt_event(evt)
                decrypted = await d if asyncio.iscoroutine(d) else d
            except Exception as e:
                self.log.debug("decrypt_event failed: %s", e)
        if decrypted is None:
            for name in ("decrypt_megolm_event", "decrypt"):
                fn = getattr(crypto, name, None)
                if not fn:
                    continue
                try:
                    d = fn(evt)
                    decrypted = await d if asyncio.iscoroutine(d) else d
                    break
                except Exception as e:
                    self.log.debug("crypto.%s failed: %s", name, e)
        return decrypted

    async def _download_media(self, mxc_or_url: str) -> bytes:
        """Download media from mxc URL. Requires client.download_media (mautrix with crypto)."""
        if hasattr(self.client, "download_media"):
            return await self.client.download_media(mxc_or_url)
        raise RuntimeError("client.download_media not available")

    async def save_msg(
        self, source_evt: MessageEvent, saver: UserID, tags: str = "", silent: bool = False
    ) -> Optional[str]:
        """Save or update an entry. Returns 'stored'|'updated'|'already_saved'|None (error/early exit)."""
        message_info = {}
        if not tags:
            tags = ""

        # Decrypt encrypted events when decryption_for_save is enabled
        if isinstance(source_evt, EncryptedEvent):
            dec = await self._decrypt_event_if_needed(source_evt)
            if dec is None:
                await source_evt.reply(
                    "sorry, that message is encrypted and i can't decrypt it."
                )
                return None
            source_evt = dec

        ## fetch our replied-to event contents
        if source_evt.content.msgtype in (MessageType.IMAGE, MessageType.VIDEO):
            content = source_evt.content
            enc_file = getattr(content, "file", None)
            if (
                enc_file
                and getattr(enc_file, "key", None) is not None
                and decrypt_attachment is not None
            ):
                try:
                    ciphertext = await self._download_media(enc_file.url)
                    # EncryptedFile.key is a key object; .key is the raw key (maubot-hateheif uses file.key.key)
                    key_material = getattr(enc_file.key, "key", enc_file.key)
                    hashes = getattr(enc_file, "hashes", None) or {}
                    h = hashes.get("sha256") if isinstance(hashes, dict) else getattr(hashes, "sha256", None)
                    if h is None and hashes:
                        try:
                            h = hashes["sha256"]
                        except (KeyError, TypeError):
                            pass
                    plaintext = decrypt_attachment(
                        ciphertext, key_material, h, enc_file.iv
                    )
                    info = getattr(content, "info", None) or type("_", (), {})()
                    mime = getattr(info, "mimetype", None) or "image/png"
                    filename = self._resolve_filename_for_media(content)
                    new_mxc = await self.client.upload_media(
                        plaintext, mime_type=mime, filename=filename
                    )
                    message_info["original"] = new_mxc
                    message_info["filename"] = filename
                    message_info["mimetype"] = mime
                    message_info["height"] = getattr(info, "height", None)
                    message_info["width"] = getattr(info, "width", None)
                    message_info["size"] = getattr(info, "size", None)
                except Exception as e:
                    self.log.warning("Failed to decrypt media: %s", e)
                    await source_evt.reply("sorry, i couldn't decrypt the file.")
                    return None
            else:
                message_info["original"] = content.url
                message_info["filename"] = self._resolve_filename_for_media(content)
                message_info["mimetype"] = content.info.mimetype
                message_info["height"] = content.info.height
                message_info["width"] = content.info.width
                message_info["size"] = content.info.size

        elif source_evt.content.msgtype == MessageType.TEXT:
            if self.config["allow_non_files"] == False:
                await source_evt.reply("i'm not allowed to save anything that isn't a file upload")
                return None
            else:
                try:
                    message_info["formatted_body"] = source_evt.content.formatted_body
                except:
                    pass
                message_info["body"] = source_evt.content.body
                message_info["sender"] = source_evt.sender
                message_info["original"] = source_evt.event_id

        elif source_evt.content.msgtype == MessageType.NOTICE:
            original = source_evt.content.get("org.jobmachine.gifme.mxorig")
            if original is None:
                try:
                    original = self.parse_original(
                        source_evt.content.formatted_body or ""
                    )
                except (AttributeError, IndexError, TypeError):
                    original = None
            if original is None:
                await source_evt.reply(
                    "i'm not going to save that, it looks like it's from a bot."
                )
                return None
            message_info["original"] = original
            message_info["msgtype"] = "text"
            message_info["source"] = "custom"

        else:
            await source_evt.reply(f"i don't know what {source_evt.content.msgtype} is, but i can't save it.")
            return None

        if not message_info["original"]:
            await source_evt.reply(
                "sorry, that image appears to be encrypted, and i can't save it."
            )
            return None

        row = await self.get_row(message_info["original"])

        ## if the entry exists, just append new tags
        if row:
            entry_id = row["id"]
            tags_list = (
                (tags or "").split()
                if isinstance(tags, str)
                else (list(tags) if tags else [])
            )
            oldtags = (self._row_get(row, "tags") or "").split()
            difftags = [t for t in tags_list if t not in oldtags]
            newtags = oldtags + difftags

            if len(difftags) != 0:
                if not silent:
                    updatemsg = await source_evt.reply(
                        f"matching entry found, adding the following new tags: {difftags}"
                    )
                    updateevt = await self.client.get_event(
                        source_evt.room_id, updatemsg
                    )
                try:
                    await self.update_tags(" ".join(newtags), entry_id)
                    if not silent:
                        await updateevt.react("✅")
                    return "updated"
                except Exception:
                    if not silent:
                        await updateevt.react("❌")
                    return None
            else:
                if not silent:
                    await source_evt.reply(
                        f"{saver} reading comprehension grade: 🇫"
                    )
                return "already_saved"
        else:
            saved_tags = await self.store_msg(message_info, tags)
            if not silent:
                await source_evt.reply(
                    f"saved to database with tags: {str(saved_tags)}"
                )
            return "stored"




    def _build_content(self, info: dict):
        """Build message content from info dict."""
        if info["original"].startswith("mxc"):
            try:
                msgtype = re.match(r"^(image|video)\/.+", info["mimetype"]).group(1)
                content = MediaMessageEventContent(
                    msgtype=f"m.{msgtype}",
                    url=info["original"],
                    body=info["filename"],
                    info=ImageInfo(
                        mimetype=info["mimetype"],
                        width=info["width"],
                        height=info["height"],
                        size=info["size"],
                    ),
                )
                content["filename"] = info["filename"]
                content["org.jobmachine.gifme.mxorig"] = info["original"]
                if info.get("source") in ("giphy", "klipy", "duckduckgo"):
                    content["org.jobmachine.gifme.source"] = info["source"]
                if info.get("query"):
                    content["org.jobmachine.gifme.query"] = info["query"]
                if info.get("original_sender"):
                    content["org.jobmachine.gifme.original_sender"] = info["original_sender"]
                return content
            except Exception:
                self.log.error("mimetype not supported: %s", info.get("mimetype"))
                raise
        else:
            msgbody = (
                info["formatted_body"]
                if info.get("formatted_body")
                else info.get("body", "")
            )
            formatted = (
                f"<blockquote><p>{msgbody}</p>"
                f"<p>--<a href=\"https://matrix.to/#/{info.get('sender', '')}\">"
                f"{info.get('sender', '')}</a></p></blockquote>"
            )
            content = TextMessageEventContent(
                msgtype=MessageType.NOTICE,
                body=info.get("body") or "(quoted)",
                format=Format.HTML,
                formatted_body=formatted,
            )
            content["org.jobmachine.gifme.mxorig"] = info["original"]
            return content

    def _source_attribution(self, source: str) -> str:
        """Human-readable attribution reaction for a fallback backend."""
        return {
            "giphy": "Powered by GIPHY",
            "klipy": "Powered by KLIPY",
            "duckduckgo": "Powered by DuckDuckGo",
        }.get(source, "Powered by the internet")

    async def send_msg(self, evt: MessageEvent, info: dict) -> EventID:
        content = self._build_content(info)
        msg_id = await evt.respond(content=content, allow_html=True)
        return msg_id

    async def send_msg_to_room(self, room_id: RoomID, info: dict) -> EventID:
        """Send a message directly to a room without replying."""
        content = self._build_content(info)
        msg_id = await self.client.send_message(room_id, content)
        return msg_id

    @command.new(name=get_command_name, aliases=is_alias, help="save and tag, or return, message contents", require_subcommand=False,
                 arg_fallthrough=False)

    @command.argument("tags", pass_raw=True, required=True)
    async def gifme(self, evt: MessageEvent, tags: str) -> None:
        tags = self.sanistring(tags)

        if not tags:
            await evt.respond(
                f"<b>Usage:</b>"
                f"<p><code>!{self.config['command_aliases'][0]} &lt;phrase&gt;</code>: return a gif matching &lt;phrase&gt;<br />"
                f"<code>!{self.config['command_aliases'][0]} giphy &lt;phrase&gt;</code>: return a gif from giphy search matching &lt;phrase&gt;<br />"
                f"<code>!{self.config['command_aliases'][0]} ddg &lt;phrase&gt;</code>: return a gif from duckduckgo search matching &lt;phrase&gt;<br />"
                f"<code>!{self.config['command_aliases'][0]} save &lt;phrase&gt;</code>: use in reply to a message to save "
                f"the message contents with &lt;phrase&gt; as tags, or update the existing tags<br />"
                f"<code>!{self.config['command_aliases'][0]} tags</code>: use in reply to a message i sent "
                f"to see the tags associated with that message in the database</p>",
                allow_html=True,
            )
            return None

        msg_info = {}
        fallback_status = 0
        await evt.mark_read()
        if self.config["fallback_threshold"] < 1:
            if self.config["allow_fallback"].lower() == "giphy":
                msg_info = await self.get_giphy(evt, tags)
            elif self.config["allow_fallback"].lower() == "klipy":
                msg_info = await self.get_klipy(evt, tags)
            elif self.config["allow_fallback"].lower() == "duckduckgo":
                msg_info = await self.get_duckduckgo(evt, tags)
            ## skip setting fallback_status so we don't send the fallback message every time, that would get old.
        else:
            entries = await self.get_all_entries(tags)

            if entries:
                if len(entries) < self.config["fallback_threshold"]:
                    if self.config["allow_fallback"].lower() == "giphy":
                        msg_info = await self.get_giphy(evt, tags)
                        fallback_status = 1
                    elif self.config["allow_fallback"].lower() == "klipy":
                        msg_info = await self.get_klipy(evt, tags)
                        fallback_status = 1
                    elif self.config["allow_fallback"].lower() == "duckduckgo":
                        msg_info = await self.get_duckduckgo(evt, tags)
                        fallback_status = 1
                else:
                    # Get the best rank (first entry has the best rank since results are sorted)
                    best_rank = self._row_get(entries[0], "_rank", 999) if entries else 999
                    # Filter to only entries with the best rank (rotate among equally top-ranked matches)
                    best_tier = [e for e in entries if self._row_get(e, "_rank", 999) == best_rank]
                    chosen = random.choice(best_tier)
                    msg_info = self.row_to_info(chosen)
                    # Store the query and original sender for RETRY functionality
                    msg_info["query"] = tags
                    msg_info["original_sender"] = str(evt.sender)
            else:
                if self.config["allow_fallback"].lower() == "giphy":
                    msg_info = await self.get_giphy(evt, tags)
                    fallback_status = 1
                elif self.config["allow_fallback"].lower() == "klipy":
                    msg_info = await self.get_klipy(evt, tags)
                    fallback_status = 1
                elif self.config["allow_fallback"].lower() == "duckduckgo":
                    msg_info = await self.get_duckduckgo(evt, tags)
                    fallback_status = 1
                else:
                    await evt.reply("i couldn't come up with anything, sorry.")
                    return None

        if msg_info is None:
            return
        # Store the query and original sender for RETRY functionality
        msg_info["query"] = tags
        msg_info["original_sender"] = str(evt.sender)
        my_msg = await self.send_msg(evt, msg_info)

        if msg_info.get("source") in ("giphy", "klipy", "duckduckgo"):
            await self.client.react(
                evt.room_id,
                my_msg,
                self._source_attribution(msg_info.get("source")),
            )
            # only ask to save if we actually are configured to pull from archives
            if self.config["fallback_threshold"] > 0:
                await self.client.react(evt.room_id, my_msg, "💾 SAVE")
        elif self.config["fallback_threshold"] > 0:
            await self.client.react(evt.room_id, my_msg, "🗃️ from my archives")
        # Add RETRY and TRASH reactions to all images
        await self.client.react(evt.room_id, my_msg, "♻️ RETRY")
        await self.client.react(evt.room_id, my_msg, "🗑️ TRASH")


    @gifme.subcommand("giphy", help="use giphy to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def giphy(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        await evt.mark_read()
        img_info = await self.get_giphy(evt, tags)
        if not img_info:
            return
        my_msg = await self.send_msg(evt, img_info)
        await self.client.react(evt.room_id, my_msg, "Powered by GIPHY")
        # only ask to save if we actually are configured to pull from archives
        if self.config["fallback_threshold"] > 0:
            await self.client.react(evt.room_id, my_msg, "💾 SAVE")


    @gifme.subcommand("klipy", help="use klipy to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def klipy(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        await evt.mark_read()
        img_info = await self.get_klipy(evt, tags)
        if not img_info:
            return
        # Store the query and original sender for RETRY functionality
        img_info["query"] = tags
        img_info["original_sender"] = str(evt.sender)
        my_msg = await self.send_msg(evt, img_info)
        await self.client.react(evt.room_id, my_msg, "Powered by KLIPY")
        # only ask to save if we actually are configured to pull from archives
        if self.config["fallback_threshold"] > 0:
            await self.client.react(evt.room_id, my_msg, "💾 SAVE")
        # Add RETRY and TRASH reactions to all images
        await self.client.react(evt.room_id, my_msg, "♻️ RETRY")
        await self.client.react(evt.room_id, my_msg, "🗑️ TRASH")


    async def _duckduckgo_cmd(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        await evt.mark_read()
        img_info = await self.get_duckduckgo(evt, tags)
        if not img_info:
            return
        # Store the query and original sender for RETRY functionality
        img_info["query"] = tags
        img_info["original_sender"] = str(evt.sender)
        my_msg = await self.send_msg(evt, img_info)
        await self.client.react(evt.room_id, my_msg, "Powered by DuckDuckGo")
        # only ask to save if we actually are configured to pull from archives
        if self.config["fallback_threshold"] > 0:
            await self.client.react(evt.room_id, my_msg, "💾 SAVE")
        # Add RETRY and TRASH reactions to all images
        await self.client.react(evt.room_id, my_msg, "♻️ RETRY")
        await self.client.react(evt.room_id, my_msg, "🗑️ TRASH")

    @gifme.subcommand("duckduckgo", help="use duckduckgo to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def duckduckgo(self, evt: MessageEvent, tags: str) -> None:
        await self._duckduckgo_cmd(evt, tags)

    @gifme.subcommand("ddg", help="alias for the duckduckgo subcommand")

    @command.argument("tags", pass_raw=True, required=True)
    async def ddg(self, evt: MessageEvent, tags: str) -> None:
        await self._duckduckgo_cmd(evt, tags)


    @command.passive(
        regex=r"^💾$",
        field=lambda evt: evt.content.relates_to.key,
        event_type=EventType.REACTION,
        msgtypes=None,
    )
    async def save_react_floppy(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        """React with 💾 only to save any message (uses filename-derived tags when no tags)."""
        source_evt = await self.client.get_event(
            evt.room_id, evt.content.relates_to.event_id
        )
        if self.config["restrict_users"] and evt.sender not in self.config.get(
            "allowed_users", []
        ):
            await source_evt.reply(
                f"{evt.sender} reacted with the save emoji, but is not allowed "
                "to save things to my database."
            )
            return
        await self.save_msg(source_evt, saver=evt.sender, tags="")

    @command.passive(
        regex=r"^💾 SAVE$",
        field=lambda evt: evt.content.relates_to.key,
        event_type=EventType.REACTION,
        msgtypes=None,
    )
    async def save_react(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        target_id = evt.content.relates_to.event_id
        key_saved = (str(evt.room_id), str(target_id))
        if key_saved in self._saved_reaction_event_ids:
            return

        source_evt = await self.client.get_event(evt.room_id, target_id)
        if source_evt.sender != self.client.mxid:
            return
        try:
            src = source_evt.content.get("org.jobmachine.gifme.source")
        except (AttributeError, TypeError):
            src = None
        if src not in ("giphy", "klipy", "duckduckgo"):
            return

        if self.config["restrict_users"] and evt.sender not in self.config.get(
            "allowed_users", []
        ):
            await source_evt.reply(
                f"{evt.sender} reacted with the save emoji, but is not allowed "
                "to save things to my database."
            )
            return

        status = await self.save_msg(
            source_evt, saver=evt.sender, tags="", silent=True
        )
        if status in ("stored", "updated"):
            self._saved_reaction_event_ids.add(key_saved)
            await self.client.react(evt.room_id, target_id, "✅ SAVED!")

    @command.passive(
        regex=r"^♻️ RETRY$",
        field=lambda evt: evt.content.relates_to.key,
        event_type=EventType.REACTION,
        msgtypes=None,
    )
    async def retry_react(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        """React with ♻️ RETRY to redact the message and retry the search with the same query."""
        target_id = evt.content.relates_to.event_id
        source_evt = await self.client.get_event(evt.room_id, target_id)
        
        # Only process reactions to messages sent by the bot
        if source_evt.sender != self.client.mxid:
            return
        
        # Get the query and original sender from the message content
        query = source_evt.content.get("org.jobmachine.gifme.query")
        if not query:
            # If no query stored, we can't retry
            return
        
        # Only allow RETRY from the person who sent the original query
        original_sender = source_evt.content.get("org.jobmachine.gifme.original_sender")
        if original_sender and str(evt.sender) != original_sender:
            # Not the original sender, ignore the reaction
            return
        
        # Redact the original message
        try:
            await self.client.redact(evt.room_id, target_id)
        except Exception as e:
            self.log.warning("Failed to redact message: %s", e)
            return
        
        # Retry the search with the same query
        # We need to determine the source and retry accordingly
        source = source_evt.content.get("org.jobmachine.gifme.source")
        
        # Create a minimal event-like object for get_giphy/get_klipy error handling
        # They only use evt.reply() for errors, so we'll handle that separately
        class FakeEvent:
            def __init__(self, room_id, plugin):
                self.room_id = room_id
                self.plugin = plugin
            
            async def reply(self, text):
                # For errors during retry, just log them
                self.plugin.log.warning(f"Error during retry: {text}")
        
        fake_evt = FakeEvent(evt.room_id, self)
        
        # Retry using the same logic as the original search
        msg_info = {}
        if source == "giphy":
            msg_info = await self.get_giphy(fake_evt, query)
        elif source == "klipy":
            msg_info = await self.get_klipy(fake_evt, query)
        elif source == "duckduckgo":
            msg_info = await self.get_duckduckgo(fake_evt, query)
        else:
            # Image came from archives - retry with same logic as gifme command
            if self.config["fallback_threshold"] < 1:
                # If fallback_threshold < 1, we shouldn't have archives, but handle it anyway
                if self.config["allow_fallback"].lower() == "giphy":
                    msg_info = await self.get_giphy(fake_evt, query)
                elif self.config["allow_fallback"].lower() == "klipy":
                    msg_info = await self.get_klipy(fake_evt, query)
                elif self.config["allow_fallback"].lower() == "duckduckgo":
                    msg_info = await self.get_duckduckgo(fake_evt, query)
            else:
                entries = await self.get_all_entries(query)

                if entries:
                    if len(entries) < self.config["fallback_threshold"]:
                        if self.config["allow_fallback"].lower() == "giphy":
                            msg_info = await self.get_giphy(fake_evt, query)
                        elif self.config["allow_fallback"].lower() == "klipy":
                            msg_info = await self.get_klipy(fake_evt, query)
                        elif self.config["allow_fallback"].lower() == "duckduckgo":
                            msg_info = await self.get_duckduckgo(fake_evt, query)
                    else:
                        # Get the best rank (first entry has the best rank since results are sorted)
                        best_rank = self._row_get(entries[0], "_rank", 999) if entries else 999
                        # Filter to only entries with the best rank (rotate among equally top-ranked matches)
                        best_tier = [e for e in entries if self._row_get(e, "_rank", 999) == best_rank]
                        chosen = random.choice(best_tier)
                        msg_info = self.row_to_info(chosen)
                        msg_info["query"] = query
                else:
                    if self.config["allow_fallback"].lower() == "giphy":
                        msg_info = await self.get_giphy(fake_evt, query)
                    elif self.config["allow_fallback"].lower() == "klipy":
                        msg_info = await self.get_klipy(fake_evt, query)
                    elif self.config["allow_fallback"].lower() == "duckduckgo":
                        msg_info = await self.get_duckduckgo(fake_evt, query)

        if msg_info is None:
            return
        
        # Store the query and original sender for RETRY functionality
        # Preserve the original sender from the message being retried
        if "query" not in msg_info:
            msg_info["query"] = query
        if "original_sender" not in msg_info:
            # Use the original sender from the message being retried, not the person who reacted
            msg_info["original_sender"] = original_sender or str(evt.sender)
        
        # Send the new message directly to the room (not as a reply)
        my_msg = await self.send_msg_to_room(evt.room_id, msg_info)
        
        # Add reactions as appropriate
        if msg_info.get("source") in ("giphy", "klipy", "duckduckgo"):
            await self.client.react(
                evt.room_id,
                my_msg,
                self._source_attribution(msg_info.get("source")),
            )
            if self.config["fallback_threshold"] > 0:
                await self.client.react(evt.room_id, my_msg, "💾 SAVE")
        elif self.config["fallback_threshold"] > 0:
            await self.client.react(evt.room_id, my_msg, "🗃️ from my archives")
        
        # Add RETRY and TRASH reactions to all images
        await self.client.react(evt.room_id, my_msg, "♻️ RETRY")
        await self.client.react(evt.room_id, my_msg, "🗑️ TRASH")

    @command.passive(
        regex=r"^🗑️ TRASH$",
        field=lambda evt: evt.content.relates_to.key,
        event_type=EventType.REACTION,
        msgtypes=None,
    )
    async def trash_react(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        """React with 🗑️ TRASH to silently redact the bot's message."""
        target_id = evt.content.relates_to.event_id
        source_evt = await self.client.get_event(evt.room_id, target_id)

        # Only process reactions to messages sent by the bot
        if source_evt.sender != self.client.mxid:
            return

        # Only allow TRASH from the person who sent the original query
        original_sender = source_evt.content.get("org.jobmachine.gifme.original_sender")
        if original_sender and str(evt.sender) != original_sender:
            return

        try:
            await self.client.redact(evt.room_id, target_id)
        except Exception as e:
            self.log.warning("Failed to redact message: %s", e)

    @gifme.subcommand("save", help="save and tag a message to the database")
    @command.argument("tags", pass_raw=True, required=True)
    async def save(self, evt: MessageEvent, tags: str) -> None:
        await evt.mark_read()

        if self.config["restrict_users"]:
            if evt.sender in self.config["allowed_users"]:
                pass
            else:
                await evt.reply("you're not allowed to do that.")
                return None

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to save")
            return None

        tags = self.sanistring(tags)

        message_info = {}

        source_evt = await self.client.get_event(evt.room_id, evt.content.get_reply_to())
        saver = evt.sender


        await self.save_msg(source_evt, saver=saver, tags=tags)

    @gifme.subcommand("tags", help="return the tags associated with a specific response from the database")
    async def return_tags(self, evt: MessageEvent) -> None:
        await evt.mark_read()

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to look up tags for")
            return None

        original = None
        reply_event = await self.client.get_event(evt.room_id, evt.content.get_reply_to())

        if reply_event.content.msgtype in (MessageType.IMAGE, MessageType.VIDEO):
            original = reply_event.content.url
        else:
            original = reply_event.content.get("org.jobmachine.gifme.mxorig")
            if original is None:
                try:
                    original = self.parse_original(
                        reply_event.content.formatted_body or ""
                    )
                except (AttributeError, IndexError, TypeError):
                    original = None
            if original is None:
                await evt.reply(
                    "i couldn't find the original in the message content, sorry."
                )
                return None

        entry = await self.get_row(original)
        if entry:
            await evt.reply(f"this saved entry has the following tags: {entry['tags']}")
        else:
            await evt.reply(f"i don't see this message in my database.")

    @gifme.subcommand("delete", help="deletes a saved entry from the database")
    async def delete_entry(self, evt: MessageEvent) -> None:
        await evt.mark_read()

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to delete")
            return None

        if self.config["restrict_users"]:
            if evt.sender in self.config["allowed_users"]:
                pass
            else:
                await evt.reply("you're not allowed to do that.")
                return None

        original = None
        reply_event = await self.client.get_event(evt.room_id, evt.content.get_reply_to())

        if reply_event.content.msgtype in (MessageType.IMAGE, MessageType.VIDEO):
            original = reply_event.content.url
        else:
            original = reply_event.content.get("org.jobmachine.gifme.mxorig")
            if original is None:
                try:
                    original = self.parse_original(
                        reply_event.content.formatted_body or ""
                    )
                except (AttributeError, IndexError, TypeError):
                    original = None
            if original is None:
                await evt.reply(
                    "i couldn't find the original in the message content, sorry."
                )
                return None

        entry = await self.get_row(original)
        if entry:
            try:
                await self.delete_row(entry["id"])
                await evt.reply("i have deleted the entry from my database 🚮")
            except Exception as e:
                await evt.reply(f"oh dear, something went wrong when deleting the entry: {e}")
                return None
        else:
            await evt.reply(f"i don't see this message in my database.")



    @classmethod
    def get_db_upgrade_table(cls) -> None:
        return upgrade_table

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
