"""Regla de puntuación de la porra, portada del Excel (DatuBase!B2:D20).

Ganar o perder de visitante vale sistemáticamente 2 puntos más que de local
para la misma diferencia de goles (1 punto más en caso de empate) — regla
real y deliberada del grupo, no un error de la hoja original.

A diferencia de la tabla del Excel (limitada a diferencias de -9 a +9), aquí
la fórmula es aritmética pura, así que extrapola sola para cualquier
diferencia de goles sin necesidad de un caso especial.
"""
from __future__ import annotations

from .models import Match


def points_for_pick(goals_for: int, goals_against: int, is_home: bool) -> int:
    diff = goals_for - goals_against
    if diff == 0:
        return 1 if is_home else 2
    if diff > 0:
        return diff + 2 if is_home else diff + 4
    margin = -diff
    return -(margin + 4) if is_home else -(margin + 2)


def team_points_in_match(team_id: int, match: Match | None) -> int:
    """Puntos que se llevó `team_id` en `match` esa jornada. 0 si el partido
    todavía no se ha jugado o si el equipo no jugó esa jornada."""
    if match is None or match.home_goals is None or match.away_goals is None:
        return 0
    if match.home_team_id == team_id:
        return points_for_pick(match.home_goals, match.away_goals, is_home=True)
    if match.away_team_id == team_id:
        return points_for_pick(match.away_goals, match.home_goals, is_home=False)
    return 0
