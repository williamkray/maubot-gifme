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
                            ReactionEvent, RedactionEvent, ImageInfo)
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

# database table related things
from .db import upgrade_table



class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("command_prefix")
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
        return self.config["command_prefix"]

    def sanistring(self, query: str) -> str:
        sani = re.sub(r'[^a-zA-Z0-9\s]', '', query).lower()
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
                await evt.respond(f"Something went wrong: {api_response.status}")
                return None

            api_data = await api_response.json()

        ## pick a random gif from the list of results returned
        picked_gif = random.choice(api_data['data'])

        ## get the info for the gif we've picked
        gif_link = picked_gif['images']['original']['url']
        info['width'] = int(picked_gif['images']['original']['width']) or 480
        info['height'] = int(picked_gif['images']['original']['height']) or 270
        info['size'] = int(picked_gif['images']['original']['size'])
        info['mimetype'] = 'image/gif'
        info['filename'] = "giphy.gif"

        ## download the image, and upload it to the matrix media repository
        async with self.http.get(gif_link) as response:
            if response.status != 200:
                await evt.respond(f"Something went wrong: {response.status}")
                return None

            imgdata = await response.read()

        info['original'] = await self.client.upload_media(imgdata, mime_type=info['mimetype'], filename=info['filename'])

        ## return an object with the necessary information to send a message
        return info

    async def save_msg(self, info: dict, tags: str) -> None:
        tags = self.sanistring(tags)
        dbq = """
                INSERT INTO responses (msg_info, tags) VALUES ($1, $2)
              """

        json_info = json.dumps(info)
        await self.database.execute(dbq, json_info, tags)

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

    async def send_msg(self, evt: MessageEvent, info: dict) -> None:
        if info['original'].startswith("mxc"):
            await self.client.send_image(evt.room_id, url=info['original'], file_name=info['filename'],
                    info=ImageInfo(
                        mimetype=info['mimetype'],
                        width=info['width'],
                        height=info['height'],
                        size=info['size']
                    )
                )
        else:
            await evt.respond(f"<blockquote><h1><em>{info['body']}</em></h1>\
                                <p>-- <a href=\"https://matrix.to/#/{info['sender']}\">{info['sender']}</a></p>\
                                </blockquote>", 
                                allow_html=True) 

    @command.new(name=get_command_name, help="save and tag, or return, message contents", require_subcommand=False,
                 arg_fallthrough=False)

    @command.argument("tags", pass_raw=True, required=True)
    async def gifme(self, evt: MessageEvent, tags: str) -> None:
        tags = self.sanistring(tags)

        if not tags:
            await evt.respond(f"<code>!{self.config['command_prefix']} \<phrase\></code>: return a gif matching \<phrase\><br />\
                        <code>!{self.config['command_prefix']} giphy \<phrase\></code>: return a gif from giphy search matching\
                        \<phrase\><br />\
                        <code>!{self.config['command_prefix']} save \<phrase\></code>: use in reply to a message to save\
                        the message contents with \<phrase\> as tags, or update the existing tags<br />\
                        <code>!{self.config['command_prefix']} tags</code>: use in reply to a message i sent\
                        to see the tags associated with that message in the database",
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
                    await evt.respond("i couldn't come up with anything, sorry.")
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


    @gifme.subcommand("save", help="save and tag a message to the database")
    @command.argument("tags", pass_raw=True, required=True)
    async def save(self, evt: MessageEvent, tags: str) -> None:
        await evt.mark_read()

        if self.config["restrict_users"]:
            if evt.sender in self.config["allowed_users"]:
                pass
            else:
                await evt.respond("you're not allowed to do that.")
                return None

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to save")
            return None

        message_info = {}

        ## fetch our replied-to event contents
        reply_event = await self.client.get_event(evt.room_id, evt.content.get_reply_to())
        if reply_event.content.msgtype == MessageType.IMAGE:
            message_info["original"] = reply_event.content.url
            message_info["filename"] = reply_event.content.body
            message_info["mimetype"] = reply_event.content.info.mimetype
            message_info["height"] = reply_event.content.info.height
            message_info["width"] = reply_event.content.info.width
            message_info["size"] = reply_event.content.info.size

        elif reply_event.content.msgtype == MessageType.TEXT:
            if self.config["allow_non_files"] == False:
                await evt.respond("i'm not allowed to save anything that isn't a file upload")
                return None
            else:
                message_info["body"] = reply_event.content.body
                message_info["sender"] = reply_event.sender
                message_info["original"] = reply_event.event_id

        elif reply_event.content.msgtype == MessageType.NOTICE:
            await evt.reply("i'm not going to save that, it looks like it's from a bot.")
            return None

        else:
            await evt.respond(f"i don't know what {reply_event.content.msgtype} is, but i can't save it.")
            return None

        if not message_info["original"]:
            await evt.respond(f"sorry, that image appears to be encrypted, and i can't save it.")
            return None

        row = await self.get_row(message_info["original"])

        ## if the entry exists, just append new tags
        if row:
            rowid = row['docid']
            tags = tags.split()
            oldtags = row["tags"].split()
            difftags = []
            newtags = oldtags

            for t in tags:
                if t in oldtags:
                    pass
                else:
                    difftags.append(t)

            updatemsg = await evt.respond(f"matching entry found, adding the following new tags: {difftags}")
            updateevt = await self.client.get_event(evt.room_id, updatemsg)
            newtags.extend(difftags)
            try:
                await self.update_tags(' '.join(newtags), rowid)
                await updateevt.react(f"✅")
            except:
                await updateevt.react(f"❌")
        else:
            await self.save_msg(message_info, tags)
            await evt.respond(f"saved to database!")

    @gifme.subcommand("tags", help="return the tags associated with a specific response from the database")
    async def return_tags(self, evt: MessageEvent) -> None:
        await evt.mark_read()

        if not evt.content.get_reply_to():
            await evt.reply("use this command in a reply to another message so i know what to look up tags for")
            return None

        original = None
        reply_event = await self.client.get_event(evt.room_id, evt.content.get_reply_to())

        if reply_event.content.msgtype == MessageType.IMAGE:
            original = reply_event.content.url
        elif reply_event.content.msgtype == MessageType.TEXT:
            original = reply_event.event_id
        else:
            await evt.respond("i don't recognize this message, sorry.")
            return None

        entry = await self.get_row(original)
        if entry:
            await evt.respond(f"this saved entry has the following tags: {entry['tags']}")
        else:
            await evt.respond(f"i don't see this message in my database.")


    @classmethod
    def get_db_upgrade_table(cls) -> None:
        return upgrade_table

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
