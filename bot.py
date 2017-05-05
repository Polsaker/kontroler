#!/usr/bin/env python3
import pydle
import argparse
import re
import copy
from datetime import datetime, timedelta
from peewee import SqliteDatabase, Model, CharField, DateTimeField
from peewee import ForeignKeyField, BooleanField, IntegerField
import votes
import config

VOTE_NAMES = {"civis": votes.Civis,
              "censure": votes.Censure,
              "staff": votes.Staff}

db = SqliteDatabase('users.db')

votelistParser = argparse.ArgumentParser()
votelistParser.add_argument('--type')


class User(Model):
    name = CharField()
    first_seen = DateTimeField()
    last_seen = DateTimeField()
    lines = IntegerField()

    class Meta:
        database = db


class Election(Model):
    vote_type = CharField()
    opened = DateTimeField()  # when election started
    close = DateTimeField()  # when election should close
    status = IntegerField()  # 0=open, 1=passed, 2=quorum, 3=not passed, 4=veto
    opened_by = ForeignKeyField(User, related_name='votes_opened')
    vote_target = CharField()

    class Meta:
        database = db


class Suffrage(Model):
    election = ForeignKeyField(Election, related_name='suffrages')
    yea = BooleanField()
    emitted_by = ForeignKeyField(User, related_name='suffrages')

    class Meta:
        database = db


class Effective(Model):
    vote_type = CharField()
    close = DateTimeField()
    vote_target = CharField()

    class Meta:
        database = db


db.connect()
db.create_tables([User, Election, Suffrage, Effective], True)


def display_time(seconds, granularity=2):
    intervals = (
        ('weeks', 604800),  # 60 * 60 * 24 * 7
        ('days', 86400),    # 60 * 60 * 24
        ('hours', 3600),    # 60 * 60
        ('minutes', 60),
        ('seconds', 1),
    )
    result = []

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(value, name))
        else:
            # Add a blank if we're in the middle of other values
            if len(result) > 0:
                result.append(None)
    return ', '.join([x for x in result[:granularity] if x is not None])


BaseClient = pydle.featurize(pydle.features.RFC1459Support,
                             pydle.features.IRCv3Support,
                             pydle.features.WHOXSupport)

CS_FLAGS_RE = re.compile(r'\d+\s+(.+?)\s+\+(.+?)\s+(?:\(.+\))?\s+\((\#.+)\).*')
CS_FCHANGE_RE = re.compile(r'set flags \002(.+?)\002 on \002(.+?)\002')


