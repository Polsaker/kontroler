#!/usr/bin/env python3
import time
import pydle
import argparse
import re
import copy
from datetime import datetime, timedelta
import votes
import config
from models import db, User, Election, Suffrage, Effective
from i18n import _

VOTE_NAMES = {"civis": votes.Civis,
              "censure": votes.Censure,
              "staff": votes.Staff,
              "destaff": votes.Destaff,
              "kick": votes.Kick,
              "topic": votes.Topic,
              "opine": votes.Opine,
              "ban": votes.Ban}


votelistParser = argparse.ArgumentParser()
votelistParser.add_argument('--type')


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
                             pydle.features.AccountSupport,
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
            self._check_flags()

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

            self.eventloop.schedule_periodically(600, self.set_mode, config.CHANNEL, 'b')
            self.eventloop.schedule_periodically(3600, self._check_flags)
        else:
            self.whois(user)

    def _check_flags(self):
        self.civis_count = 0
        self.staff_count = 0
        self.message('ChanServ', 'FLAGS {}'.format(config.CHANNEL))

    def on_raw_367(self, message):
        ban, creator, timestamp = message.params[2:]
        if time.time() - int(timestamp) > 86400:
            self.set_mode(config.CHANNEL, '-b', ban)

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
                                    fl, '')
        elif by == "ChanServ" and target == self.nickname:  # FLAGS
            if message == "You are not authorized to perform this operation.":
                return self.message(config.CHANNEL, _("Error: Can't see ACL"))
            if message.endswith('FLAGS listing.'):
                for k in self.usermap:
                    u = self.usermap[k]['flags']
                    if (('V' in u) or ('O' in u)) and k.lower() != config.SASL_USER.lower():
                        print(self.civis_count, k)
                        try:
                            ef = Effective.select().where(Effective.vote_target == k).get()
                        except Effective.DoesNotExist:
                            flags = 'VO'
                            if self.civis_count <= 3:
                                flags = flags.replace('V', '')
                                self.civis_count -= 1
                            if self.staff_count <= 2:
                                flags = flags.replace('O', '')
                                self.staff_count -= 1
                            self.message('ChanServ', 'FLAGS {0} {1} -{2}'.format(config.CHANNEL, k, flags))
                return
            m = CS_FLAGS_RE.search(message)
            if m:
                if self.usermap.get(m.group(1).lower()):
                    self.usermap[m.group(1).lower()]['flags'] = m.group(2)
                else:
                    self.usermap[m.group(1).lower()] = {"flags": m.group(2)}

                if 'V' in m.group(2):
                    self.civis_count += 1
                if 'O' in m.group(2):
                    self.staff_count += 1

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
            if by not in self.channels[config.CHANNEL]['modes'].get('o', []):
                return self.notice(by, _('Failed: You are not enfranchised.'))
        # 2 - get vote class
        vote = VOTE_NAMES[args[0]](self)
        if not vote.get_target(args):
            return self.notice(by, _('Failed: Target user not found or not identified.'))
        # 3 - check if vote already exists
        opener = User.get(User.name == account)
        try:
            vote = Election.select() \
                           .where(Election.vote_type == args[0],
                                  Election.status == 0,
                                  Election.vote_target == vote.get_target(args)).get()
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
        if not (vote.is_target_user and opener.name == vote.get_target(args)):
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
        self.msg(_("Vote \002#{0}\002: \002{1}\002: \037{2}\037. You have "
                   "\002{3}\002 to vote; \002{4}\002 votes are required for a "
                   "quorum! Type or PM \002\00303!vote y {0}\003\002 or "
                   "\002\00304!vote n {0}\003\002").format(
                       elec.id, args[0], vote.get_target(args), dt, vote.quorum))

    def _closevote(self, voteid):
        """ Called when a vote is to be closed """
        vote = Election.get(Election.id == voteid)
        vclass = VOTE_NAMES[vote.vote_type](self)
        suffrages = Suffrage.select().where(Suffrage.election == vote)
        if suffrages.count() < vclass.quorum:
            self.msg(_("\002#{0}\002: Failed to reach quorum: \002{1}\002 of "
                       "\002{2}\002 required votes.").format(voteid, suffrages.count(), vclass.quorum))
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
        perc = int((yeas / suffrages.count()) * 100)
        if (perc < 75 and vclass.supermajority) or (perc < 51):
            self.msg(_("\002#{0}\002: \002{1}\002: \037{2}\037.  \002\00300,04The nays have it.\003\002 "
                       "Yeas: \00303{3}\003. Nays: \00304{4}\003. \00304{5}\003% of approval (required at least \002{6}%)")
                     .format(voteid, vote.vote_type, vote.vote_target, yeas, nays, perc,
                             75 if vclass.supermajority else 51))
            vote.status = 3  # closed - not approved
            vote.save()
            return
        self.msg(_("\002#{0}\002: \002{1}\002: \037{2}\037. \002\00300,03The yeas have it.\003\002 Yeas: \00303{3}\003. Nays: \00304{4}\003. "
                   "\00303{5}\003% of approval (required at least \002{6}%)")
                 .format(voteid, vote.vote_type, vote.vote_target, yeas, nays, perc,
                         75 if vclass.supermajority else 51))
        vote.status = 1  # closed - passed
        vote.save()
        vclass.on_pass(vote.vote_target)
        act = Effective(vote_type=vote.vote_type,
                        close=datetime.utcnow() +
                        timedelta(seconds=vclass.duration),
                        vote_target=vote.vote_target,
                        election=vote)
        act.save()
        self.eventloop.schedule_in(vclass.duration, self._expire, act.id)

    def _expire(self, efid):
        print("EEEXPIRE")
        vote = Effective.get(Effective.id == efid)
        vclass = VOTE_NAMES[vote.vote_type](self)
        vclass.on_expire(vote.vote_target)
        vote.delete_instance()

    def _resolve_status(self, status):
        if status == 0:
            stat = _('\00301,07ACTIVE\003')
        elif status == 1:
            stat = _('\00300,03PASSED\003')
        elif status == 2:
            stat = _('\00300,04QUORUM\003')
        elif status == 3:
            stat = _('\00300,04FAILED\003')
        elif status == 4:
            stat = _('\00300,04VETOED\003')
        else:
            stat = _('\00300,02LIZARD\003')

        return stat

    def _resolve_time(self, delta, word):
        if delta.total_seconds() > 604800:
            ostr = _('{0} \002weeks {1}\002').format(
                int(delta.total_seconds() / 604800), word)
        elif delta.total_seconds() > 86400:
            ostr = _('{0} \002days {1}\002').format(
                int(delta.total_seconds() / 86400), word)
        elif delta.total_seconds() > 3600:
            ostr = _('{0} \002hours {1}\002').format(
                int(round(delta.total_seconds() / 3600, 0)), word)
        elif delta.total_seconds() > 60:
            ostr = _('{0} \002minutes {1}\002').format(
                int(round(delta.total_seconds() / 60, 0)), word)
        else:
            ostr = _('{0} \002seconds {1}\002').format(
                int(delta.total_seconds()), word)

        return ostr

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
            elif args[0] == "list" and target == config.CHANNEL:
                print('list ', by)
                if by not in self.channels[config.CHANNEL]['modes'].get('v', []):
                    if by not in self.channels[config.CHANNEL]['modes'].get('o', []):
                        return self.notice(by, 'Failed: You are not enfranchised.')
                vpar, unk = votelistParser.parse_known_args(args[1:])
                if not vpar.type:
                    votes = Election.select().where(Election.status == 0) \
                                    .order_by(Election.id.desc()).limit(5)
                else:
                    if vpar.type not in list(VOTE_NAMES):
                        return self.notice(by, 'Failed: Unknown vote type')
                    votes = Election.select() \
                                    .where(Election.vote_type == vpar.type) \
                                    .order_by(Election.id.desc()).limit(10)
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
                        yv = Suffrage.get((Suffrage.election == vote) & (Suffrage.emitted_by == user))
                        if yv.yea:
                            you = '\00300,03YEA\003'
                        else:
                            you = '\00300,04NAY\003'
                    except Suffrage.DoesNotExist:
                        you = '\00300,01---\003'
                    stat = self._resolve_status(vote.status)
                    if vote.status == 0:
                        tdel = vote.close - datetime.utcnow()
                        ostr = self._resolve_time(tdel, _('left'))
                    else:
                        tdel = datetime.utcnow() - vote.close
                        ostr = self._resolve_time(tdel, _('ago'))
                    self.msg(_('\002#{0} YEA: \00303{1}\003 NAY: \00305{2}\003 '
                               'YOU: {3} {4} {5}\002 \037{6}\037 - {7}').format(
                                   vote.id, posit, negat, you, stat,
                                   vote.vote_type, vote.vote_target, ostr))

            elif args[0].isdigit() or args[0] in ['y', 'yes', 'n', 'no']:
                if by not in self.channels[config.CHANNEL]['modes'].get('v', []):
                    if by not in self.channels[config.CHANNEL]['modes'].get('o', []):
                        return self.notice(by, 'Failed: You are not enfranchised.')
                user = User.get(User.name == account)
                if args[0].isdigit():
                    if len(args) == 1:
                        return self.vote_info(by, args[0])
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
                return self.vote(elec, user, by, positive, (target != config.CHANNEL))

    def vote_info(self, by, voteid):
        try:
            elec = Election.get(Election.id == voteid)
        except Election.DoesNotExist:
            return self.notice(by, 'Failed: Vote not found')
        vtype = VOTE_NAMES[elec.vote_type](self)

        if elec.status == 0:
            tdel = elec.close - datetime.utcnow()
            ostr = self._resolve_time(tdel, 'left')
        else:
            tdel = datetime.utcnow() - elec.close
            ostr = self._resolve_time(tdel, 'ago')
        self.notice(by, "Information on vote #{0}: \002{1}\002 ({2})".format(
                        elec.id, self._resolve_status(elec.status), ostr))

        votes = Suffrage.select().where(Suffrage.election == elec)
        yeacount = 0
        yeas = ""
        naycount = 0
        nays = ""
        for vot in votes:
            if vot.yea:
                yeacount += 1
                yeas += vot.emitted_by.name + " "
            else:
                naycount += 1
                nays += vot.emitted_by.name + " "

        votecount = yeacount + naycount
        perc = int((yeacount / votecount)*100) if votecount != 0 else 0
        percneeded = 75 if vtype.supermajority else 50
        if elec.status == 1:
            try:
                eff = Effective.get(Effective.election == elec)
                tdel = eff.close - datetime.utcnow()
                ostr = self._resolve_time(tdel, 'left')
                self.notice(by, " - \002\00303ACTIVE\003\002 {0}".format(ostr))
            except Effective.DoesNotExist:
                self.notice(by, " - \002\00304NOT EFFECTIVE ANYMORE\003\002 (expired)")
                pass
        elif elec.status == 0:
            if votecount < vtype.quorum:
                self.notice(by, " - \002\00307Needs {0} more votes for quorum\002".format(vtype.quorum-votecount))
            else:
                if perc < percneeded:
                    self.notice(by, " - \002\00304Motion is not passing ({0}% of approval, needs {1}%)\002".format(perc, percneeded))
                else:
                    self.notice(by, " - \002\00303Motion is passing ({0}% of approval, needs {1}%)\002".format(perc, percneeded))

        if yeacount == 0:
            yeas = " - "
        if naycount == 0:
            nays = " - "

        self.notice(by, " - \002\00303YEA\003\002 - \002{0}\002: {1}".format(yeacount, yeas))
        self.notice(by, " - \002\00304NAY\003\002 - \002{0}\002: {1}".format(naycount, nays))

    def vote(self, elec, user, by, positive=True, doAnn=False):
        vtype = VOTE_NAMES[elec.vote_type](self)
        if vtype.is_target_user and user.name == elec.vote_target:
            return self.notice(by, 'Failed: You can\'t vote for yourself')
        try:
            svote = Suffrage.get(Suffrage.emitted_by == user,
                                 Suffrage.election == elec)
            if svote.yea == positive:
                self.notice(by, 'Failed: You have already voted on'
                            ' \002#{0}\002'.format(elec.id))
                return
            self.notice(by, 'You have changed your vote on '
                        '\002#{0}\002'.format(elec.id))
            if doAnn:
                self.msg('{0} changed their vote in #\002{2}\002 (now is \002{1}\002)'.format(user.name, '\00303YEA\003' if positive else '\00304NAY\003', elec.id))
        except Suffrage.DoesNotExist:
            svote = Suffrage(election=elec,
                             emitted_by=user)
            if doAnn:
                self.msg('{0} voted \002{1}\002 in #\002{2}\002'.format(user.name, '\00303YEA\003' if positive else '\00304NAY\003', elec.id))
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
