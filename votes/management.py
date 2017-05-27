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


class Kick(BaseVote):
    openfor = 600  # 10 minutes
    name = "kick"
    duration = 0

    def on_pass(self, target):
        self.irc.kick(config.CHANNEL, target, "The people have decided.")

    def on_expire(self, target):
        pass


class Topic(BaseVote):
    openfor = 900  # 15 minutes
    name = "topic"
    duration = 0

    is_target_user = False

    def on_pass(self, issue):
        self.irc.message('ChanServ', 'TOPIC {0} {1}'.format(config.CHANNEL, issue))

    def on_expire(self, target):
        pass
