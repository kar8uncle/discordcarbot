import asyncio
import mimetypes
import logging
import operator
import os
import re
from functools import reduce
import aiohttp

import discord
from line import LineBotApi
from line.models import TextSendMessage, ImageSendMessage, VideoSendMessage, AudioSendMessage
from line.models import (FlexSendMessage, BubbleContainer, FillerComponent, BoxComponent,
                         ImageComponent, TextComponent, IconComponent)

logger = logging.getLogger(__name__)

def group(list, group_size):
    """ Splits the given array into an array of subarrays,
        with each subarray having at most group_size many elements.
    """ 
    return [ list[start_idx:start_idx + group_size] for start_idx in range(0, len(list), group_size) ]

class LineCarbot:
    token = os.environ['LINE_TOKEN']
    api = LineBotApi(token)
    target_group_id = os.environ['LINE_TARGET_GROUP_ID']

class DiscordCarbot(discord.Client):
    token = os.environ['DISCORD_TOKEN']
    # id of the bot that sends Line messages to Discord,
    # this bot should ignore messages from that bot or else it becomes an infinite feedback
    friend_bot_id = os.environ['DISCORD_FRIEND_BOT_ID']
    target_channel = 'line'

    async def on_message(self, message):
        if message.channel.is_private:
            # message is private, 
            # forward it to target_channel, and to Line through another on_message event
            await self.broadcast_from_private_channel(message)
        elif ( str(message.channel) == DiscordCarbot.target_channel and  # message came from target channel
               message.type == discord.MessageType.default and           # message not from system
               message.author.id != DiscordCarbot.friend_bot_id          # friend bot didn't send the message
        ): await self.forward_message(message)


    async def broadcast_from_private_channel(self, message):
        # only look at servers that the author belongs in,
        # so that no random/malicious person can send message to our Line counterpart
        for server in filter(lambda server: message.author in server.members, self.servers):
            try:
                dest_channel = next(filter(lambda channel: str(channel) == self.target_channel, server.channels))
                if message.attachments:
                    async with aiohttp.ClientSession() as client:
                        for attachment in message.attachments:
                            async with client.get(attachment['url']) as r:
                                # sending the message content together with attachments,
                                # so that they can be deleted together :P
                                await self.send_file(destination=dest_channel, filename=attachment['filename'],
                                                     fp=r.content, content=message.content or None)
                elif message.content:
                    await self.send_message(destination=dest_channel, content=message.content)

                # this message shall be forwarded to line too, 
                # through another on_message event with author = self.user
            except StopIteration:
                # no target_channel in server,
                # let's just do nothing
                pass

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
            LineCarbot.api.push_message(LineCarbot.target_group_id, grouped_messages)


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

        return [ FlexSendMessage(alt_text='{author}:{body}'.format(author=message.author.display_name, body=message.content),
                                 contents=message_card_bubble) ]

    def attachments(self, message):
        transformed_attachments = []
        
        for attachment in message.attachments:
            guessed_type, _ = mimetypes.guess_type(attachment['filename'])
            if guessed_type.startswith('image/'):
                transformed_attachments.append(ImageSendMessage(original_content_url=attachment['url'], preview_image_url=attachment['proxy_url']))

            elif guessed_type.startswith('audio/'):
                transformed_attachments.append(AudioSendMessage(original_content_url=attachment['url']))

            elif guessed_type.startswith('video/'):
                transformed_attachments.append(VideoSendMessage(original_content_url=attachment['url']))

            else:
                logger.info('Unhandleable attachment mimetype {}, guessed from filename {}.'.format(guessed_type, attachment['filename']))

        return transformed_attachments
