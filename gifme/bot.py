# gifme - a maubot plugin to overcome the fact that giphy kinda sucks

from typing import Awaitable, Type, Optional, Tuple
import json
import time
import random
import urllib.parse

from mautrix.client import Client
from mautrix.types import (Event, StateEvent, EventID, UserID, FileInfo, EventType, RoomID,
                            MediaMessageEventContent, ReactionEvent, RedactionEvent, ImageInfo)
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command, event

# database table related things
from .db import upgrade_table



class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("allow_fallback")
        helper.copy("force_fallback")
        helper.copy("giphy_api_key")
        helper.copy("allow_non_files")
        helper.copy("restrict_users")
        helper.copy("allowed_users")


class GifMe(Plugin):

    async def start(self) -> None:
        await super().start()
        self.config.load_and_update()
        
    async def get_giphy(self, evt: MessageEvent, query: str) -> None:

        #query = query.replace('"', '') # remove quotes to pass raw terms to giphy
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
        info['mime'] = 'image/gif'
        info['filename'] = "giphy.gif"

        ## download the image, and upload it to the matrix media repository
        async with self.http.get(gif_link) as response:
            if response.status != 200:
                await evt.respond(f"Something went wrong: {response.status}")
                return None

            imgdata = await response.read()

        info['mxc_uri'] = await self.client.upload_media(imgdata, mime_type=info['mime'], filename=info['filename'])

        ## return an object with the necessary information to send a message
        return info


    async def send_msg(self, room_id: RoomID, info: dict) -> None:
        await self.client.send_image(room_id, url=info['mxc_uri'], file_name=info['filename'],
                info=ImageInfo(
                    mimetype=info['mime'],
                    width=info['width'],
                    height=info['height'],
                    size=info['size']
                )
            )

    @command.new(name="gifme", help="save and tag, or return, message contents", require_subcommand=False,
                 arg_fallthrough=False)

    @command.argument("tags", pass_raw=True, required=True)
    async def gifme(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        img_info = {}
        fallback_status = 0
        await evt.mark_read()
        if self.config["force_fallback"]:
            img_info = await self.get_giphy(evt, tags)
        else:
            ## logic to do local lookup
            if self.config["allow_fallback"]:
                img_info = await self.get_giphy(evt, tags)
                fallback_status = 1

        await self.send_msg(evt.room_id, img_info)
        if fallback_status > 0:
            await evt.respond("psst... i couldn't find a saved response, so i found something on giphy. be sure to save\
                    it if it's any good.")

    @gifme.subcommand("giphy", help="use giphy to search for a gif without using the local collection")

    @command.argument("tags", pass_raw=True, required=True)
    async def giphy(self, evt: MessageEvent, tags: str) -> None:
        if not tags:
            tags = "random"
        img_info = {}
        await evt.mark_read()
        
        img_info = await self.get_giphy(evt, tags)

        await self.send_msg(evt.room_id, img_info)


    @gifme.subcommand("save", help="save and tag a message to the database")
    async def save(self, evt: MessageEvent) -> None:
        await evt.mark_read()
        await evt.respond("this doesn't work yet.")



    @classmethod
    def get_db_upgrade_table(cls) -> None:
        return upgrade_table

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
