import asyncio
import mimetypes
import logging
import operator
import os
from functools import reduce

import discord
from line import LineBotApi
from line.models import TextSendMessage, ImageSendMessage, VideoSendMessage, AudioSendMessage
from line.models import (FlexSendMessage, BubbleContainer, FillerComponent, BoxComponent,
                         ImageComponent, TextComponent, IconComponent)

logger = logging.getLogger(__name__).setLevel(logging.INFO)

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
        if ( str(message.channel) == DiscordCarbot.target_channel and  # message came from target channel
             message.type == discord.MessageType.default and           # message not from system
             message.author != self.user and                           # this bot didn't send the message
             message.author.id != DiscordCarbot.friend_bot_id          # friend bot didn't send the message
        ): await self.forward_message(message)

    async def forward_message(self, message):
        transforms = [ DiscordCarbot.text_message, DiscordCarbot.attachments ]
        # each transform function returns a list, this line flattens the list of lists into a single list,
        # it is set up this way because one Discord message can contain multiple attachments,
        # so that transform function can return more than one Line SendMessage object
        messages = reduce(operator.add, [ T(message) for T in transforms ], [])

        def group_messages(messages, group_size=5):
            """ Splits array of messages into arrays of subarrays of messages,
                with each subarray having at most group_size many messages.
                A group_size of 5 is the maximum that the push_message API allows up to.
            """ 
            return [ messages[start_idx:start_idx + group_size] for start_idx in range(0, len(messages), group_size) ]

        for grouped_messages in group_messages(messages):
            LineCarbot.api.push_message(LineCarbot.target_group_id, grouped_messages)

    @staticmethod
    def text_message(message):
        # message_body_box contains a line of message
        # TODO: when we (if ever) support inline emojis, there will be more than one message_body_box
        message_body = ( FillerComponent() if not message.content else
                         TextComponent(text=str(message.content), flex=0, wrap=True) )
        message_body_box = BoxComponent(layout='baseline', contents=[ message_body ])

        # message_author is one line of string (no wrap) that has the author name 
        # with a color as displayed in Discord
        message_author = TextComponent(text=str(message.author.display_name), weight='bold', flex=0, 
                                       color=str(message.author.color), size='sm')

        # message_box contains the author and the message, stacked vertically
        message_box = BoxComponent(layout='vertical', contents=[ message_author, message_body_box ])

        # avatar is an image placed on the left of the message_box
        # NOTE: avatar_url gives a webp format which Line doesn't know how to deal with.
        #       Let's just guess the png file name from the user id and avatar hash.
        #       default_avatar_url is a png so no guessing is needed.
        avatar = ImageComponent(url=message.author.default_avatar_url if not message.author.avatar else
                                    'https://cdn.discordapp.com/avatars/{0.id}/{0.avatar}.png?size=256'.format(message.author),
                                flex=0, size='xxs')

        # message_card_box is the box that contains the avatar and the message_box, stacked horizontally
        message_card_box = BoxComponent(layout='horizontal', spacing='md', contents=[ avatar, message_box ])

        # NOTE: using footer since it has the least padding; otherwise the message overall would have 
        #       too much unnecessary whitespace
        message_card_bubble = BubbleContainer(footer=message_card_box)

        return [ FlexSendMessage(alt_text='{author}:{body}'.format(author=message.author.display_name, body=message.content),
                                 contents=message_card_bubble) ]

    @staticmethod
    def attachments(message):
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
