from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_admin
from .cache import cached
from .db import get_session, init_db
from .football_api import FootballDataClient
from .models import ExtraPoints, Jornada, Match, Participant, ParticipantTeam, Team
from .queries import build_scoreboard
from .validation import (
    load_team_mapping,
    translate_team_name,
    validate_new_participant_name,
    validate_participant_teams,
)

MADRID_TZ = ZoneInfo("Europe/Madrid")
LIGA_ULTIMA_JORNADA = 19


def _format_kickoff(utc_date: str) -> str:
    dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00")).astimezone(MADRID_TZ)
    return dt.strftime("%d/%m/%Y %H:%M")


def _liga_matches_por_jornada(max_matchday: int = LIGA_ULTIMA_JORNADA) -> dict[int, list[dict]]:
    client = FootballDataClient()
    matches = cached("liga_matches_all", 300, client.get_matches)
    by_jornada: dict[int, list[dict]] = {}
    for m in matches:
        if m.matchday > max_matchday:
            continue
        by_jornada.setdefault(m.matchday, []).append(
            {
                "home": m.home_team,
                "away": m.away_team,
                "home_goals": m.home_goals,
                "away_goals": m.away_goals,
                "finished": m.finished,
                "kickoff": _format_kickoff(m.utc_date),
            }
        )
    return dict(sorted(by_jornada.items()))

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR.parent / ".env")

app = FastAPI(title="La Porra")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

init_db()


# --------------------------------------------------------------------------
# Público
# --------------------------------------------------------------------------

@app.get("/")
def leaderboard(request: Request, session: Session = Depends(get_session)):
    board = build_scoreboard(session)
    return templates.TemplateResponse(
        "leaderboard.html", {"request": request, "ranking": board.season_leaderboard()}
    )


@app.get("/jornadas")
def jornadas_list(request: Request, session: Session = Depends(get_session)):
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    return templates.TemplateResponse("jornadas.html", {"request": request, "jornadas": jornadas})


@app.get("/jornada/{number}")
def jornada_detail(number: int, request: Request, session: Session = Depends(get_session)):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")

    matches = session.scalars(
        select(Match).where(Match.jornada_number == number)
    ).all()

    board = build_scoreboard(session)
    all_numbers = sorted(j.number for j in board.jornadas)
    idx = all_numbers.index(number)

    return templates.TemplateResponse(
        "jornada.html",
        {
            "request": request,
            "jornada": jornada,
            "matches": matches,
            "leaderboard": board.jornada_leaderboard(number),
            "prev_number": all_numbers[idx - 1] if idx > 0 else None,
            "next_number": all_numbers[idx + 1] if idx < len(all_numbers) - 1 else None,
        },
    )


@app.get("/liga/clasificacion")
def liga_clasificacion(request: Request):
    standings: list[dict] = []
    error = None
    try:
        client = FootballDataClient()
        standings = cached("liga_standings", 600, client.get_standings)
    except Exception as exc:  # noqa: BLE001 - se muestra al usuario tal cual
        error = str(exc)
    return templates.TemplateResponse(
        "liga_clasificacion.html", {"request": request, "standings": standings, "error": error}
    )


@app.get("/liga/calendario")
def liga_calendario(request: Request):
    by_jornada: dict[int, list[dict]] = {}
    error = None
    try:
        by_jornada = _liga_matches_por_jornada()
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    return templates.TemplateResponse(
        "liga_calendario.html", {"request": request, "by_jornada": by_jornada, "error": error}
    )


@app.get("/liga/resultados")
def liga_resultados(request: Request):
    by_jornada: dict[int, list[dict]] = {}
    error = None
    try:
        by_jornada = _liga_matches_por_jornada()
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    return templates.TemplateResponse(
        "liga_resultados.html", {"request": request, "by_jornada": by_jornada, "error": error}
    )


@app.get("/participante/{participant_id}")
def participante_detail(participant_id: int, request: Request, session: Session = Depends(get_session)):
    participant = session.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participante no encontrado")

    board = build_scoreboard(session)
    cumulative = 0
    rows = []
    for jornada in board.jornadas:
        points = board.per_jornada.get(jornada.number, {}).get(participant.id, 0)
        cumulative += points
        rows.append({
            "number": jornada.number,
            "is_trap": jornada.is_trap,
            "points": points,
            "cumulative": cumulative,
        })

    return templates.TemplateResponse(
        "participante.html",
        {
            "request": request,
            "participant": participant,
            "jornada_rows": rows,
            "extra_points": board.extra_by_participant.get(participant.id, []),
            "season_total": board.season_total.get(participant.id, 0),
        },
    )


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------

@app.get("/admin")
def admin_dashboard(request: Request, _: str = Depends(require_admin)):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request})


# --- Participantes ---------------------------------------------------------

