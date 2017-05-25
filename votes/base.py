from datetime import datetime, timedelta
import config
from models import Effective, Election


class BaseVote(object):
    required_time = 0
    required_lines = 0
    duration = 259200  # 3 days
    openfor = 1800  # 30 minutes
    quorum = 3
    supermajority = False
    name = "base"
    cooldown = 86400  # 1 day

    is_target_user = True  # True if target is a user in the channel

    def __init__(self, irc):
        self.irc = irc

    def get_target(self, args):
        if self.is_target_user:
            try:
                return self.irc.users[args[1]]['account'].lower()
            except AttributeError:
                return False
        else:
            return " ".join(args[1:])

    def vote_check(self, args, by):
        if self.is_target_user:
            try:
                account = self.irc.users[args[1]]['account'].lower()
            except KeyError:
                return self.irc.notice(by, 'Can\'t start vote: User not found '
                                       'or not identified.')
            user = self.irc.usermap.get(account)
            if not user or not user.get('lines'):
                return self.irc.notice(by, 'Can\'t start vote: User has never '
                                       'interacted with the channel.')

            try:
                x = Effective.select().where((Effective.vote_type == self.name) &
                                             (Effective.vote_target == self.get_target(args))) \
                             .get()
                try:
                    elecid = x.election.id
                except Election.DoesNotExist:
                    elecid = "Unknown election"
                return self.irc.notice(by, 'Can\'t start vote: There\'s an identical motion already active (\002{0}\002).'.format(elecid))
            except Effective.DoesNotExist:
                pass

            try:
                x = Election.select().where((Election.vote_type == self.name) &
                                            (Election.vote_target == self.get_target(args)) &
                                            (Election.status == 3) &
                                            (Election.close > (datetime.utcnow() - timedelta(seconds=self.cooldown)))).get()
                return self.irc.notice(by, 'Can\'t start vote: There was a similar vote that failed not too long ago (\002{0}\002).'.format(x.id))
            except Election.DoesNotExist:
                pass

            if self.required_time != 0:
                reqtime = datetime.utcnow() - timedelta(seconds=self.required_time)
                if user['first_seen'] > reqtime:
                    return self.irc.notice(by, "Can't start vote: User at issue "
                                           "has not been present long enough for "
                                           "consideration.")

                if user['last_seen'] < reqtime:
                    return self.irc.notice(by, "Can't start vote: User at issue "
                                           "has not been active recently.")

                if user['lines'] < self.required_lines:
                    return self.irc.notice(by, "Can't start vote: User at issue "
                                           "has {0} of {1} required lines"
                                           .format(user['lines'],
                                                   self.required_lines))
        return True  # True = check passed


class Opine(BaseVote):
    openfor = 900  # 15 minutes
    name = "opine"
    duration = 0

    is_target_user = False

    def on_pass(self, issue):
        self.irc.msg("The people of {0} decided \002{1}\002".format(
                    config.CHANNEL,
                    issue))


    def on_expire(self, target):
        pass
