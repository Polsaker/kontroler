from peewee import SqliteDatabase, Model, CharField, DateTimeField
from peewee import ForeignKeyField, BooleanField, IntegerField


db = SqliteDatabase('users.db')
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
    election = ForeignKeyField(Election, related_name='effective')
    vote_type = CharField()
    close = DateTimeField()
    vote_target = CharField()

    class Meta:
        database = db


db.connect()
db.create_tables([User, Election, Suffrage, Effective], True)
