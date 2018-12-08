import asyncio
import mimetypes
import logging
import operator
import os
import re
import requests
from functools import reduce
import aiohttp

import discord
from line import LineBotApi
from line.exceptions import LineBotApiError
from line.models import TextSendMessage, ImageSendMessage, VideoSendMessage, AudioSendMessage
from line.models import (FlexSendMessage, BubbleContainer, FillerComponent, BoxComponent,
                         ImageComponent, TextComponent, IconComponent)

logger = logging.getLogger(__name__)

def group(list, group_size):
    """ Splits the given array into an array of subarrays,
        with each subarray having at most group_size many elements.
    """ 
    return [ list[start_idx:start_idx + group_size] for start_idx in range(0, len(list), group_size) ]

class TwitchBroadcastAnnouncer:
    @staticmethod
    def subscribe(user_name):
        response = requests.post(os.environ['TWITCH_SUBSCRIBE_URL'], data={ 'user_name' : user_name })
        try:
            response.raise_for_status()
        except:
            logger.error('Unable to subscribe for Twitch user {}'.format(user_name))

class LineCarbot:
    token = os.environ['LINE_TOKEN']
    api = LineBotApi(token)
    target_group_id = os.environ['LINE_TARGET_GROUP_ID']

class DiscordCarbot(discord.Client):
    token = os.environ['DISCORD_TOKEN']
    # id of the bot that sends Line messages to Discord,
    # this bot should ignore messages from that bot or else it becomes an infinite feedback
    friend_bot_id = int(os.environ['DISCORD_FRIEND_BOT_ID'])
    target_channel = 'line'


    async def on_member_update(self, before, after):
        dest_channel = discord.utils.find(lambda channel: str(channel) == self.target_channel, after.guild.channels)
        if dest_channel is None:
            return

        if isinstance(after.activity, discord.Streaming) and not isinstance(before.activity, discord.Streaming):
            # user is currently streaming but not before
            # let's broadcast it
            TwitchBroadcastAnnouncer.subscribe(after.activity.twitch_name)

    async def on_message(self, message):
        if isinstance(message.channel, discord.DMChannel):
            # message is private, 
            # forward it to target_channel, and to Line through another on_message event
            await self.broadcast_from_private_channel(message)
        elif ( str(message.channel) == DiscordCarbot.target_channel and  # message came from target channel
               message.type == discord.MessageType.default and           # message not from system
               message.author.id != DiscordCarbot.friend_bot_id          # friend bot didn't send the message
        ): await self.forward_message(message)


    async def broadcast_from_private_channel(self, message):
        # only look at guilds that the author belongs in,
        # so that no random/malicious person can send message to our Line counterpart
        for guild in filter(lambda guild: message.author in guild.members, self.guilds):
            dest_channel = discord.utils.find(lambda channel: str(channel) == self.target_channel, guild.channels)
            if dest_channel is None:
                continue

            if message.content:
                await dest_channel.send(content=message.content)

            if message.attachments:
                async with aiohttp.ClientSession() as client:
                    for attachment in message.attachments:
                        async with client.get(attachment['url']) as r:
                            await dest_channel.send(destination=dest_channel, 
                                                    file=discord.File(r.content, filename=attachment['filename'])
                                                    )
            # this message shall be forwarded to line too, 
            # through another on_message event with author = self.user

            logger.info('user {m.author} sent a message with content:\n'
                        '{m.content}\n'
                        'and attachments(filenames only):\n'
                        '{filenames}'.format(m=message, filenames=str([a['filename'] for a in message.attachments])))


    async def forward_message(self, message):
        transforms = [ self.text_message, self.attachments ]
        # each transform function returns a list, this line flattens the list of lists into a single list,
        # e.g. flatten([ [a], [b, c] ]) => [a, b, c]
        # it is set up this way because one Discord message can contain multiple attachments,
        # so that one transform function can return more than one Line SendMessage object
        messages = reduce(operator.add, [ T(message) for T in transforms ], [])
        
        # Line only allows up to 5 messages per push_message API call,
        # let's split the message array into bite-size subarrays in case there are more than
        # 5 messages in the original array.

        for grouped_messages in group(messages, 5):
            try:
                logger.info('Sending a message to group with id {group_id}:\n{messages}'
                            .format(group_id=str(LineCarbot.target_group_id),
                                    messages=str(grouped_messages)))
                LineCarbot.api.push_message(LineCarbot.target_group_id, grouped_messages)
            except LineBotApiError as err:
                logger.error('LineBotApiError raised:\n{error}'
                             .format(error=str(err)))

    """ Regex that matches an emoji string, in its text form.

        An emoji is of the form: <:(emoji name):(emoji hash)>.
        For example, <:crown:408166031022882816> is a valid emoji

        Captures the emoji hash.

        Discord seems to sanitize messages so we don't have to worry about 
        having message content in this form but is not an emoji.
    """
    emoji_regex = re.compile(r'<:[^:]+:([0-9]+)>')

    """ Regex that matches a message with just emojis, in its text form.

        A message that contains just emojis is a message such that there is no
        non-emoji text in the content, except whitespaces.
        For example, "<:rock:408166560826654730> <:crown:408166031022882816>"
        matches this regex.
    """
    plain_emoji_msg_regex = re.compile(r'^(?:\s*<:[^:]+:[0-9]+>\s*)+$')

    """ Regex that matches a url.
        
        This is needed since URLs sent in a flex message will not appear in
        Line as a clickable link, nor is it copiable, which is extremely
        inconvenient as the user will eventually need to open Discord to open
        the link, which defeats the whole purpose of the bot.

        Credits goes to gruber @ https://gist.github.com/gruber/8891611
    """
    url_regex = re.compile(r'''(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))''')

    def text_message(self, message):
        if message.author.bot:
            if not message.content:
                # this message only has attachments,
                # don't send any text message
                return []

            # don't show name if the message was sent by this bot
            message_author = avatar = []
        else:
            # message_author is one line of string (no wrap) that has the author name 
            # with a color as displayed in Discord
            message_author = [ TextComponent(text=str(message.author.display_name), weight='bold', flex=0, 
                                             color=str(message.author.color), size='sm') ]
            # avatar is an image placed on the left of the message_box
            # NOTE: avatar_url gives a webp format which Line doesn't know how to deal with.
            #       Let's just guess the png file name from the user id and avatar hash.
            #       default_avatar_url is a png so no guessing is needed.
            avatar = [ ImageComponent(url=message.author.default_avatar_url if not message.author.avatar else
                                          'https://cdn.discordapp.com/avatars/{0.id}/{0.avatar}.png?size=256'.format(message.author),
                                      flex=0, size='xxs') ]

        message_body_boxes = []

        if not message.content:
            # message is empty, 
            # since Line doesn't like TextComponent with an empty string,
            # let's just use a filler so that it looks empty
            message_body_boxes.append(FillerComponent())
        elif DiscordCarbot.plain_emoji_msg_regex.match(message.content):
            # message contains only emojis and no other text except whitespaces,
            # let's use icons as the message
            emojis = DiscordCarbot.emoji_regex.findall(message.content)
            if len(emojis) <= 10:
                # one line can fit 6 emojis at 3xl size
                group_size, icon_size = 6, '3xl'
            elif len(emojis) <= 15:
                # one line can fit 8 emojis at xxl size
                group_size, icon_size = 8, 'xxl'
            else:
                # one line can fit 10 emojis at xl size,
                # xl is actually already very small so we are not going below that
                group_size, icon_size = 10, 'xl'

            for emojis_per_line in group(emojis, group_size):
                line_contents = [IconComponent(url='https://cdn.discordapp.com/emojis/{}.png'.format(emoji), size=icon_size) for emoji in emojis_per_line]
                message_body_boxes.append(BoxComponent(layout='baseline', contents=line_contents))
        elif message.author.bot:
            # message is a normal text message, from a bot,
            # let's not use flex because we are not adding avatar and nickname to the message
            return [ TextSendMessage(text=str(message.content)) ]
        else:
            # message is a normal text message, from a user,
            # let's continue building the flex boxes, as we need to show avatar and nickname
            message_body_boxes.append(TextComponent(text=str(message.content), flex=0, wrap=True))


        # message_box contains the author and the message, stacked vertically
        message_box = BoxComponent(layout='vertical', contents=message_author + message_body_boxes)

        # message_card_box is the box that contains the avatar and the message_box, stacked horizontally
        message_card_box = BoxComponent(layout='horizontal', spacing='md', contents=avatar + [ message_box ])

        # NOTE: using footer since it has the least padding; otherwise the message overall would have 
        #       too much unnecessary whitespace
        message_card_bubble = BubbleContainer(footer=message_card_box)

        return ([ FlexSendMessage(alt_text='{author}:{body}'.format(author=message.author.display_name, body=message.content),
                                  contents=message_card_bubble) ] + 
                [ TextSendMessage(text=str(url)) for url in DiscordCarbot.url_regex.findall(str(message.content)) ])

    def attachments(self, message):
        transformed_attachments = []
        
        for attachment in message.attachments:
            guessed_type, _ = mimetypes.guess_type(attachment.filename)
            if guessed_type.startswith('image/'):
                transformed_attachments.append(ImageSendMessage(original_content_url=attachment.url, preview_image_url=attachment.proxy_url))

            elif guessed_type.startswith('audio/'):
                transformed_attachments.append(AudioSendMessage(original_content_url=attachment.url))

            elif guessed_type.startswith('video/'):
                transformed_attachments.append(VideoSendMessage(original_content_url=attachment.url))

            else:
                logger.info('Unhandleable attachment mimetype {}, guessed from filename {}.'.format(guessed_type, attachment.filename))

        return transformed_attachments
