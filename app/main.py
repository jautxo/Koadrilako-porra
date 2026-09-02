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
from .models import DerbyPrediction, Jornada, Match, Participant, ParticipantTeam, Team
from .queries import build_scoreboard, get_settings
from .scheduler import start_scheduler, stop_scheduler
from .sync import sync_jornada
from .team_badges import team_badge
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


def _liga_default_jornada(by_jornada: dict[int, list[dict]]) -> int:
    numbers = sorted(by_jornada.keys())
    if not numbers:
        return 1
    for n in numbers:
        if any(not m["finished"] for m in by_jornada[n]):
            return n
    return numbers[-1]


def _initials_filter(name: str) -> str:
    words = name.split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return name[:2].upper()


APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR.parent / ".env")

app = FastAPI(title="Kiniela")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["initials"] = _initials_filter
templates.env.globals["team_badge"] = team_badge

init_db()


@app.on_event("startup")
def _on_startup() -> None:
    start_scheduler()


@app.on_event("shutdown")
def _on_shutdown() -> None:
    stop_scheduler()


# --------------------------------------------------------------------------
# Público
# --------------------------------------------------------------------------

@app.get("/")
def leaderboard(request: Request, session: Session = Depends(get_session)):
    board = build_scoreboard(session)
    settings = get_settings(session)
    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request, "active_tab": "porra", "ranking": board.season_leaderboard(),
            "top_highlight_count": settings.top_highlight_count,
            "bottom_highlight_start": settings.bottom_highlight_start,
            "bottom_highlight_end": settings.bottom_highlight_end,
        },
    )


def _jornada_status(jornada: Jornada, matches: list[Match]) -> str:
    """'published' (balidatuta), 'pending' (jokatuta baina balidatzeke) edo
    'not_played' (oraindik jokatu gabe), emaitzen presentzian oinarrituta."""
    if jornada.is_published:
        return "published"
    if matches and all(m.home_goals is not None and m.away_goals is not None for m in matches):
        return "pending"
    return "not_played"


@app.get("/jornadas")
def jornadas_list(request: Request, session: Session = Depends(get_session)):
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    matches = session.scalars(select(Match)).all()
    matches_by_jornada: dict[int, list[Match]] = {}
    for m in matches:
        matches_by_jornada.setdefault(m.jornada_number, []).append(m)

    rows = [
        {"jornada": j, "status": _jornada_status(j, matches_by_jornada.get(j.number, []))}
        for j in jornadas
    ]
    return templates.TemplateResponse(
        "jornadas.html", {"request": request, "active_tab": "jornadas", "rows": rows}
    )


