"""Reglas de validación portadas de agente_porra/add_participants.py y
update_participants.py, más la traducción de nombres de equipo de
agente_porra/config.py (usada solo al sincronizar con football-data.org;
los formularios de la webapp ya ofrecen los nombres canónicos en un
desplegable, así que no necesitan traducción)."""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
TEAM_MAPPING_PATH = DATA_DIR / "team_mapping.json"


def _normalize(name: str) -> str:
    return name.strip().lower()


def load_team_mapping() -> dict[str, str]:
    """Devuelve {alias_normalizado: nombre_canonico}."""
    data = json.loads(TEAM_MAPPING_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for team in data["teams"]:
        canonical = team["canonical"]
        mapping[_normalize(canonical)] = canonical
        for alias in team["aliases"]:
            mapping[_normalize(alias)] = canonical
    return mapping


def translate_team_name(api_name: str, mapping: dict[str, str]) -> str | None:
    """None si la API devuelve un equipo sin alias conocido (no se adivina)."""
    return mapping.get(_normalize(api_name))


def validate_participant_teams(team_names: list[str], canonical_teams: set[str]) -> list[str]:
    """Reglas comunes a alta y edición: exactamente 8, sin duplicados, todos válidos."""
    errors: list[str] = []
    cleaned = [t.strip() for t in team_names if t and t.strip()]

    if len(cleaned) != 8:
        errors.append(f"Se han recibido {len(cleaned)} equipos, se necesitan exactamente 8.")
        return errors

    if len(set(cleaned)) != 8:
        errors.append("Hay equipos repetidos entre los 8 elegidos.")

    unknown = [t for t in cleaned if t not in canonical_teams]
    if unknown:
        errors.append(
            "Estos equipos no son válidos esta temporada: " + ", ".join(sorted(set(unknown)))
        )

    return errors


def validate_new_participant_name(name: str, existing_names_lower: set[str]) -> list[str]:
    errors: list[str] = []
    name = (name or "").strip()
    if not name:
        errors.append("Falta el nombre.")
    elif name.lower() in existing_names_lower:
        errors.append(f"'{name}' ya está dado de alta.")
    return errors
