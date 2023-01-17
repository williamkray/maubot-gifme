# gifme

a maubot plugin that saves gifs, memes, or optionally anything else someone has posted, associate tags with it, and then
return it when those tags are called. written because frankly, giphy has gone downhill and a private collection is more
reliable when it comes to a community's expectations of what the reaction should be.

## installation

install like any other maubot plugin: either create a `.zip` file of this repository and upload it, or use `mbc build`
commands to generate and upload a package to your maubot server.

## commands

`!gifme <phrase>` will make the bot respond with a randomly selected gif that matches that phrase. optionally, if no
entries have been stored for that phrase, will fall back to posting something from a giphy search.

`!gifme save <phrase>` should be used in reply to a message in order to save it to the database and tag it with the
phrase given. use double-quotes to ensure multi-word phrases are tied together, for example:
    
    !gifme save that is actually hilarious

would save and tag the image with the tags `that`, `is`, `actually`, and `hilarious`, whereas

    !gifme save "that is actually hilarious"

would save and tag the image with the tag `that is actually hilarious`


## config

`allow_fallback`: enables the ability for gifme to return a result from giphy if no suitable option is found internally.
requires that a giphy api key is added, otherwise fallback will return an error. set to either `true` or `false`

`force_fallback`: skips looking up internal images entirely. useful if you don't have much in your database yet and
you're trying to build up a collection. requires that a giphy api key is added, otherwise fallback will return an error.
set to either `true` or `false`.

`giphy_api_key`: an api key to authenticate against the giphy api endpoint. optional, only used for fallback behavior.

`allow_non_files`: whether to enable storing and returning messages which are not file-uploads. this effectively enables
the bot to function as a message bookmark system, which may be useful in scenarios where the same message is regularly
posted and you want a shortcut to it, you want to return someone's message out-of-context for comedic purposes, etc.
this will return the message as quoted text, with the original sender's matrix ID and the date as the source. set to
either `true` or `false`.

`restrict_users`: whether to restrict tagging and storing permissions to a list of users. set to either `true` or
`false`.

`allowed_users`: list of users who should be allowed to save and tag messages. optional, ignored if `restrict_users` is
set to `false`. set to a yaml list (`[]`).
