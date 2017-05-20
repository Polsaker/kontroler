import config
from .base import BaseVote


class Ban(BaseVote):
    required_time = 0
    required_lines = 0
    duration = 259200  # 3 days
    name = "ban"

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +b'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -b'
                         .format(config.CHANNEL, target))