class Kontroler(BaseClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # {"Account": {"flags": ..., "lines": ..., ...}}
        self.usermap = {}

        for user in User.select():
            self.usermap[user.name] = {"lines": user.lines,
                                       "first_seen": user.first_seen,
                                       "last_seen": user.last_seen,
                                       "flags": ""}

    def on_connect(self):
        super().on_connect()
        self.join(config.CHANNEL)

    def on_join(self, channel, user):
        if user == self.nickname:
            self.message('ChanServ', 'FLAGS {}'.format(channel))

            for elec in Election.select().where(Election.status == 0):
                if elec.close < datetime.utcnow():
                    # Already closed!!
                    self._closevote(elec.id)
                else:
                    closes_in = elec.close - datetime.utcnow()
                    self.eventloop.schedule_in(closes_in, self._closevote, elec.id)

            for elec in Effective.select():
                if elec.close < datetime.utcnow():
                    # Already closed!!
                    self._expire(elec.id)
                else:
                    closes_in = elec.close - datetime.utcnow()
                    self.eventloop.schedule_in(closes_in, self._expire, elec.id)
        else:
            self.whois(user)

    def on_notice(self, target, by, message):
        if by == "ChanServ" and target == config.CHANNEL:
            m = CS_FCHANGE_RE.search(message)
            if m:
                for fl in m.group(1):
                    if fl == '+':
                        add = True
                    elif fl == '-':
                        add = False
                    else:
                        if add:
                            self.usermap[m.group(2).lower()]['flags'] += fl
                        else:
                            self.usermap[m.group(2).lower()]['flags'] = \
                             self.usermap[m.group(2).lower()]['flags'].replace(
                                fl, ''
                             )
        elif by == "ChanServ" and target == self.nickname:  # FLAGS
            if message == "You are not authorized to perform this operation.":
                return self.message(config.CHANNEL, "Error: Can't see ACL")
            m = CS_FLAGS_RE.search(message)
            if m:
                if self.usermap.get(m.group(1).lower()):
                    self.usermap[m.group(1).lower()]['flags'] = m.group(2)
                else:
                    self.usermap[m.group(1).lower()] = {"flags": m.group(2)}

    def msg(self, message):
        return self.notice(config.CHANNEL, message)

    def count_line(self, account):
        if self.usermap.get(account):
            user = self.usermap[account]
            user['last_seen'] = datetime.utcnow()
            if user.get('lines'):
                user['lines'] += 1
            else:
                user['lines'] = 1
                user['first_seen'] = datetime.utcnow()
                dbuser = User(name=account, lines=1,
                              first_seen=datetime.utcnow(),
                              last_seen=datetime.utcnow())
                dbuser.save()
            if (user['lines'] % 5) == 0:
                dbuser = User.get(User.name == account)
                dbuser.lines += 5
                dbuser.last_seen = user['last_seen']
                dbuser.save()
        else:
            user = {"first_seen": datetime.utcnow(),
                    "last_seen": datetime.utcnow(),
                    "lines": 1,
                    "flags": ""}
            dbuser = User(name=account, lines=1,
                          first_seen=datetime.utcnow(),
                          last_seen=datetime.utcnow())
            dbuser.save()
        self.usermap[account] = user

    def start_vote(self, by, args):
        account = self.users[by]['account'].lower()
        # 1 - Check if user has voice
        if by not in self.channels[config.CHANNEL]['modes'].get('v', []):
            return self.notice(by, 'Failed: You are not enfranchised.')
        # 2 - get vote class
        vote = VOTE_NAMES[args[0]](self)
        if not vote.get_target(args):
            return self.notice(by, 'Failed: Target user not found or not identified.')
        # 3 - check if vote already exists
        opener = User.get(User.name == account)
        try:
            vote = Election.select() \
                        .where(Election.vote_type == args[0],
                               Election.status == 0,
                               Election.vote_target == vote.get_target(args)) \
                        .get()
            # !!! vote already exists
            return self.vote(vote, opener, by)
        except Election.DoesNotExist:
            pass

        # 5 - Custom vote type checks
        if vote.vote_check(args, by) is not True:
            print("Vote creation rejected by custom rule")
            return

        # 6 - Create the vote
        elec = Election(vote_type=args[0],
                        opened=datetime.utcnow(),
                        close=datetime.utcnow() +
                        timedelta(seconds=vote.openfor),
                        status=0,
                        opened_by=opener,
                        vote_target=vote.get_target(args))
        elec.save()
        # 7 - Emit self vote
        svote = Suffrage(election=elec,
                         yea=True,
                         emitted_by=opener)
        svote.save()
        # 8 - Schedule
        self.eventloop.schedule_in(timedelta(seconds=vote.openfor),
                                   self._closevote, elec.id)
        # 9 - announce
        dt = display_time(vote.openfor)
        self.msg("Vote \002#{0}\002: \002{1}\002: \037{2}\037. You have "
                 "\002{3}\002 to vote; \002{4}\002 votes are required for a "
                 "quorum! Type or PM \002\00303!vote y {0}\003\002 or "
                 "\002\00304!vote n {0}\003\002".format(
                     elec.id, args[0], vote.get_target(args), dt, vote.quorum
                 ))

    def _closevote(self, voteid):
        """ Called when a vote is to be closed """
        vote = Election.get(Election.id == voteid)
        vclass = VOTE_NAMES[vote.vote_type](self)
        suffrages = Suffrage.select().where(Suffrage.election == vote)
        if suffrages.count() < vclass.quorum:
            self.msg("\002#{0}\002: Failed to reach quorum: \002{1}\002 of "
                     "\002{2}\002 required votes.".format(voteid,
                                                          suffrages.count(),
                                                          vclass.quorum))
            vote.status = 2  # Closed - quorum
            vote.save()
            return
        yeas = 0
        nays = 0
        for sf in suffrages:
            if sf.yea:
                yeas += 1
            else:
                nays += 1
        perc = int((yeas / suffrages.count())*100)
        if (perc < 75 and vclass.supermajority) or (perc < 51):
            self.msg("\002#{0}\002: \002{1}\002: \037{2}\037. "
                     "\002\00300,04The nays have it.\003\002 "
                     "Yeas: \00303{3}\003. Nays: \00304{4}\003. "
                     "\00304{5}\003% of approval (required at least "
                     "\002{6}%)".format(voteid, vote.vote_type,
                                        vote.vote_target,
                                        yeas, nays, perc,
                                        75 if vclass.supermajority else 51))
            vote.status = 3  # closed - not approved
            vote.save()
            return
        self.msg("\002#{0}\002: \002{1}\002: \037{2}\037. "
                 "\002\00300,03The yeas have it.\003\002 "
                 "Yeas: \00303{3}\003. Nays: \00304{4}\003. "
                 "\00303{5}\003% of approval (required at least "
                 "\002{6}%)".format(voteid, vote.vote_type,
                                    vote.vote_target,
                                    yeas, nays, perc,
                                    75 if vclass.supermajority else 51))
        vote.status = 1  # closed - passed
        vote.save()
        vclass.on_pass(vote.vote_target)
        act = Effective(vote_type=vote.vote_type,
                        close=datetime.utcnow() +
                        timedelta(seconds=vclass.duration),
                        vote_target=vote.vote_target)
        act.save()
        self.eventloop.schedule_in(vclass.duration, self._expire, act.id)

    def _expire(self, efid):
        print("EEEXPIRE")
        vote = Effective.get(Effective.id == efid)
        vclass = VOTE_NAMES[vote.vote_type](self)
        vclass.on_expire(vote.vote_target)
        vote.delete_instance()

    def on_message(self, target, by, message):
        try:
            account = self.users[by]['account']
        except KeyError:
            print("{0}: Not identified/not found".format(by))
            return
        if not account:
            return  # Unregistered users don't exist
        account = account.lower()
        if target == config.CHANNEL:
            self.count_line(account)

        message = message.strip().lower()

        if not message.startswith('!'):
            return

        command = message[1:].split()[0]
        args = message.split()[1:]

        if command == 'vote':
            if not args:
                return
            args[0] = args[0].strip('#')
            if args[0] in list(VOTE_NAMES):  # creating a vote!
                self.start_vote(by, args)
            elif args[0] == "list":
                vpar = votelistParser.parse_args(args[1:])
                if not vpar.type:
                    votes = Election.select().where(Election.status == 0) \
                                    .limit(5)
                else:
                    if vpar.type not in list(VOTE_NAMES):
                        return self.notice(by, 'Failed: Unknown vote type')
                    votes = Election.select() \
                                    .where(Election.vote_type == vpar.type) \
                                    .limit(10)
                if not votes:
                    return self.notice(by, 'No matching results.')
                user = User.get(User.name == account)
                for vote in votes:
                    posit = Suffrage.select() \
                                    .where((Suffrage.election == vote) &
                                           (Suffrage.yea == True)).count()
                    negat = Suffrage.select() \
                                    .where((Suffrage.election == vote) &
                                           (Suffrage.yea == False)).count()
                    try:
                        yv = Suffrage.get(Suffrage.emitted_by == user)
                        if yv.yea:
                            you = '\00300,03YEA\003'
                        else:
                            you = '\00300,04NAY\003'
                    except Suffrage.DoesNotExist:
                        you = '\00300,01---\003'
                    if vote.status == 0:
                        stat = '\00301,07ACTIVE\003'
                    elif vote.status == 1:
                        stat = '\00300,03PASSED\003'
                    elif vote.status == 2:
                        stat = '\00300,04QUORUM\003'
                    elif vote.status == 3:
                        stat = '\00300,04FAILED\003'
                    elif vote.status == 4:
                        stat = '\00300,04VETOED\003'
                    else:
                        stat = '\00300,02LIZARD\003'
                    if vote.status == 0:
                        tdel = vote.close - datetime.utcnow()
                        if tdel.total_seconds() > 3600:
                            ostr = '{0} \002hours left\002'.format(
                                round(tdel.total_seconds()/3600, 2))
                        elif tdel.total_seconds() > 60:
                            ostr = '{0} \002minutes left\002'.format(
                                round(tdel.total_seconds()/60, 2))
                        else:
                            ostr = '{0} \002seconds left\002'.format(
                                int(tdel.total_seconds()))
                    else:
                        tdel = datetime.utcnow() - vote.close
                        if tdel.total_seconds() > 604800:
                            ostr = '{0} \002weeks ago\002'.format(
                                int(tdel.total_seconds()/604800))
                        elif tdel.total_seconds() > 86400:
                            ostr = '{0} \002days ago\002'.format(
                                int(tdel.total_seconds()/86400))
                        elif tdel.total_seconds() > 3600:
                            ostr = '{0} \002hours ago\002'.format(
                                round(tdel.total_seconds()/3600, 2))
                        elif tdel.total_seconds() > 60:
                            ostr = '{0} \002minutes ago\002'.format(
                                round(tdel.total_seconds()/60, 2))
                        else:
                            ostr = '{0} \002seconds ago\002'.format(
                                int(tdel.total_seconds()))
                    self.msg('\002#{0} YEA: \00303{1}\003 NAY: \00305{2}\003 '
                             'YOU: {3} {4} {5}\002 \037{6}\037 - {7}'.format(
                                 vote.id, posit, negat, you, stat,
                                 vote.vote_type, vote.vote_target, ostr))

            elif args[0].isdigit() or args[0] in ['y', 'yes', 'n', 'no']:
                if by not in self.channels[config.CHANNEL]['modes'] \
                                 .get('v', []):
                    return self.notice(by, 'Failed: You are not enfranchised.')
                if len(args) == 1:
                    pass  # vote INFO
                user = User.get(User.name == account)
                if args[0].isdigit():
                    voteid = args[0]
                    positive = True if args[1] in ['y', 'yes'] else False
                else:
                    positive = True if args[0] in ['y', 'yes'] else False
                    if len(args) == 1:
                        xe = Election.select().where(Election.status == 1)
                        if xe.count() == 1:
                            voteid = xe.get().id
                        else:
                            return self.notice(by, 'Failed: Usage: !vote y/n '
                                               '<vote id>')
                    else:
                        voteid = args[1].strip('#')
                        if not voteid.isdigit():
                            self.notice(by, 'Usage: !vote y/n <vote id>')
                            return
                try:
                    elec = Election.get(Election.id == voteid)
                except Election.DoesNotExist:
                    return self.notice(by, 'Failed: Vote not found')
                if elec.status != 0:
                    return self.notice(by, 'Failed: This vote already '
                                       'ended')
                return self.vote(elec, user, by, positive)

    def vote(self, elec, user, by, positive=True):
        try:
            svote = Suffrage.get(Suffrage.emitted_by == user,
                                 Suffrage.election == elec)
            if svote.yea == positive:
                self.notice(by, 'Failed: You have already voted on'
                            ' \002#{0}\002'.format(elec))
                return
            self.notice(by, 'You have changed your vote on '
                        '\002#{0}\002'.format(elec))

        except Suffrage.DoesNotExist:
            svote = Suffrage(election=elec,
                             emitted_by=user)
            self.notice(by, 'Thanks for casting your vote in '
                        '\002#{0}\002'.format(elec.id))
        svote.yea = positive
        svote.save()

    def _rename_user(self, user, new):
        if user in self.users:
            self.users[new] = copy.copy(self.users[user])
            self.users[new]['nickname'] = new
            del self.users[user]
        else:
            self._create_user(new)
            if new not in self.users:
                return

        for ch in self.channels.values():
            # Rename user in channel list.
            if user in ch['users']:
                ch['users'].discard(user)
                ch['users'].add(new)


client = Kontroler('Kontroler',
                   sasl_username=config.SASL_USER,
                   sasl_password=config.SASL_PASS)
client.connect(config.IRC_SERVER, tls=True)
try:
    client.handle_forever()
except KeyboardInterrupt:
    print("Saving all our stuff...")
    for usr in client.usermap:
        uinfo = client.usermap[usr]
        if not uinfo.get('lines'):
            continue
        try:
            user = User.get(User.name == usr)
            user.lines = uinfo['lines']
            user.last_seen = uinfo['last_seen']
        except User.DoesNotExist:
            user = User(name=usr, lines=uinfo['lines'],
                        first_seen=uinfo['first_seen'],
                        last_seen=uinfo['last_seen'])
        user.save()
