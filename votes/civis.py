import config
from .base import BaseVote
from models import Election, Effective


class Civis(BaseVote):
    required_time = 172800  # 2 days
    required_lines = 250
    duration = 2419200  # 28 days
    name = "civis"

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +V'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        try:
            x = Effective.select().where((Effective.vote_type == "staff") &
                                         (Effective.vote_target == target)).get()
            return self.irc.msg('\002{0}\002\'s civis expired. Not removing, as they are active staff.'.format(target))
        except Effective.DoesNotExist:
            pass
        try:
            x = Effective.select().where((Effective.vote_type == "civis")).count()
            if x <= 3:
                return self.irc.msg('\002{0}\002\'s civis expired. Not removing as there are too few enfranchised users.')
        except Effective.DoesNotExist:
            pass
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
    required_lines = 2500
    duration = 2419200  # 28 days
    openfor = 86400  # 1 day
    quorum = 5
    supermajority = True
    name = "staff"
    cooldown = 604800  # 7 days

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} +O'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        f = self.irc.usermap[target]['flags']
        print(f, ' ', target)
        if 'V' in f:
            flags = '-VO'
        else:
            flags = '-O'
        try:
            x = Effective.select().where((Effective.vote_type == "staff")).count()
            if x <= 2:
                return self.irc.msg('\002{0}\002\'s civis expired. Not removing as there are too few enfranchised users.')
        except Effective.DoesNotExist:
            pass

        self.irc.message('ChanServ', 'FLAGS {0} {1} {2}'
                         .format(config.CHANNEL, target, flags))

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'V' not in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "not enfranchised.")
        return super().vote_check(args, by)


class Destaff(BaseVote):
    duration = 0
    openfor = 86400  # 1 day
    quorum = 5
    supermajority = True
    name = "destaff"
    cooldown = 604800  # 7 days

    def on_pass(self, target):
        self.irc.message('ChanServ', 'FLAGS {0} {1} -O'
                         .format(config.CHANNEL, target))

    def on_expire(self, target):
        pass

    def vote_check(self, args, by):
        f = self.irc.usermap[self.get_target(args)]['flags']
        if 'O' not in f:
            return self.irc.notice(by, "Can't start vote: User at issue is "
                                   "not staff.")
        return super().vote_check(args, by)
