"""Emaitzen sinkronizazio automatikoa: futbol-jokoak jokatzen diren egunetan
(ostiral-astelehen) 2 orduro egiaztatzen du emaitzarik gabeko partidarik
dagoen eta, egonez gero, football-data.org-etik eguneratzen ditu."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .db import SessionLocal
from .football_api import FootballDataClient
from .models import Match
from .sync import sync_jornada

logger = logging.getLogger("porra.scheduler")
MADRID_TZ = ZoneInfo("Europe/Madrid")

scheduler = BackgroundScheduler(timezone=MADRID_TZ)


def _pending_jornada_numbers(session) -> list[int]:
    numbers = session.scalars(
        select(Match.jornada_number)
        .where((Match.home_goals.is_(None)) | (Match.away_goals.is_(None)))
        .distinct()
    ).all()
    return sorted(numbers)


def sync_pending_results() -> None:
    session = SessionLocal()
    try:
        pending_numbers = _pending_jornada_numbers(session)
        if not pending_numbers:
            return

        # football-data.org-en doako maila 10 eskaera/minutura mugatuta dago:
        # jardunaldi pendiente bakoitzeko eskaera bat egin beharrean (10-20
        # eskaera exekuzio bakoitzeko izan litezke), behin bakarrik eskatu
        # partida guztiak eta gero banatu jardunaldika.
        try:
            all_api_matches = FootballDataClient().get_matches()
        except Exception:
            logger.exception("Auto-sync: ezin izan da football-data.org kontsultatu")
            return

        matches_by_jornada: dict[int, list] = {}
        for m in all_api_matches:
            matches_by_jornada.setdefault(m.matchday, []).append(m)

        for number in pending_numbers:
            try:
                result = sync_jornada(session, number, api_matches=matches_by_jornada.get(number, []))
                logger.info(
                    "Auto-sync jornada %s: %d sortuta, %d eguneratuta, %d baztertuta",
                    number, result.created, result.updated, result.skipped,
                )
                for warning in result.warnings:
                    logger.warning("Auto-sync jornada %s: %s", number, warning)
            except Exception:
                logger.exception("Auto-sync failed for jornada %s", number)
    finally:
        session.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        sync_pending_results,
        trigger=CronTrigger(day_of_week="fri,sat,sun,mon", hour="*/2", timezone=MADRID_TZ),
        id="sync_pending_results",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
