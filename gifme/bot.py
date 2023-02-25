# gifme - a maubot plugin to overcome the fact that giphy kinda sucks

from typing import Awaitable, Type, Optional, Tuple
import json
import re
import time
import random
import urllib.parse

from mautrix.client import Client
from mautrix.types import (Event, MessageType, EventID, UserID, FileInfo, EventType, RoomID,
                            MediaMessageEventContent, TextMessageEventContent, ContentURI,
                            ReactionEvent, RedactionEvent, ImageInfo, RelationType)
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
        helper.copy("allow_non_files")
        helper.copy("restrict_users")
        helper.copy("allowed_users")


class GifMe(Plugin):

    async def start(self) -> None:
        self.config.load_and_update()

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
            info['original'] = await self.client.upload_media(imgdata, mime_type=info['mimetype'], filename=info['filename'])
        except Exception as e:
            await evt.reply(f"Oops, I had an accident uploading my image to matrix: {e}")

        ## return an object with the necessary information to send a message
        return info

    async def store_msg(self, info: dict, tags: str) -> list:
        if not tags:
            ## if no tags supplied, use the filename to generate some tags
            ## sanitize the filename again because we don't know where it came from
            if 'filename' in info:
                tags = self.sanistring(info['filename'])
            else:
                tags = self.sanistring(info['body'])
        else:
            tags = self.sanistring(tags)


        dbq = """
                INSERT INTO responses (msg_info, tags) VALUES ($1, $2)
              """

        json_info = json.dumps(info)
        await self.database.execute(dbq, json_info, tags)
        return tags

    async def update_tags(self, tags: str, rowid: int) -> None:
        tags = self.sanistring(tags)
        dbq = """
                UPDATE responses SET tags = $1 WHERE rowid = $2
              """

        await self.database.execute(dbq, tags, rowid)

    async def get_all_entries(self, tags: str) -> None:
        tags = self.sanistring(tags)
        dbq = """
                SELECT * FROM responses WHERE tags MATCH $1
              """

        rows = await self.database.fetch(dbq, tags)
        return rows

    async def get_row(self, original: str) -> None:
        dbq = """
                SELECT docid, msg_info, tags FROM responses WHERE msg_info MATCH $1
              """

        row = await self.database.fetchrow(dbq, original)
        return row
    
    async def delete_row(self, row: int) -> None:
        dbq = """
                DELETE FROM responses WHERE docid = $1
              """

        row = await self.database.execute(dbq, row)

    def parse_original(self, body: str):
        orig = re.search(r'mxorig://(.+)">', body).group(1)
        return orig


    async def save_msg(self, source_evt: MessageEvent, tags="") -> None:

        message_info = {}
        if not tags:
            tags = ""

        ## fetch our replied-to event contents
        if source_evt.content.msgtype == MessageType.IMAGE or source_evt.content.msgtype == MessageType.VIDEO:
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
                message_info["body"] = source_evt.content.body
                message_info["sender"] = source_evt.sender
                message_info["original"] = source_evt.event_id

        elif source_evt.content.msgtype == MessageType.NOTICE:
            try:
                body = source_evt.content.formatted_body
                message_info["original"] = self.parse_original(body)
            except Exception as e:
                await source_evt.reply("i'm not going to save that, it looks like it's from a bot.")
                return None

        else:
            await source_evt.reply(f"i don't know what {source_evt.content.msgtype} is, but i can't save it.")
            return None

        if not message_info["original"]:
            await source_evt.reply(f"sorry, that image appears to be encrypted, and i can't save it.")
            return None

        row = await self.get_row(message_info["original"])

        ## if the entry exists, just append new tags
        if row:
            rowid = row['docid']
            try:
                tags = tags.split()
            except:
                pass
            oldtags = row["tags"].split()
            difftags = []
            newtags = oldtags

            for t in tags:
                if t in oldtags:
                    pass
                else:
                    difftags.append(t)
                    
            if len(difftags) != 0:
              updatemsg = await source_evt.reply(f"matching entry found, adding the following new tags: {difftags}")
              updateevt = await self.client.get_event(source_evt.room_id, updatemsg)
            else:
              await source_evt.reply(f"It looks like this image is already saved with these tags."
            newtags.extend(difftags)
            try:
                await self.update_tags(' '.join(newtags), rowid)
                await updateevt.react(f"✅")
            except:
                await updateevt.react(f"❌")
        else:
            saved_tags = await self.store_msg(message_info, tags)
            await source_evt.reply(f"saved to database with tags: {str(saved_tags)}")




    async def send_msg(self, evt: MessageEvent, info: dict) -> None:

        if info['original'].startswith("mxc"):
            try:
                msgtype = re.match(r'^(image|video)\/.+', info['mimetype']).group(1)
                content = MediaMessageEventContent(
                            msgtype=f"m.{msgtype}",
                            url=info['original'],
                            body=info['filename'],
                            info=ImageInfo(
                                mimetype=info['mimetype'],
                                width=info['width'],
                                height=info['height'],
                                size=info['size']
                                )
                        )
            except:
                self.log.error(f"mimetype not supported: {info['mimetype']}")
        else:
            content = f"<blockquote><p>{info['body']}</p>\
                        <p>-- <a href=\"https://matrix.to/#/{info['sender']}\">{info['sender']}</a></p>\
                        <a href=\"mxorig://{info['original']}\"></a>\
                        </blockquote>"

        await evt.respond(content=content, allow_html=True) 

    @command.new(name=get_command_name, aliases=is_alias, help="save and tag, or return, message contents", require_subcommand=False,
                 arg_fallthrough=False)

    @command.argument("tags", pass_raw=True, required=True)
    async def gifme(self, evt: MessageEvent, tags: str) -> None:
        tags = self.sanistring(tags)

        if not tags:
            await evt.respond(f"<b>Usage:</b>\
                        <p><code>!{self.config['command_aliases'][0]} \<phrase\></code>: return a gif matching \<phrase\><br />\
                        <code>!{self.config['command_aliases'][0]} giphy \<phrase\></code>: return a gif from giphy search matching\
                        \<phrase\><br />\
                        <code>!{self.config['command_aliases'][0]} save \<phrase\></code>: use in reply to a message to save\
                        the message contents with \<phrase\> as tags, or update the existing tags<br />\
                        <code>!{self.config['command_aliases'][0]} tags</code>: use in reply to a message i sent\
                        to see the tags associated with that message in the database</p>",
                        allow_html=True)
            return None

        msg_info = {}
        fallback_status = 0
        await evt.mark_read()
        if self.config["fallback_threshold"] < 1:
            msg_info = await self.get_giphy(evt, tags)
            ## skip setting fallback_status so we don't send the fallback message every time, that would get old.
        else:
            entries = await self.get_all_entries(tags)

            if entries:
                if len(entries) < self.config["fallback_threshold"]:
                    if self.config["allow_fallback"]:
                        msg_info = await self.get_giphy(evt, tags)
                        fallback_status = 1
                else:
                    chosen = random.choice(entries)
                    msg_info = json.loads(chosen['msg_info'])
            else:
                if self.config["allow_fallback"]:
                    msg_info = await self.get_giphy(evt, tags)
                    fallback_status = 1
                else:
                    await evt.reply("i couldn't come up with anything, sorry.")
                    return None

        await self.send_msg(evt, msg_info)
        if fallback_status > 0:
            await evt.respond("psst... i found this on giphy. be sure to save\
                    it if it's any good.")

    @gifme.subcommand("giphy", help="use giphy to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def giphy(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        img_info = {}
        await evt.mark_read()
        
        img_info = await self.get_giphy(evt, tags)

        await self.send_msg(evt, img_info)




    @command.passive(regex='💾', field=lambda evt: evt.content.relates_to.key,
                     event_type=EventType.REACTION, msgtypes=None)
    async def save_react(self, evt: ReactionEvent, key: Tuple[str]) -> None:
        source_evt = await self.client.get_event(evt.room_id, evt.content.relates_to.event_id)

        if self.config["restrict_users"]:
            if evt.sender in self.config["allowed_users"]:
                pass
            else:
                await source_evt.reply(f"{evt.sender} reacted with the save\
                            emoji, but is not allowed to save things to my database.")
                return None

        await self.save_msg(source_evt)




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


        await self.save_msg(source_evt, tags)

    @gifme.subcommand("tags", help="return the tags associated with a specific response from the database")
    async def return_tags(self, evt: MessageEvent) -> None:
        await evt.mark_read()

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to look up tags for")
            return None

        original = None
        reply_event = await self.client.get_event(evt.room_id, evt.content.get_reply_to())

        if reply_event.content.msgtype == MessageType.IMAGE or reply_event.content.msgtype == MessageType.VIDEO:
            original = reply_event.content.url
        else:
            try:
                body = reply_event.content.formatted_body
                original = self.parse_original(body)
            except Exception as e:
                await evt.reply(f"i couldn't find the original in the message content, sorry. {e}")
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

        if reply_event.content.msgtype == MessageType.IMAGE or reply_event.content.msgtype == MessageType.VIDEO:
            original = reply_event.content.url
        else:
            try:
                body = reply_event.content.formatted_body
                original = self.parse_original(body)
            except Exception as e:
                await evt.reply(f"i couldn't find the original in the message content, sorry. {e}")
                return None

        entry = await self.get_row(original)
        if entry:
            try:
                await self.delete_row(entry['docid'])
                await evt.reply(f"i have deleted the entry from my database 🚮")
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
