from sqlalchemy import Column, Integer, String

from app.db import Base


class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    album = Column(String, index=True)
    duration = Column(Integer, nullable=True)
    source = Column(String, index=True, default="unknown")
    path = Column(String)
