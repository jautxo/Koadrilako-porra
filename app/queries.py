"""Cálculo de clasificaciones a partir de la base de datos. No hay ninguna
columna de puntos guardada: todo se recalcula aquí a partir de partidos,
elecciones de equipos y puntos extra. Con 16 participantes y ~19 jornadas el
volumen de datos es trivial, así que no hace falta optimizar ni cachear."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSettings, DerbyPrediction, Jornada, Match, Participant
from .scoring import team_points_in_match


def get_settings(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
    return settings


@dataclass
class ScoreBoard:
    participants: list[Participant]
    jornadas: list[Jornada]
    per_jornada: dict[int, dict[int, int]]  # jornada_number -> {participant_id: puntos}
    season_total: dict[int, int]  # participant_id -> total (elecciones + derbiak)
    # jornada_number -> {participant_id: bonus metatua, jardunaldiko derbi guztiak batuta}.
    # Independiente de la tranpa, siempre suma.
    derby_bonus_by_jornada: dict[int, dict[int, int]] = field(default_factory=dict)
    derby_matches_by_jornada: dict[int, list[Match]] = field(default_factory=dict)
    derby_predictions_by_match: dict[int, list[DerbyPrediction]] = field(default_factory=dict)
    derby_hits_by_match: dict[int, set[int]] = field(default_factory=dict)  # match_id -> {participant_id asmatu dutenak}

    def jornada_leaderboard(self, jornada_number: int) -> list[tuple[Participant, int]]:
        jornada = next((j for j in self.jornadas if j.number == jornada_number), None)
        scores = self.per_jornada.get(jornada_number, {})
        sign = -1 if (jornada and jornada.is_trap) else 1
        derby_bonus = self.derby_bonus_by_jornada.get(jornada_number, {})
        rows = [
            (p, sign * scores.get(p.id, 0) + derby_bonus.get(p.id, 0))
            for p in self.participants
        ]
        return sorted(rows, key=lambda row: row[1], reverse=True)

    def season_leaderboard(self) -> list[tuple[Participant, int]]:
        rows = [(p, self.season_total.get(p.id, 0)) for p in self.participants]
        return sorted(rows, key=lambda row: row[1], reverse=True)


def build_scoreboard(session: Session, *, include_unpublished: bool = False) -> ScoreBoard:
    """Por defecto solo tiene en cuenta jornadas que el administrador ha
    validado (`is_published`), que es lo que debe ver el público. El admin
    pasa `include_unpublished=True` para revisar el estado completo antes de
    validar."""
    participants = list(session.scalars(select(Participant).order_by(Participant.name)).all())
    jornadas_query = select(Jornada).order_by(Jornada.number)
    if not include_unpublished:
        jornadas_query = jornadas_query.where(Jornada.is_published.is_(True))
    jornadas = list(session.scalars(jornadas_query).all())
    matches = session.scalars(select(Match)).all()
    settings = get_settings(session)

    matches_by_jornada_team: dict[int, dict[int, Match]] = {}
    derby_matches_by_jornada: dict[int, list[Match]] = {}
    for m in matches:
        by_team = matches_by_jornada_team.setdefault(m.jornada_number, {})
        by_team[m.home_team_id] = m
        by_team[m.away_team_id] = m
        if m.is_derby:
            derby_matches_by_jornada.setdefault(m.jornada_number, []).append(m)

    derby_predictions_by_match: dict[int, list[DerbyPrediction]] = {}
    for dp in session.scalars(select(DerbyPrediction)).all():
        derby_predictions_by_match.setdefault(dp.match_id, []).append(dp)

    per_jornada: dict[int, dict[int, int]] = {}
    season_total: dict[int, int] = {p.id: 0 for p in participants}
    derby_bonus_by_jornada: dict[int, dict[int, int]] = {}
    derby_hits_by_match: dict[int, set[int]] = {}

    for jornada in jornadas:
        team_matches = matches_by_jornada_team.get(jornada.number, {})
        scores_this_jornada: dict[int, int] = {}
        sign = -1 if jornada.is_trap else 1
        for p in participants:
            score = sum(
                team_points_in_match(pick.team_id, team_matches.get(pick.team_id))
                for pick in p.picks
            )
            scores_this_jornada[p.id] = score
            season_total[p.id] += sign * score
        per_jornada[jornada.number] = scores_this_jornada

        bonus_this_jornada: dict[int, int] = {}
        for derby_match in derby_matches_by_jornada.get(jornada.number, []):
            hits: set[int] = set()
            if derby_match.home_goals is not None and derby_match.away_goals is not None:
                for dp in derby_predictions_by_match.get(derby_match.id, []):
                    if (
                        dp.predicted_home_goals == derby_match.home_goals
                        and dp.predicted_away_goals == derby_match.away_goals
                    ):
                        hits.add(dp.participant_id)
                        bonus_this_jornada[dp.participant_id] = (
                            bonus_this_jornada.get(dp.participant_id, 0) + settings.derby_bonus_points
                        )
                        season_total[dp.participant_id] += settings.derby_bonus_points
            derby_hits_by_match[derby_match.id] = hits
        derby_bonus_by_jornada[jornada.number] = bonus_this_jornada

    return ScoreBoard(
        participants=participants,
        jornadas=jornadas,
        per_jornada=per_jornada,
        season_total=season_total,
        derby_bonus_by_jornada=derby_bonus_by_jornada,
        derby_matches_by_jornada=derby_matches_by_jornada,
        derby_predictions_by_match=derby_predictions_by_match,
        derby_hits_by_match=derby_hits_by_match,
    )
