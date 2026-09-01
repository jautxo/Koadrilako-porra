"""Cliente mínimo de la API de football-data.org (v4), portado de
agente_porra/football_api.py. Misma lógica; la única diferencia es que la
API key se lee de la variable de entorno FOOTBALL_DATA_API_KEY en vez de
config.json, porque aquí no hay Excel ni fichero de config local."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

BASE_URL = "https://api.football-data.org/v4"


@dataclass
class ApiMatch:
    matchday: int
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    status: str
    utc_date: str

    @property
    def finished(self) -> bool:
        return self.status == "FINISHED"


class FootballDataClient:
    def __init__(self, api_key: str | None = None, competition_code: str = "PD"):
        api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY")
        if not api_key:
            raise ValueError(
                "Falta la variable de entorno FOOTBALL_DATA_API_KEY "
                "(consigue una API key gratis en https://www.football-data.org/client/register)."
            )
        self.competition_code = competition_code
        self._session = requests.Session()
        self._session.headers.update({"X-Auth-Token": api_key})

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{BASE_URL}{path}"
        for _ in range(3):
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"No se pudo completar la petición a {url} tras varios reintentos")

    def get_teams(self) -> list[dict]:
        data = self._get(f"/competitions/{self.competition_code}/teams")
        return [
            {"name": t["name"], "shortName": t.get("shortName", ""), "tla": t.get("tla", "")}
            for t in data.get("teams", [])
        ]

    def get_matches(self, matchday: int | None = None) -> list[ApiMatch]:
        params = {}
        if matchday is not None:
            params["matchday"] = matchday
        data = self._get(f"/competitions/{self.competition_code}/matches", params=params)
        matches = []
        for m in data.get("matches", []):
            score = m.get("score", {}).get("fullTime", {})
            matches.append(
                ApiMatch(
                    matchday=m["matchday"],
                    home_team=m["homeTeam"]["name"],
                    away_team=m["awayTeam"]["name"],
                    home_goals=score.get("home"),
                    away_goals=score.get("away"),
                    status=m["status"],
                    utc_date=m["utcDate"],
                )
            )
        return matches
