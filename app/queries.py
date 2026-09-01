"""Cálculo de clasificaciones a partir de la base de datos. No hay ninguna
columna de puntos guardada: todo se recalcula aquí a partir de partidos,
elecciones de equipos y puntos extra. Con 16 participantes y ~19 jornadas el
volumen de datos es trivial, así que no hace falta optimizar ni cachear."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ExtraPoints, Jornada, Match, Participant
from .scoring import team_points_in_match


@dataclass
class ScoreBoard:
    participants: list[Participant]
    jornadas: list[Jornada]
    per_jornada: dict[int, dict[int, int]]  # jornada_number -> {participant_id: puntos}
    season_total: dict[int, int]  # participant_id -> total (elecciones + puntos extra)
    extra_by_participant: dict[int, list[ExtraPoints]] = field(default_factory=dict)

    def jornada_leaderboard(self, jornada_number: int) -> list[tuple[Participant, int]]:
        jornada = next((j for j in self.jornadas if j.number == jornada_number), None)
        scores = self.per_jornada.get(jornada_number, {})
        sign = -1 if (jornada and jornada.is_trap) else 1
        rows = [(p, sign * scores.get(p.id, 0)) for p in self.participants]
        return sorted(rows, key=lambda row: row[1], reverse=True)

    def season_leaderboard(self) -> list[tuple[Participant, int]]:
        rows = [(p, self.season_total.get(p.id, 0)) for p in self.participants]
        return sorted(rows, key=lambda row: row[1], reverse=True)


def build_scoreboard(session: Session) -> ScoreBoard:
    participants = list(session.scalars(select(Participant).order_by(Participant.name)).all())
    jornadas = list(session.scalars(select(Jornada).order_by(Jornada.number)).all())
    matches = session.scalars(select(Match)).all()

    matches_by_jornada_team: dict[int, dict[int, Match]] = {}
    for m in matches:
        by_team = matches_by_jornada_team.setdefault(m.jornada_number, {})
        by_team[m.home_team_id] = m
        by_team[m.away_team_id] = m

    extra_by_participant: dict[int, list[ExtraPoints]] = {p.id: [] for p in participants}
    for ep in session.scalars(select(ExtraPoints)).all():
        extra_by_participant.setdefault(ep.participant_id, []).append(ep)

    per_jornada: dict[int, dict[int, int]] = {}
    season_total: dict[int, int] = {p.id: 0 for p in participants}

    for jornada in jornadas:
        team_matches = matches_by_jornada_team.get(jornada.number, {})
        scores_this_jornada: dict[int, int] = {}
        for p in participants:
            score = sum(
                team_points_in_match(pick.team_id, team_matches.get(pick.team_id))
                for pick in p.picks
            )
            scores_this_jornada[p.id] = score
            season_total[p.id] += score
        per_jornada[jornada.number] = scores_this_jornada

    for p in participants:
        season_total[p.id] += sum(ep.points for ep in extra_by_participant.get(p.id, []))

    return ScoreBoard(
        participants=participants,
        jornadas=jornadas,
        per_jornada=per_jornada,
        season_total=season_total,
        extra_by_participant=extra_by_participant,
    )
