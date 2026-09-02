"""Insignia visual (iniciales + color) para un equipo, a partir de
cualquier variante de su nombre (canónico de la porra o nombre completo
tal cual lo devuelve football-data.org). Reutiliza team_mapping.json
para resolver alias -> canónico antes de buscar en la paleta."""
from __future__ import annotations

from .validation import load_team_mapping, translate_team_name

_BADGES: dict[str, tuple[str, str]] = {
    "R. Madrid": ("RMA", "#1a2b4c"),
    "Barcelona": ("FCB", "#a50044"),
    "Betis": ("BET", "#0b7a3b"),
    "Atlético": ("ATM", "#cb3524"),
    "Athletic": ("ATH", "#7a1f1f"),
    "Villareal": ("VIL", "#ffe667"),
    "Celta": ("CEL", "#2f8fc0"),
    "Real Sociedad": ("RSO", "#14508c"),
    "Valencia": ("VAL", "#f5a623"),
    "Mallorca": ("MAL", "#c8102e"),
    "Osasuna": ("OSA", "#ab1519"),
    "Rayo": ("RAY", "#d31145"),
    "Getafe": ("GET", "#1f5fa8"),
    "Sevilla": ("SEV", "#b7202e"),
    "Espanyol": ("ESP", "#2f6fae"),
    "Alavés": ("ALA", "#0f6b6b"),
    "Girona": ("GIR", "#d2091c"),
    "Levante": ("LEV", "#7a1f3d"),
    "Elche": ("ELX", "#0e8f6f"),
    "Oviedo": ("OVI", "#1e3a8a"),
    "Deportivo": ("DEP", "#0a3f91"),
    "Racing": ("RAC", "#2f8f4e"),
    "Málaga": ("MLG", "#1670b8"),
}

_DARK_TEXT_BACKGROUNDS = {"#ffe667"}
_FALLBACK_PALETTE = ["#1a2b4c", "#a50044", "#0b7a3b", "#cb3524", "#2f8fc0", "#1f5fa8", "#7a1f3d"]
_SKIP_WORDS = {"cf", "fc", "cd", "rc", "rcd", "ud", "ca", "real", "club", "de", "la", "atlético", "deportivo"}


def team_badge(name: str) -> dict:
    canonical = translate_team_name(name, load_team_mapping()) or name
    initials, color = _BADGES.get(canonical) or (_fallback_initials(canonical), _fallback_color(canonical))
    text_color = "#1a2b4c" if color in _DARK_TEXT_BACKGROUNDS else "#ffffff"
    return {"initials": initials, "color": color, "text_color": text_color}


def _fallback_initials(name: str) -> str:
    words = [w for w in name.split() if w.lower().strip(".") not in _SKIP_WORDS]
    letters = "".join(w[0] for w in words[:3]).upper()
    return (letters or name[:3].upper())[:3]


def _fallback_color(name: str) -> str:
    return _FALLBACK_PALETTE[sum(ord(c) for c in name) % len(_FALLBACK_PALETTE)]
