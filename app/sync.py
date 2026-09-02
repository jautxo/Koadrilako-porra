"""Jardunaldi baten emaitzak football-data.org-etik sinkronizatzeko logika,
admin panelaren botoiak eta scheduler automatikoak partekatzen dutena."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .football_api import FootballDataClient
from .models import Jornada, Match, Team
from .validation import load_team_mapping, translate_team_name


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def sync_jornada(session: Session, number: int, force: bool = False, api_matches=None) -> SyncResult:
    """`api_matches` aurrez eskuratuta badago (adib. scheduler-ak jardunaldi
    guztientzat eskaera bakarrean lortuta), hori erabiltzen da eta ez da
    football-data.org berriro kontsultatzen jardunaldi honentzat bakarrik."""
    jornada = session.get(Jornada, number)
    if jornada is None:
        jornada = Jornada(number=number)
        session.add(jornada)
        session.flush()

    result = SyncResult()

    if api_matches is None:
        try:
            client = FootballDataClient()
            api_matches = client.get_matches(matchday=number)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"Ezin izan da football-data.org kontsultatu: {exc}")
            api_matches = []

    mapping = load_team_mapping()
    teams_by_name = {t.name: t for t in session.scalars(select(Team)).all()}
    existing = {
        (m.home_team_id, m.away_team_id): m
        for m in session.scalars(select(Match).where(Match.jornada_number == number)).all()
    }

    for api_match in api_matches:
        home_name = translate_team_name(api_match.home_team, mapping)
        away_name = translate_team_name(api_match.away_team, mapping)
        if home_name is None or away_name is None:
            result.warnings.append(
                f"Ez dago mapaketarik '{api_match.home_team}' edo '{api_match.away_team}' "
                "taldeentzat team_mapping.json fitxategian."
            )
            result.skipped += 1
            continue
        home_team = teams_by_name.get(home_name)
        away_team = teams_by_name.get(away_name)
        if home_team is None or away_team is None:
            result.warnings.append(f"'{home_name}' edo '{away_name}' ez dago denboraldiko taldeen zerrendan.")
            result.skipped += 1
            continue

        has_score = api_match.finished and api_match.home_goals is not None and api_match.away_goals is not None
        key = (home_team.id, away_team.id)
        match = existing.get(key)
        if match is None:
            match = Match(
                jornada_number=number,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                home_goals=api_match.home_goals if has_score else None,
                away_goals=api_match.away_goals if has_score else None,
            )
            session.add(match)
            existing[key] = match
            result.created += 1
        elif has_score:
            already_has_result = match.home_goals is not None or match.away_goals is not None
            if not already_has_result or force:
                match.home_goals = api_match.home_goals
                match.away_goals = api_match.away_goals
                result.updated += 1

    session.commit()
    return result
