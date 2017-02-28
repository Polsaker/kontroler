#!/usr/bin/env python3
import pydle
import re
from datetime import datetime
from peewee import SqliteDatabase, Model, CharField, DateTimeField
from peewee import ForeignKeyField, BooleanField, IntegerField
import config

db = SqliteDatabase('users.db')


class User(Model):
    name = CharField()
    first_seen = DateTimeField()
    last_seen = DateTimeField()
    lines = IntegerField()

    class Meta:
        database = db


class Election(Model):
    vote_type = IntegerField()  # Vote type (1 = civis, ...)
    opened = DateTimeField()
    closed = DateTimeField()
    opened_by = ForeignKeyField(User, related_name='votes_opened')
    opened_for = ForeignKeyField(User, related_name='votes_subjected')

    class Meta:
        database = db


class Suffrage(Model):
    election = ForeignKeyField(Election, related_name='suffrages')
    yea = BooleanField()
    emitted_by = ForeignKeyField(User, related_name='suffrages')

    class Meta:
        database = db


db.connect()
db.create_tables([User, Election, Suffrage], True)


BaseClient = pydle.featurize(pydle.features.RFC1459Support,
                             pydle.features.TLSSupport,
                             pydle.features.AccountSupport,
                             pydle.features.WHOXSupport)

CS_FLAGS_RE = re.compile(r'\d+\s+(.+?)\s+\+(.+?)\s+(?:\(.+\))?\s+\((\#.+)\).*')


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

    def on_private_notice(self, by, message):
        if by == "ChanServ":  # FLAGS
            if message == "You are not authorized to perform this operation.":
                return self.message(config.CHANNEL, "Error: Can't see ACL")
            m = CS_FLAGS_RE.search(message)
            if m:
                if self.usermap.get(m.group(1).lower()):
                    self.usermap[m.group(1).lower()]['flags'] = m.group(2)
                else:
                    self.usermap[m.group(1).lower()] = {"flags": m.group(2)}

    def on_notice(self, target, by, message):
        if by == "ChanServ" and target != self.nickname:
            self.message('ChanServ', 'FLAGS {}'.format(target))

    def on_message(self, target, by, message):
        if target != config.CHANNEL:
            return  # TODO: commands - via private message
        print(self.usermap)
        account = self.users[by]['account'].lower()
        if not account:
            return  # Unregistered users don't exist

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
                dbuser.lines = user['lines']
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


client = Kontroler('Kontroler')
client.connect(config.IRC_SERVER, tls=True)
client.handle_forever()