@app.get("/jornada/{number}")
def jornada_detail(number: int, request: Request, session: Session = Depends(get_session)):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")

    matches = session.scalars(
        select(Match).where(Match.jornada_number == number)
    ).all()
    status = _jornada_status(jornada, matches)

    all_numbers = [n for n in session.scalars(select(Jornada.number).order_by(Jornada.number)).all()]
    idx = all_numbers.index(number)

    points_breakdown: list[dict] = []
    derbiak: list[dict] = []
    if jornada.is_published:
        board = build_scoreboard(session)
        points_breakdown = _points_breakdown_from_board(board, number)
        for derby_match in board.derby_matches_by_jornada.get(number, []):
            hits = board.derby_hits_by_match.get(derby_match.id, set())
            derbiak.append({
                "match": derby_match,
                "rows": [
                    {"participant": dp.participant, "home": dp.predicted_home_goals,
                     "away": dp.predicted_away_goals, "hit": dp.participant_id in hits}
                    for dp in board.derby_predictions_by_match.get(derby_match.id, [])
                ],
            })

    settings = get_settings(session)
    return templates.TemplateResponse(
        "jornada.html",
        {
            "request": request,
            "active_tab": "jornadas",
            "jornada": jornada,
            "status": status,
            "matches": matches,
            "points_breakdown": points_breakdown,
            "prev_number": all_numbers[idx - 1] if idx > 0 else None,
            "next_number": all_numbers[idx + 1] if idx < len(all_numbers) - 1 else None,
            "derbiak": derbiak,
            "derby_bonus_points": settings.derby_bonus_points,
            "top_highlight_count": settings.top_highlight_count,
            "bottom_highlight_start": settings.bottom_highlight_start,
            "bottom_highlight_end": settings.bottom_highlight_end,
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
        "liga_clasificacion.html",
        {"request": request, "active_tab": "liga_tabla", "standings": standings, "error": error},
    )


@app.get("/liga/calendario")
def liga_calendario(request: Request, jornada: int | None = None):
    by_jornada: dict[int, list[dict]] = {}
    error = None
    try:
        by_jornada = _liga_matches_por_jornada()
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    number = jornada if jornada is not None else (_liga_default_jornada(by_jornada) if by_jornada else 1)
    number = max(1, min(number, LIGA_ULTIMA_JORNADA))
    return templates.TemplateResponse(
        "liga_calendario.html",
        {
            "request": request,
            "active_tab": "liga_calendario",
            "number": number,
            "matches": by_jornada.get(number, []),
            "prev_number": number - 1 if number > 1 else None,
            "next_number": number + 1 if number < LIGA_ULTIMA_JORNADA else None,
            "error": error,
        },
    )


@app.get("/participante/{participant_id}")
def participante_detail(participant_id: int, request: Request, session: Session = Depends(get_session)):
    participant = session.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Ez da partaidea aurkitu")

    board = build_scoreboard(session)
    cumulative = 0
    rows = []
    for jornada in board.jornadas:
        derby_bonus = board.derby_bonus_by_jornada.get(jornada.number, {}).get(participant.id, 0)
        sign = -1 if jornada.is_trap else 1
        points = sign * board.per_jornada.get(jornada.number, {}).get(participant.id, 0) + derby_bonus
        cumulative += points
        rows.append({
            "number": jornada.number,
            "is_trap": jornada.is_trap,
            "points": points,
            "cumulative": cumulative,
            "derby_hit": derby_bonus > 0,
        })

    return templates.TemplateResponse(
        "participante.html",
        {
            "request": request,
            "active_tab": "porra",
            "participant": participant,
            "jornada_rows": rows,
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
        raise HTTPException(status_code=404, detail="Ez da partaidea aurkitu")
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
        raise HTTPException(status_code=404, detail="Ez da partaidea aurkitu")

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
        errors.append("Taldearen izena falta da.")
    elif name in {t.name for t in teams}:
        errors.append(f"'{name}' dagoeneko zerrendan dago.")
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
        errors.append(f"Ezin izan da football-data.org kontsultatu: {exc}")
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
                "ez du mapaketarik team_mapping.json fitxategian — gehitu eskuz sinkronizatu aurretik."
            )
            continue
        if canonical not in current_names:
            session.add(Team(name=canonical))
            current_names.add(canonical)
            added.append(canonical)

    session.commit()
    if added:
        messages.append("Taldeak gehituta: " + ", ".join(sorted(added)))
    else:
        messages.append("Ez dago talde berririk gehitzeko.")

    teams = session.scalars(select(Team).order_by(Team.name)).all()
    return templates.TemplateResponse(
        "admin/equipos.html", {"request": request, "teams": teams, "errors": errors, "messages": messages}
    )


# --- Jornadas / resultados ----------------------------------------------

@app.get("/admin/jornadas")
def admin_jornadas(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    return templates.TemplateResponse("admin/jornadas.html", {"request": request, "jornadas": jornadas})


def _admin_derbiak(session: Session, number: int) -> list[dict]:
    """Jardunaldi honetako derbi bakoitza (bat baino gehiago egon daitezke),
    bere iragarpen-taularekin, argitaratu gabe egon arren."""
    board = build_scoreboard(session, include_unpublished=True)
    derbiak = []
    for derby_match in board.derby_matches_by_jornada.get(number, []):
        hits = board.derby_hits_by_match.get(derby_match.id, set())
        derbiak.append({
            "match": derby_match,
            "rows": [
                {"participant": dp.participant, "home": dp.predicted_home_goals,
                 "away": dp.predicted_away_goals, "hit": dp.participant_id in hits}
                for dp in board.derby_predictions_by_match.get(derby_match.id, [])
            ],
        })
    return derbiak


def _points_breakdown_from_board(board, number: int) -> list[dict]:
    """Partaide bakoitzak jardunaldi honetan lortuko lituzkeen puntuak,
    partidengatik eta derbiagatik bereizita (tranpa barne)."""
    jornada = next((j for j in board.jornadas if j.number == number), None)
    sign = -1 if (jornada and jornada.is_trap) else 1
    raw_scores = board.per_jornada.get(number, {})
    derby_bonus = board.derby_bonus_by_jornada.get(number, {})

    rows = []
    for p in board.participants:
        match_points = sign * raw_scores.get(p.id, 0)
        derby_points = derby_bonus.get(p.id, 0)
        rows.append({
            "participant": p,
            "match_points": match_points,
            "derby_points": derby_points,
            "total_points": match_points + derby_points,
        })
    return sorted(rows, key=lambda r: r["total_points"], reverse=True)


def _jornada_points_breakdown(session: Session, number: int) -> list[dict]:
    """Argitaratu aurretik administratzaileak ikusi ahal izateko bertsioa:
    argitaratu gabeko jardunaldiak ere kontuan hartzen ditu."""
    board = build_scoreboard(session, include_unpublished=True)
    return _points_breakdown_from_board(board, number)


@app.get("/admin/jornadas/{number}")
def admin_jornada_form(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    return templates.TemplateResponse(
        "admin/jornada_form.html",
        {
            "request": request, "jornada": jornada, "matches": matches, "warnings": [], "messages": [],
            "derby_bonus_points": get_settings(session).derby_bonus_points,
            "derbiak": _admin_derbiak(session, number),
            "points_breakdown": _jornada_points_breakdown(session, number),
        },
    )


@app.post("/admin/jornadas/{number}/resultados")
async def admin_jornada_resultados(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")

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
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")
    jornada.is_trap = not jornada.is_trap
    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}", status_code=303)


@app.post("/admin/jornadas/{number}/argitaratu")
def admin_jornada_argitaratu(
    number: int, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")
    jornada.is_published = not jornada.is_published
    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}", status_code=303)


@app.post("/admin/jornadas/{number}/derbi")
async def admin_jornada_derbi(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")

    form = await request.form()
    selected_ids = {int(v) for v in form.getlist("derby_match_ids")}
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    for m in matches:
        m.is_derby = m.id in selected_ids
    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}", status_code=303)


@app.get("/admin/jornadas/{number}/derbi-iragarpenak")
def admin_derbi_iragarpenak_form(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")
    derby_matches = session.scalars(
        select(Match).where(Match.jornada_number == number, Match.is_derby.is_(True))
    ).all()
    if not derby_matches:
        raise HTTPException(status_code=400, detail="Jardunaldi honek ez du derbirik esleituta")

    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    predictions = {
        (dp.match_id, dp.participant_id): dp
        for dp in session.scalars(
            select(DerbyPrediction).where(DerbyPrediction.jornada_number == number)
        ).all()
    }
    return templates.TemplateResponse(
        "admin/derbi_iragarpenak.html",
        {
            "request": request,
            "jornada": jornada,
            "derby_matches": derby_matches,
            "participants": participants,
            "predictions": predictions,
            "errors": [],
        },
    )


@app.post("/admin/jornadas/{number}/derbi-iragarpenak")
async def admin_derbi_iragarpenak_submit(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")
    derby_matches = session.scalars(
        select(Match).where(Match.jornada_number == number, Match.is_derby.is_(True))
    ).all()
    if not derby_matches:
        raise HTTPException(status_code=400, detail="Jardunaldi honek ez du derbirik esleituta")

    form = await request.form()
    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    existing = {
        (dp.match_id, dp.participant_id): dp
        for dp in session.scalars(
            select(DerbyPrediction).where(DerbyPrediction.jornada_number == number)
        ).all()
    }

    for match in derby_matches:
        for p in participants:
            home_raw = (form.get(f"home_{match.id}_{p.id}") or "").strip()
            away_raw = (form.get(f"away_{match.id}_{p.id}") or "").strip()
            prediction = existing.get((match.id, p.id))
            if not home_raw or not away_raw:
                if prediction is not None:
                    session.delete(prediction)
                continue
            home_goals, away_goals = int(home_raw), int(away_raw)
            if prediction is None:
                session.add(DerbyPrediction(
                    participant_id=p.id, jornada_number=number, match_id=match.id,
                    predicted_home_goals=home_goals, predicted_away_goals=away_goals,
                ))
            else:
                prediction.predicted_home_goals = home_goals
                prediction.predicted_away_goals = away_goals

    session.commit()
    return RedirectResponse(f"/admin/jornadas/{number}/derbi-iragarpenak", status_code=303)


@app.post("/admin/jornadas/{number}/sync")
async def admin_jornada_sync(
    number: int, request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    force = form.get("force") == "1"

    result = sync_jornada(session, number, force=force)
    messages = [
        f"Sinkronizatuta: {result.created} partida sortuta, {result.updated} emaitza eguneratuta, "
        f"{result.skipped} baztertuta."
    ]

    jornada = session.get(Jornada, number)
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    return templates.TemplateResponse(
        "admin/jornada_form.html",
        {
            "request": request, "jornada": jornada, "matches": matches, "warnings": result.warnings,
            "messages": messages,
            "derby_bonus_points": get_settings(session).derby_bonus_points,
            "derbiak": _admin_derbiak(session, number),
            "points_breakdown": _jornada_points_breakdown(session, number),
        },
    )


# --- Konfigurazioa ---------------------------------------------------------

def _derbi_konfigurazioa_context(session: Session) -> dict:
    jornadas = session.scalars(select(Jornada).order_by(Jornada.number)).all()
    matches = session.scalars(select(Match).order_by(Match.jornada_number, Match.id)).all()
    matches_by_jornada: dict[int, list[Match]] = {}
    for m in matches:
        matches_by_jornada.setdefault(m.jornada_number, []).append(m)

    derbi_partidak = [m for m in matches if m.is_derby]
    participants = session.scalars(select(Participant).order_by(Participant.name)).all()
    predictions = {
        (dp.match_id, dp.participant_id): dp
        for dp in session.scalars(select(DerbyPrediction)).all()
    }
    return {
        "jornadas": jornadas,
        "matches_by_jornada": matches_by_jornada,
        "derbi_partidak": derbi_partidak,
        "participants": participants,
        "predictions": predictions,
    }


@app.get("/admin/konfigurazioa")
def admin_konfigurazioa(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    settings = get_settings(session)
    return templates.TemplateResponse(
        "admin/konfigurazioa.html",
        {"request": request, "settings": settings, "errors": [], "messages": [], **_derbi_konfigurazioa_context(session)},
    )


@app.post("/admin/konfigurazioa")
async def admin_konfigurazioa_gorde(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    settings = get_settings(session)
    form = await request.form()
    errors = []
    try:
        settings.derby_bonus_points = int((form.get("derby_bonus_points") or "").strip())
    except ValueError:
        errors.append("Derbiaren puntuek zenbaki oso bat izan behar dute.")

    if not errors:
        session.commit()
        return RedirectResponse("/admin/konfigurazioa", status_code=303)

    session.rollback()
    return templates.TemplateResponse(
        "admin/konfigurazioa.html",
        {"request": request, "settings": settings, "errors": errors, "messages": [], **_derbi_konfigurazioa_context(session)},
    )


@app.get("/admin/taulak")
def admin_taulak(request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)):
    settings = get_settings(session)
    return templates.TemplateResponse(
        "admin/taulak.html", {"request": request, "settings": settings, "errors": []}
    )


@app.post("/admin/taulak")
async def admin_taulak_gorde(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    settings = get_settings(session)
    form = await request.form()
    errors = []
    try:
        settings.top_highlight_count = int((form.get("top_highlight_count") or "0").strip() or "0")
        settings.bottom_highlight_start = int((form.get("bottom_highlight_start") or "0").strip() or "0")
        settings.bottom_highlight_end = int((form.get("bottom_highlight_end") or "0").strip() or "0")
    except ValueError:
        errors.append("Postu-kopuruek zenbaki osoak izan behar dituzte.")

    if not errors:
        session.commit()
        return RedirectResponse("/admin/taulak", status_code=303)

    session.rollback()
    return templates.TemplateResponse(
        "admin/taulak.html", {"request": request, "settings": settings, "errors": errors}
    )


@app.post("/admin/konfigurazioa/derbia")
async def admin_konfigurazioa_derbia(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    number = int(form.get("jornada_number", "0"))
    jornada = session.get(Jornada, number)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Ez da jardunaldia aurkitu")

    selected_ids = {int(v) for v in form.getlist("derby_match_ids")}
    matches = session.scalars(select(Match).where(Match.jornada_number == number)).all()
    for m in matches:
        m.is_derby = m.id in selected_ids
    session.commit()
    return RedirectResponse("/admin/konfigurazioa", status_code=303)


@app.post("/admin/konfigurazioa/derbi-emaitzak")
async def admin_konfigurazioa_derbi_emaitzak(
    request: Request, session: Session = Depends(get_session), _: str = Depends(require_admin)
):
    form = await request.form()
    derby_matches = session.scalars(select(Match).where(Match.is_derby.is_(True))).all()
    participants = session.scalars(select(Participant)).all()
    existing = {
        (dp.match_id, dp.participant_id): dp
        for dp in session.scalars(select(DerbyPrediction)).all()
    }

    for match in derby_matches:
        for p in participants:
            key = (match.id, p.id)
            home_raw = (form.get(f"home_{match.id}_{p.id}") or "").strip()
            away_raw = (form.get(f"away_{match.id}_{p.id}") or "").strip()
            prediction = existing.get(key)
            if not home_raw or not away_raw:
                if prediction is not None:
                    session.delete(prediction)
                continue
            home_goals, away_goals = int(home_raw), int(away_raw)
            if prediction is None:
                session.add(DerbyPrediction(
                    participant_id=p.id, jornada_number=match.jornada_number, match_id=match.id,
                    predicted_home_goals=home_goals, predicted_away_goals=away_goals,
                ))
            else:
                prediction.predicted_home_goals = home_goals
                prediction.predicted_away_goals = away_goals

    session.commit()
    return RedirectResponse("/admin/konfigurazioa", status_code=303)
