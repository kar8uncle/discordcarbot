#!/usr/bin/python3 -p

import logging
import logging.config
import sys
import os
from carbot import DiscordCarbot

LOGGING_CONFIG = None
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'carbot': {
            'level': 'INFO',
            'handlers': ['console']
        },
    },
})

logger = logging.getLogger(__name__)

def main():
    try:
        DiscordCarbot().run(DiscordCarbot.token)
    except Exception as e:
        logger.error('Caught exception: ' + str(e))
    finally:
        os.execv(__file__, sys.argv)


if __name__ == '__main__':
	main()
