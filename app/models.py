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
    is_published: Mapped[bool] = mapped_column(default=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("jornada_number", "home_team_id", "away_team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    jornada_number: Mapped[int] = mapped_column(ForeignKey("jornadas.number"))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_goals: Mapped[int | None] = mapped_column(default=None)
    away_goals: Mapped[int | None] = mapped_column(default=None)
    is_derby: Mapped[bool] = mapped_column(default=False)

    jornada: Mapped["Jornada"] = relationship(foreign_keys=[jornada_number])
    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])


class DerbyPrediction(Base):
    """Marcador que el administrazioak eskuz anotatu du partaide bakoitzeko,
    derbi gisa markatutako partida (`Match.is_derby`) bakoitzarentzat. Jardunaldi
    batek derbi bat baino gehiago izan ditzake."""

    __tablename__ = "derby_predictions"
    __table_args__ = (UniqueConstraint("participant_id", "match_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"))
    jornada_number: Mapped[int] = mapped_column(ForeignKey("jornadas.number"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    predicted_home_goals: Mapped[int]
    predicted_away_goals: Mapped[int]

    participant: Mapped["Participant"] = relationship()
    jornada: Mapped["Jornada"] = relationship()
    match: Mapped["Match"] = relationship()


class AppSettings(Base):
    """Fila única (id=1) con ajustes globales editables desde el admin."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    derby_bonus_points: Mapped[int] = mapped_column(default=5)
    top_highlight_count: Mapped[int] = mapped_column(default=3)
    # Sailkapenean gorriz nabarmentzeko posizio-tartea (1etik hasita, biak
    # barne). 0 bada hasieran, ez da ezer nabarmenduko.
    bottom_highlight_start: Mapped[int] = mapped_column(default=0)
    bottom_highlight_end: Mapped[int] = mapped_column(default=0)
