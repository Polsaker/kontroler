import config
from .base import BaseVote


class Civis(BaseVote):
    required_time = 172800  # 2 days
    required_lines = 250
    duration = 2419200  # 28 days

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
        return super().vote_check(args, by)


class Arripio(object):
    temporary = False  # Permanent
    openfor = 86400
    quorum = 5
    supermajority = True

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -Vo'
                         .format(config.CHANNEL, target))

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'V' not in f or 'o' not in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "not enfranchised.")
        return super().vote_check(args, by)
