from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Place(Base):
    """Модель места досуга."""

    __tablename__ = "places"

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)
    city = Column(Text)
    district = Column(Text)
    address = Column(Text)
    rating = Column(Float)
    reviews_count = Column(Integer, default=0)
    ratings_count = Column(Integer, default=0)
    working_hours = Column(Text)
    website = Column(Text)
    phone = Column(Text)
    location = Column(Geography("POINT", srid=4326))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tags = relationship("Tag", secondary="place_tags", back_populates="places")
    interactions = relationship("UserInteraction", back_populates="place")

    __table_args__ = (
        Index("idx_places_district", "district"),
        Index("idx_places_rating", "rating", postgresql_ops={"rating": "DESC"}),
        Index("idx_places_city", "city"),
        Index("idx_places_name", text("to_tsvector('russian', name)"), postgresql_using="gin"),
        Index("idx_places_location", "location", postgresql_using="gist"),
    )


class Tag(Base):
    """Модель тега."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    places = relationship("Place", secondary="place_tags", back_populates="tags")

    __table_args__ = (Index("idx_tags_name", "name"),)


# Association table для many-to-many связи Place и Tag
place_tags = Table(
    "place_tags",
    Base.metadata,
    Column("place_id", BigInteger, ForeignKey("places.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_place_tags_place", "place_id"),
    Index("idx_place_tags_tag", "tag_id"),
)


class UserProfile(Base):
    """Модель профиля пользователя."""

    __tablename__ = "user_profiles"

    telegram_id = Column(BigInteger, primary_key=True)
    preferred_tags = Column(ARRAY(Text))
    avoided_tags = Column(ARRAY(Text))
    favorite_districts = Column(ARRAY(Text))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    interactions = relationship("UserInteraction", back_populates="user_profile")

    __table_args__ = (Index("idx_user_profiles_telegram", "telegram_id"),)


class UserInteraction(Base):
    """Модель взаимодействия пользователя с местом."""

    __tablename__ = "user_interactions"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, ForeignKey("user_profiles.telegram_id"))
    place_id = Column(BigInteger, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    interaction_type = Column(Text, nullable=False)  # viewed, liked, visited, disliked
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user_profile = relationship("UserProfile", back_populates="interactions")
    place = relationship("Place", back_populates="interactions")

    __table_args__ = (
        Index("idx_user_interactions_telegram", "telegram_id"),
        Index("idx_user_interactions_place", "place_id"),
        Index("idx_user_interactions_type", "interaction_type"),
    )
