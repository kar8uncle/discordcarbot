#!/usr/bin/python3

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

def main():
    try:
        DiscordCarbot().run(DiscordCarbot.token)
    except SystemExit:
        pass
    except Exception as e:
        logging.getLogger('carbot').error('Caught exception: ' + str(e))
        os.execv(__file__, sys.argv)


if __name__ == '__main__':
	main()