@app.get("/admin/participantes")
def admin_participantes(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    return templates.TemplateResponse(
        "admin/participantes.html", {"request": request, "participants": participants}
    )


@app.get("/admin/participantes/nuevo")
def admin_participante_nuevo_form(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    all_teams = [t.name for t in session.scalars(select(Team).order_by(Team.name)).all()]
    return templates.TemplateResponse(
        "admin/participante_form.html",
        {"request": request, "editing": False, "all_teams": all_teams, "errors": [], "name": "", "selected": []},
    )


@app.post("/admin/participantes/nuevo")
async def admin_participante_nuevo_submit(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    name = (form.get("name") or "").strip()
    team_names = [(form.get(f"team_{i}") or "").strip() for i in range(8)]

    all_teams_rows = session.scalars(select(Team).order_by(Team.name)).all()
    canonical_teams = {t.name for t in all_teams_rows}
    existing_names_lower = {
        p.name.lower() for p in session.scalars(select(Participant)).all()
    }

    errors = validate_new_participant_name(name, existing_names_lower)
    errors += validate_participant_teams(team_names, canonical_teams)

    if errors:
        return templates.TemplateResponse(
            "admin/participante_form.html",
            {
                "request": request,
                "editing": False,
                "all_teams": [t.name for t in all_teams_rows],
                "errors": errors,
                "name": name,
                "selected": team_names,
            },
        )

    teams_by_name = {t.name: t for t in all_teams_rows}
    participant = Participant(name=name)
    participant.picks = [ParticipantTeam(team=teams_by_name[t]) for t in team_names]
    session.add(participant)
    session.commit()
    return RedirectResponse("/admin/participantes", status_code=303)


@app.get("/admin/participantes/{participant_id}/editar")
def admin_participante_editar_form(
    participant_id: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    participant = session.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participante no encontrado")
    all_teams = [t.name for t in session.scalars(select(Team).order_by(Team.name)).all()]
    selected = [pick.team.name for pick in participant.picks]
    return templates.TemplateResponse(
        "admin/participante_form.html",
        {
            "request": request,
            "editing": True,
            "name": participant.name,
            "all_teams": all_teams,
            "errors": [],
            "selected": selected,
        },
    )


@app.post("/admin/participantes/{participant_id}/editar")
async def admin_participante_editar_submit(
    participant_id: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    participant = session.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participante no encontrado")

    form = await request.form()
    team_names = [(form.get(f"team_{i}") or "").strip() for i in range(8)]

    all_teams_rows = session.scalars(select(Team).order_by(Team.name)).all()
    canonical_teams = {t.name for t in all_teams_rows}
    errors = validate_participant_teams(team_names, canonical_teams)

    if errors:
        return templates.TemplateResponse(
            "admin/participante_form.html",
            {
                "request": request,
                "editing": True,
                "name": participant.name,
                "all_teams": [t.name for t in all_teams_rows],
                "errors": errors,
                "selected": team_names,
            },
        )

    teams_by_name = {t.name: t for t in all_teams_rows}
    participant.picks = [ParticipantTeam(team=teams_by_name[t]) for t in team_names]
    session.commit()
    return RedirectResponse("/admin/participantes", status_code=303)


# --- Equipos -----------------------------------------------------------

@app.get("/admin/equipos")
def admin_equipos(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    teams = session.scalars(select(Team).order_by(Team.name)).all()
    return templates.TemplateResponse(
        "admin/equipos.html", {"request": request, "teams": teams, "errors": [], "messages": []}
    )


@app.post("/admin/equipos/nuevo")
async def admin_equipo_nuevo(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    name = (form.get("name") or "").strip()
    teams = session.scalars(select(Team).order_by(Team.name)).all()
    errors = []
    if not name:
        errors.append("Falta el nombre del equipo.")
    elif name in {t.name for t in teams}:
        errors.append(f"'{name}' ya está en la lista.")
    else:
        session.add(Team(name=name))
        session.commit()
        return RedirectResponse("/admin/equipos", status_code=303)

    return templates.TemplateResponse(
        "admin/equipos.html", {"request": request, "teams": teams, "errors": errors, "messages": []}
    )


@app.post("/admin/equipos/sync")
def admin_equipos_sync(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    teams = session.scalars(select(Team).order_by(Team.name)).all()
    errors: list[str] = []
    messages: list[str] = []

    try:
        client = FootballDataClient()
        api_teams = client.get_teams()
    except Exception as exc:  # noqa: BLE001 - se muestra al admin tal cual
        errors.append(f"No se pudo consultar football-data.org: {exc}")
        return templates.TemplateResponse(
            "admin/equipos.html", {"request": request, "teams": teams, "errors": errors, "messages": messages}
        )

    mapping = load_team_mapping()
    current_names = {t.name for t in teams}
    added = []
    for api_team in api_teams:
        canonical = translate_team_name(api_team["name"], mapping)
        if canonical is None:
            errors.append(
                f"'{api_team['name']}' (shortName={api_team['shortName']!r}, tla={api_team['tla']!r}) "
                "no tiene mapeo en team_mapping.json — añádelo a mano antes de sincronizar."
            )
            continue
        if canonical not in current_names:
            session.add(Team(name=canonical))
            current_names.add(canonical)
            added.append(canonical)

    session.commit()
    if added:
        messages.append("Equipos añadidos: " + ", ".join(sorted(added)))
    else:
        messages.append("No hay equipos nuevos que añadir.")

    teams = session.scalars(select(Team).order_by(Team.name)).all()
    return templates.TemplateResponse(
        "admin/equipos.html", {"request": request, "teams": teams, "errors": errors, "messages": messages}
    )


# --- Jornadas / resultados ----------------------------------------------

@app.get("/admin/jornadas")
def admin_jornadas(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    return templates.TemplateResponse("admin/jornadas.html", {"request": request, "jornadas": jornadas})


@app.get("/admin/jornadas/{number}")
def admin_jornada_form(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    return templates.TemplateResponse(
        "admin/jornada_form.html",
        {"request": request, "jornada": jornada, "matches": matches, "warnings": [], "messages": []},
    )


@app.post("/admin/jornadas/{number}/resultados")
async def admin_jornada_resultados(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")

    form = await request.form()
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    for m in matches:
        home_raw = (form.get(f"home_{m.id}") or "").strip()
        away_raw = (form.get(f"away_{m.id}") or "").strip()
        m.home_goals = int(home_raw) if home_raw else None
        m.away_goals = int(away_raw) if away_raw else None
    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}", status_code=303)


@app.post("/admin/jornadas/{number}/trampa")
def admin_jornada_trampa(
    number: int, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")
    jornada.is_trap = not jornada.is_trap
    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}", status_code=303)


@app.post("/admin/jornadas/{number}/sync")
async def admin_jornada_sync(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    force = form.get("force") == "1"

    jornada = session.get(Jornada, number)
    if jornada is None:
        jornada = Jornada(number=number)
        session.add(jornada)
        session.flush()

    warnings: list[str] = []
    messages: list[str] = []

    try:
        client = FootballDataClient()
        api_matches = client.get_matches(matchday=number)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"No se pudo consultar football-data.org: {exc}")
        api_matches = []

    mapping = load_team_mapping()
    teams_by_name = {t.name: t for t in session.scalars(select(Team)).all()}
    existing = {
        (m.home_team_id, m.away_team_id): m
        for m in session.scalars(select(Match).where(Match.jornada_number == number)).all()
    }

    created, updated, skipped = 0, 0, 0
    for api_match in api_matches:
        home_name = translate_team_name(api_match.home_team, mapping)
        away_name = translate_team_name(api_match.away_team, mapping)
        if home_name is None or away_name is None:
            warnings.append(
                f"No hay mapeo para '{api_match.home_team}' o '{api_match.away_team}' en team_mapping.json."
            )
            skipped += 1
            continue
        home_team = teams_by_name.get(home_name)
        away_team = teams_by_name.get(away_name)
        if home_team is None or away_team is None:
            warnings.append(f"'{home_name}' o '{away_name}' no está en la lista de equipos de la temporada.")
            skipped += 1
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
            created += 1
        elif has_score:
            already_has_result = match.home_goals is not None or match.away_goals is not None
            if not already_has_result or force:
                match.home_goals = api_match.home_goals
                match.away_goals = api_match.away_goals
                updated += 1

    session.commit()
    messages.append(f"Sincronizado: {created} partidos creados, {updated} resultados actualizados, {skipped} omitidos.")

    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    return templates.TemplateResponse(
        "admin/jornada_form.html",
        {"request": request, "jornada": jornada, "matches": matches, "warnings": warnings, "messages": messages},
    )


# --- Puntos extra ---------------------------------------------------------

@app.get("/admin/puntos-extra")
def admin_puntos_extra(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    entries = session.scalars(select(ExtraPoints)).all()
    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    return templates.TemplateResponse(
        "admin/puntos_extra.html",
        {"request": request, "entries": entries, "participants": participants, "jornadas": jornadas, "errors": []},
    )


@app.post("/admin/puntos-extra/nuevo")
async def admin_puntos_extra_nuevo(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    errors = []
    participant_id = form.get("participant_id")
    jornada_number = form.get("jornada_number")
    points_raw = (form.get("points") or "").strip()
    note = (form.get("note") or "").strip() or None

    participant = session.get(Participant, int(participant_id)) if participant_id else None
    jornada = session.get(Jornada, int(jornada_number)) if jornada_number else None
    if participant is None:
        errors.append("Participante no válido.")
    if jornada is None:
        errors.append("Jornada no válida.")
    try:
        points = int(points_raw)
    except ValueError:
        errors.append("Los puntos deben ser un número entero.")
        points = None

    if not errors:
        session.add(ExtraPoints(participant_id=participant.id, jornada_number=jornada.number, points=points, note=note))
        session.commit()
        return RedirectResponse("/admin/puntos-extra", status_code=303)

    entries = session.scalars(select(ExtraPoints)).all()
    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    return templates.TemplateResponse(
        "admin/puntos_extra.html",
        {"request": request, "entries": entries, "participants": participants, "jornadas": jornadas, "errors": errors},
    )
