# gifme - a maubot plugin to overcome the fact that giphy kinda sucks

from typing import Awaitable, Type, Optional, Tuple
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

# database table related things
from .db import upgrade_table



class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("command_aliases")
        helper.copy("allow_fallback")
        helper.copy("fallback_threshold")
        helper.copy("giphy_api_key")
        helper.copy("klipy_api_key")
        helper.copy("allow_non_files")
        helper.copy("say_already_saved")
        helper.copy("be_subtle")
        helper.copy("restrict_users")
        helper.copy("allowed_users")


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
        try:
            rows = await self.database.fetch(
                """SELECT * FROM entries
                   WHERE to_tsvector('english', COALESCE(tags, '')) @@ plainto_tsquery('english', $1)""",
                tags,
            )
        except Exception:
            rows = await self.database.fetch(
                "SELECT * FROM entries WHERE COALESCE(tags, '') LIKE '%' || $1 || '%'",
                tags,
            )
        return rows

    async def get_row(self, original: str):
        return await self.database.fetchrow(
            "SELECT * FROM entries WHERE original = $1", original
        )

    async def delete_row(self, entry_id: int) -> None:
        await self.database.execute("DELETE FROM entries WHERE id = $1", entry_id)

    def parse_original(self, body: str):
        orig = re.search(r'mxorig://(.+)">', body).group(1)
        return orig


    async def save_msg(
        self, source_evt: MessageEvent, saver: UserID, tags: str = "", silent: bool = False
    ) -> Optional[str]:
        """Save or update an entry. Returns 'stored'|'updated'|'already_saved'|None (error/early exit)."""
        message_info = {}
        if not tags:
            tags = ""

        ## fetch our replied-to event contents
        if source_evt.content.msgtype in (MessageType.IMAGE, MessageType.VIDEO):
            message_info["original"] = source_evt.content.url
            message_info["filename"] = source_evt.content.body
            message_info["mimetype"] = source_evt.content.info.mimetype
            message_info["height"] = source_evt.content.info.height
            message_info["width"] = source_evt.content.info.width
            message_info["size"] = source_evt.content.info.size

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
                    if self.config["say_already_saved"]:
                        await source_evt.reply(
                            f"{saver} reading comprehension grade: 🇫"
                        )
                    else:
                        await source_evt.reply(
                            "It looks like this is already saved with these tags."
                        )
                return "already_saved"
        else:
            saved_tags = await self.store_msg(message_info, tags)
            if not silent:
                await source_evt.reply(
                    f"saved to database with tags: {str(saved_tags)}"
                )
            return "stored"




    async def send_msg(self, evt: MessageEvent, info: dict) -> EventID:

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
                content["org.jobmachine.gifme.mxorig"] = info["original"]
                if info.get("source") in ("giphy", "klipy"):
                    content["org.jobmachine.gifme.source"] = info["source"]
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

        msg_id = await evt.respond(content=content, allow_html=True)
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
                else:
                    chosen = random.choice(entries)
                    msg_info = self.row_to_info(chosen)
            else:
                if self.config["allow_fallback"].lower() == "giphy":
                    msg_info = await self.get_giphy(evt, tags)
                    fallback_status = 1
                elif self.config["allow_fallback"].lower() == "klipy":
                    msg_info = await self.get_klipy(evt, tags)
                    fallback_status = 1
                else:
                    await evt.reply("i couldn't come up with anything, sorry.")
                    return None

        if msg_info is None:
            return
        my_msg = await self.send_msg(evt, msg_info)

        if msg_info.get("source") in ("giphy", "klipy"):
            await self.client.react(
                evt.room_id,
                my_msg,
                "Powered by GIPHY" if msg_info.get("source") == "giphy" else "Powered by KLIPY",
            )
            await self.client.react(evt.room_id, my_msg, "💾 SAVE?")
        elif self.config["say_already_saved"] and self.config["fallback_threshold"] > 0:
            if self.config["be_subtle"]:
                await self.client.react(evt.room_id, my_msg, "🗃️")
            else:
                await evt.respond(
                    "<em>i found this in my personal archives, you don't need to save it again.</em>",
                    allow_html=True,
                )


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
        await self.client.react(evt.room_id, my_msg, "💾 SAVE?")


    @gifme.subcommand("klipy", help="use klipy to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def klipy(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        await evt.mark_read()
        img_info = await self.get_klipy(evt, tags)
        if not img_info:
            return
        my_msg = await self.send_msg(evt, img_info)
        await self.client.react(evt.room_id, my_msg, "Powered by KLIPY")
        await self.client.react(evt.room_id, my_msg, "💾 SAVE?")


    @command.passive(
        regex=r"^💾 SAVE\?$",
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
        if src not in ("giphy", "klipy"):
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
