from geoalchemy2 import Geometry
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    UniqueConstraint
)


Base = declarative_base()


class Gym(Base):
    __tablename__ = 'gym'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    location = Column(Geometry(geometry_type='POINT', srid=4326))
    ex = Column(Boolean, default=False)


class GymAlias(Base):
    __tablename__ = 'gymalias'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    gym_id = Column(Integer, ForeignKey("gym.id"))
    gym = relationship(Gym, foreign_keys=[gym_id])
    guild_id = Column(BigInteger)


class Pokestop(Base):
    __tablename__ = 'pokestop'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)


class Pokemon(Base):
    __tablename__ = 'pokemon'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    raid_level = Column(Integer, nullable=True)
    ex = Column(Boolean, default=False)
    types = Column(Integer, nullable=True)
    perfect_cp = Column(Integer, nullable=True)
    perfect_cp_boosted = Column(Integer, nullable=True)
    availability_rules = Column(String, nullable=True)
    shiny = Column(Boolean, default=False)


class Raid(Base):
    __tablename__ = 'raid'
    id = Column(Integer, primary_key=True)
    pokemon_id = Column(Integer, ForeignKey("pokemon.id"), nullable=True)
    pokemon = relationship(Pokemon, foreign_keys=[pokemon_id])
    gym_id = Column(Integer, ForeignKey("gym.id"))
    gym = relationship(Gym, foreign_keys=[gym_id])
    despawn_time = Column(DateTime)
    start_time = Column(DateTime)
    level = Column(Integer, nullable=True)
    ex = Column(Boolean, default=False)
    hatched = Column(Boolean, default=False)
    despawned = Column(Boolean, default=False)
    cancelled = Column(Boolean, default=False)


class Event(Base):
    __tablename__ = 'event'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    done = Column(Boolean, default=False)
    cancelled = Column(Boolean, default=False)


class Embed(Base):
    __tablename__ = 'embed'
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger)
    message_id = Column(BigInteger)
    raid_id = Column(Integer, ForeignKey("raid.id"))
    raid = relationship(Raid, foreign_keys=[raid_id])
    embed_type = Column(Integer)


class Going(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    guild_id = Column(BigInteger)
    extra = Column(Integer, default=0)


class RaidGoing(Going, Base):
    raid_id = Column(Integer, ForeignKey("raid.id"))
    raid = relationship(Raid, foreign_keys=[raid_id])
    __table_args__ = (UniqueConstraint('raid_id', 'user_id', name='_raid_id_user_uc'),)


class EventGoing(Going, Base):
    event_id = Column(Integer, ForeignKey("event.id"))
    event = relationship(Event, foreign_keys=[event_id])


class Party(Base):
    __tablename__ = 'party'
    id = Column(Integer, primary_key=True)
    creator_user_id = Column(BigInteger)
    user_id = Column(BigInteger)
    guild_id = Column(BigInteger)
    extra = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint('creator_user_id', 'user_id', name='_creator_user_id_user_id_uc'),)


class GuildConfig(Base):
    __tablename__ = 'guildconfig'
    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger)
    channel_id = Column(BigInteger)
    mirror = Column(Boolean, default=False)
    region = Column(Geometry('POLYGON', srid=4326), nullable=True, default=None)
    timezone = Column(String, default="Europe/London")
    subscriptions = Column(Boolean, default=False)
    emoji_going = Column(String, default="\U0001F44D")
    #__table_args__ = (UniqueConstraint('guild_id', 'key', name='_guild_id_key_uc'),)
