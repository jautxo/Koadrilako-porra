import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

PROJECT_DIR = Path(__file__).resolve().parent.parent

# Render/Neon-en bezalako hodeietan DATABASE_URL ingurune-aldagaia dago
# (PostgreSQL). Hori ez badago, garapenerako SQLite fitxategi lokala erabili.
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    # Zenbait hornitzailek "postgres://" itzultzen dute, baina SQLAlchemy-k
    # "postgresql://" behar du psycopg2 driver-arekin erabiltzeko.
    if _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    # Render (15 min inaktibitatearen ondoren lo egiten du) eta Neon bezalako
    # zerbitzari gabeko Postgres-ek konexio inaktiboak isilean ixten dituzte;
    # pool_pre_ping-ek konexio zahar bat berrerabili aurretik egiaztatzen du,
    # bestela hurrengo eskaerak "server closed the connection" errorea emango luke.
    engine = create_engine(_database_url, pool_pre_ping=True, pool_recycle=300)
else:
    DB_PATH = os.environ.get("DATABASE_PATH", str(PROJECT_DIR / "porra.db"))
    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """create_all crea tablas nuevas pero no columnas nuevas en tablas ya
    existentes: añade aquí a mano las que se han ido incorporando.

    Migrazio hau SQLite-rako idatzita dago (PRAGMA eta abar), datu-base
    zaharrak eguneratzeko. PostgreSQL-en (Render/Neon) beti hasten gara base
    hutsetik, eta create_all()-ek jada eguneratutako eskema sortzen du, beraz
    ez dago zertan exekutatu."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jornadas)")}
        if "is_published" not in cols:
            conn.exec_driver_sql("ALTER TABLE jornadas ADD COLUMN is_published INTEGER DEFAULT 0")
            # Jardunaldi zaharrak jadanik publikoki ikusgai zeuden: ez ezkutatu
            # migrazio honekin, hemendik aurrera sortuko diren berriek bakarrik
            # beharko dute administratzailearen berrespena.
            conn.exec_driver_sql("UPDATE jornadas SET is_published = 1")

        # Eskema zaharrean jardunaldi bakoitzak derbi bakarra izan zezakeen
        # (jornadas.derby_match_id). Orain edozein partida marka daiteke
        # derbi gisa (matches.is_derby), jardunaldi bakoitzak bat baino
        # gehiago izan ditzan.
        matches_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(matches)")}
        if "is_derby" not in matches_cols:
            conn.exec_driver_sql("ALTER TABLE matches ADD COLUMN is_derby INTEGER DEFAULT 0")
            if "derby_match_id" in cols:
                conn.exec_driver_sql(
                    "UPDATE matches SET is_derby = 1 "
                    "WHERE id IN (SELECT derby_match_id FROM jornadas WHERE derby_match_id IS NOT NULL)"
                )

        dp_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(derby_predictions)")}
        if "match_id" not in dp_cols:
            # (participant_id, jornada_number) bakarra onartzen zuen; orain
            # (participant_id, match_id) behar da derbi bat baino gehiago
            # egon daitezkeelako jardunaldi berean. SQLite-k ez du UNIQUE
            # murrizketak zuzenean aldatzen uzten: taula berrsortu behar da.
            conn.exec_driver_sql("ALTER TABLE derby_predictions RENAME TO derby_predictions_old")
            conn.exec_driver_sql(
                """
                CREATE TABLE derby_predictions (
                    id INTEGER PRIMARY KEY,
                    participant_id INTEGER NOT NULL REFERENCES participants(id),
                    jornada_number INTEGER NOT NULL REFERENCES jornadas(number),
                    match_id INTEGER NOT NULL REFERENCES matches(id),
                    predicted_home_goals INTEGER NOT NULL,
                    predicted_away_goals INTEGER NOT NULL,
                    UNIQUE(participant_id, match_id)
                )
                """
            )
            if "derby_match_id" in cols:
                conn.exec_driver_sql(
                    """
                    INSERT INTO derby_predictions
                        (id, participant_id, jornada_number, match_id, predicted_home_goals, predicted_away_goals)
                    SELECT dp.id, dp.participant_id, dp.jornada_number,
                           (SELECT j.derby_match_id FROM jornadas j WHERE j.number = dp.jornada_number),
                           dp.predicted_home_goals, dp.predicted_away_goals
                    FROM derby_predictions_old dp
                    WHERE (SELECT j.derby_match_id FROM jornadas j WHERE j.number = dp.jornada_number) IS NOT NULL
                    """
                )
            conn.exec_driver_sql("DROP TABLE derby_predictions_old")

        settings_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(app_settings)")}
        if "top_highlight_count" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN top_highlight_count INTEGER DEFAULT 3")
        if "bottom_highlight_start" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN bottom_highlight_start INTEGER DEFAULT 0")
        if "bottom_highlight_end" not in settings_cols:
            conn.exec_driver_sql("ALTER TABLE app_settings ADD COLUMN bottom_highlight_end INTEGER DEFAULT 0")


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
