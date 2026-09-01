"""Modelo de datos SQLAlchemy. Sin columnas de puntos derivados: los puntos
se calculan siempre al vuelo en scoring.py/queries.py a partir de los
partidos y las elecciones de cada participante."""
from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)

    picks: Mapped[list["ParticipantTeam"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan", order_by="ParticipantTeam.id"
    )
    extra_points: Mapped[list["ExtraPoints"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )


class ParticipantTeam(Base):
    __tablename__ = "participant_teams"
    __table_args__ = (UniqueConstraint("participant_id", "team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    participant: Mapped["Participant"] = relationship(back_populates="picks")
    team: Mapped["Team"] = relationship()


class Jornada(Base):
    __tablename__ = "jornadas"

    number: Mapped[int] = mapped_column(primary_key=True)
    is_trap: Mapped[bool] = mapped_column(default=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("jornada_number", "home_team_id", "away_team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    jornada_number: Mapped[int] = mapped_column(ForeignKey("jornadas.number"))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_goals: Mapped[int | None] = mapped_column(default=None)
    away_goals: Mapped[int | None] = mapped_column(default=None)

    jornada: Mapped["Jornada"] = relationship()
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])


class ExtraPoints(Base):
    __tablename__ = "extra_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"))
    jornada_number: Mapped[int] = mapped_column(ForeignKey("jornadas.number"))
    points: Mapped[int]
    note: Mapped[str | None] = mapped_column(default=None)

    participant: Mapped["Participant"] = relationship(back_populates="extra_points")
    jornada: Mapped["Jornada"] = relationship()
