import config
from .base import BaseVote


class Civis(BaseVote):
    required_time = 172800  # 2 days
    required_lines = 250
    duration = 2419200  # 28 days
    name = "civis"

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +V'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -V'
                         .format(config.CHANNEL, target))

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'V' in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "already enfranchised.")
        return super().vote_check(args, by)


class Censure(BaseVote):
    supermajority = True
    name = "censure"

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -V'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +V'
                         .format(config.CHANNEL, target))

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'V' not in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "not enfranchised.")
        if 'o' in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "a staff.")
        return super().vote_check(args, by)


class Staff(BaseVote):
    required_time = 2419200  # 28 days
    required_lines = 1500
    duration = 2419200  # 28 days
    openfor = 86400 # 1 day
    quorum = 5
    supermajority = True
    name = "staff"
    cooldown = 604800  # 7 days
    
    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +o'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -o'
                         .format(config.CHANNEL, target))

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'V' not in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "not enfranchised.")
        return super().vote_check(args, by)
