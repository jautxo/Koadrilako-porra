"""Migración de un solo uso: copia todos los datos del porra.db local
(SQLite) a una base de datos PostgreSQL (p. ej. Neon, para desplegar en
Render). No modifica porra.db.

Uso:
    python migrate_sqlite_to_postgres.py "postgresql://usuario:contraseña@host/basededatos"

La URL de destino es la misma que le darás a Render como DATABASE_URL.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    AppSettings,
    Base,
    DerbyPrediction,
    Jornada,
    Match,
    Participant,
    ParticipantTeam,
    Team,
)

# Orden importante: cada tabla se copia después de las que referencia
# mediante clave foránea.
MODELS_IN_ORDER = [Team, Participant, ParticipantTeam, Jornada, Match, DerbyPrediction, AppSettings]

# Columnas enteras autoincrementales cuya secuencia hay que recolocar en
# Postgres tras insertar filas con id explícito (si no, el próximo INSERT
# de la app en producción chocaría con un id ya usado).
SEQUENCES_TO_RESET = [
    ("teams", "id"),
    ("participants", "id"),
    ("participant_teams", "id"),
    ("matches", "id"),
    ("derby_predictions", "id"),
]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    target_url = sys.argv[1]

    sqlite_path = Path(__file__).resolve().parent / "porra.db"
    if not sqlite_path.exists():
        print(f"Ez da aurkitu {sqlite_path}")
        sys.exit(1)

    source_engine = create_engine(f"sqlite:///{sqlite_path}")
    target_engine = create_engine(target_url)

    print("Sortzen Postgres-eko taulak...")
    Base.metadata.create_all(target_engine)

    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)
    source = SourceSession()
    target = TargetSession()

    for model in MODELS_IN_ORDER:
        rows = source.scalars(select(model)).all()
        print(f"{model.__tablename__}: {len(rows)} lerro kopiatzen...")
        for row in rows:
            target.merge(row)
        target.commit()

    print("Sekuentziak berrezartzen...")
    with target_engine.begin() as conn:
        for table, column in SEQUENCES_TO_RESET:
            conn.exec_driver_sql(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                f"COALESCE((SELECT MAX({column}) FROM {table}), 1))"
            )

    source.close()
    target.close()
    print("Migrazioa amaituta.")


if __name__ == "__main__":
    main()
