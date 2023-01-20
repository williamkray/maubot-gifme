# gifme

NOTE: this bot has only been tested, and is assumed to only work, using SQLite as the plugin database.

a maubot plugin that saves gifs, memes, or optionally anything else someone has posted, associate tags with it, and then
return it when those tags are called. written because frankly, giphy has gone downhill and a private collection is more
reliable when it comes to a community's expectations of what the reaction should be.

## installation

install like any other maubot plugin: either create a `.zip` file of this repository and upload it, or use `mbc build`
commands to generate and upload a package to your maubot server.

## commands

`!gifme <phrase>` will make the bot respond with a randomly selected gif that matches that phrase. optionally, if no
entries have been stored for that phrase, will fall back to posting something from a giphy search.

`!gifme giphy <phrase>` will skip looking up internally and just go right to returning a result from giphy. this enables
you to force fallback without needing to set the plugin to do so all the time.

`!gifme save <phrase>` should be used in reply to a message in order to save it to the database and tag it with the
phrase or words given. tags are stored as text entries in the sqlite database, and returned with full-text search
queries so no need to get too crazy about quotes or separation. _NOTE: if the image is already stored in the database
the command will update the tags for the existing image, minus any duplicate words. This effectively enables you to add
more tags to an entry._

`!gifme tags` should be used in a reply to a message sent by the bot to show all tags associated with the image.

## config

`command_prefix`: the command to use for this module. defaults to `gifme`. 

`allow_fallback`: enables the ability for gifme to return a result from giphy if no suitable option is found internally.
requires that a giphy api key is added, otherwise fallback will return an error. set to either `true` or `false`

`fallback_threshold`: the number of results that need to be returned from the internal database before falling back to a
giphy search. for example, if set to `2`, there must be at least two entries in the internal database returned, and if
there are not the bot will search giphy. set to `0` to force fallback at all times and effectively make the bot function
purely as a giphy bot.

`giphy_api_key`: an api key to authenticate against the giphy api endpoint. optional, only used for fallback behavior.

`allow_non_files`: whether to enable storing and returning messages which are not file-uploads. this effectively enables
the bot to function as a message bookmark system, which may be useful in scenarios where the same message is regularly
posted and you want a shortcut to it, you want to return someone's message out-of-context for comedic purposes, etc.
this will return the message as quoted text, with the original sender's matrix ID and the date as the source. set to
either `true` or `false`. *WARNING! this will store the content of the message as plain-text in the database, as well as
the sender of that message, even for messages sent in encrypted rooms. DO NOT ENABLE THIS IF YOU ARE CONCERNED ABOUT PRIVACY.*

`restrict_users`: whether to restrict tagging and storing permissions to a list of users. set to either `true` or
`false`.

`allowed_users`: list of users who should be allowed to save and tag messages. optional, ignored if `restrict_users` is
set to `false`. set to a yaml list (`[]`).
