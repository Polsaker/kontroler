from datetime import datetime, timedelta


class BaseVote(object):
    required_time = 0
    required_lines = 0
    duration = 120
    openfor = 15
    quorum = 2
    supermajority = False

    is_target_user = True  # True if target is a user in the channel

    def __init__(self, irc):
        self.irc = irc

    def get_target(self, args):
        if self.is_target_user:
            return self.irc.users[args[1]]['account'].lower()
        else:
            return args[1]

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
