# La Porra — webapp

Reimplementación independiente de la porra de fútbol (antes gestionada en
`../agente_porra/` sobre un Excel vía automatización COM). Backend FastAPI +
SQLite, sin dependencia de Excel ni de Windows.

Ver `PLAN.md` para el contexto y las decisiones de diseño.

## Puesta en marcha (local)

1. Crear y activar un entorno virtual dentro de esta carpeta:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```
3. Copiar `.env.example` como `.env` y rellenar `ADMIN_PASSWORD` (y
   `FOOTBALL_DATA_API_KEY` si vas a usar los botones de sincronización).
4. Migrar los datos actuales del Excel (solo lectura, no lo modifica):
   ```
   python migrate_from_excel.py
   ```
   Esto crea `porra.db` con equipos, participantes, calendario, resultados y
   jornadas trampa de la temporada actual.
5. Arrancar el servidor:
   ```
   uvicorn app.main:app --reload
   ```
6. Abrir `http://localhost:8000` (clasificación pública) y
   `http://localhost:8000/admin` (pide usuario/contraseña de `.env`).

## Verificación tras migrar

Compara el total de 2-3 participantes en `http://localhost:8000/participante/<id>`
contra el total que muestra `KinielaSaikapena` en el Excel — deben coincidir
exactamente.

## Estructura

- `app/models.py` — tablas SQLAlchemy (equipos, participantes, sus 8 elecciones,
  jornadas, partidos, puntos extra). No se guardan puntos calculados: se
  recalculan siempre a partir de los partidos y las elecciones.
- `app/scoring.py` — regla de puntuación pura (fácil de testear).
- `app/queries.py` — construye las clasificaciones (general y por jornada,
  con el efecto de las jornadas trampa) a partir de la base de datos.
- `app/validation.py` — reglas de alta/edición de participantes y traducción
  de nombres de equipo de la API, portadas de `agente_porra/`.
- `app/football_api.py` — cliente de football-data.org, portado de
  `agente_porra/football_api.py`.
- `app/main.py` — rutas FastAPI, públicas y de administración
  (`/admin/*`, protegidas con usuario/contraseña).
- `migrate_from_excel.py` — script de un solo uso para la migración inicial.

## Pendiente de decidir más adelante

- Hosting definitivo (ver `PLAN.md`): si la plataforma elegida no ofrece disco
  persistente para `porra.db`, habrá que pasar a una base de datos gestionada
  (Postgres) sin cambiar el resto del código, gracias a que el acceso a datos
  está aislado en `app/db.py` y `app/models.py`.
