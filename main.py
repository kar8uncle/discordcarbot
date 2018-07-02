#!/usr/bin/python3 -p

import logging
import logging.config
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
        # TODO: if it restarts too much eventually it can stack overflow and dies...
        #       maybe consider using exec instead?
        main()


if __name__ == '__main__':
	main()
