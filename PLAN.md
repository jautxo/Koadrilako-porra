# Webapp de la porra — plan y notas (en pausa)

Estado: solo pensado, sin código todavía. Este documento resume lo hablado para retomarlo otro día.

## Objetivo

Convertir la porra actual (Excel `../Liga BBVA 2026-2027 Apertura.xlsm`, gestionado hoy por los scripts de `../agente_porra/` vía automatización COM de Excel) en una webapp independiente.

**Por qué:** `agente_porra` depende de pywin32 + Excel instalado en Windows con el fichero cerrado. Eso no sirve para una web real con varios usuarios accediendo a la vez desde fuera.

## Decisiones ya tomadas

- **No se aloja en el propio ordenador.** Necesita hosting externo, no depender de que el PC esté encendido ni de abrir puertos en casa.
- **Hosting recomendado:** un PaaS gratuito/barato tipo Render o Railway. Te dan una URL (`algo.onrender.com`) sin gestionar servidores.
- **Enfoque técnico recomendado:** desacoplarse del Excel por completo.
  - Migrar los datos (equipos, participantes, calendario, resultados, y las fórmulas de puntuación de `PartiduenEmaitzak`) a una base de datos ligera.
  - Si se quiere que los datos sobrevivan a reinicios/redeploys sin líos, mejor ir directo a un Postgres gestionado (gratuito en Render/Railway) en vez de un SQLite en disco efímero.
  - Reimplementar la lógica en un backend pequeño (ej. FastAPI/Flask) + frontend sencillo.
  - **El grueso del trabajo real:** portar a código las fórmulas de puntuación que hoy viven en el Excel.

## Pasos para preparar el hosting (cuando se retome)

1. **Repositorio Git** — el proyecto tiene que estar en GitHub, porque Render/Railway despliegan directamente desde ahí. Esta carpeta (`webapp_porra/`) todavía no es un repo git.
2. **Estructura desplegable** — `requirements.txt`, comando de arranque (ej. `uvicorn app:app`), variables de entorno para secretos (API key de football-data.org, credenciales de la BD) — nunca hardcodeadas en el código ni subidas al repo.
3. **Cuenta en Render o Railway**, conectada al repo de GitHub.
4. **Configurar el servicio**: build command, start command, variables de entorno, base de datos (Postgres gratuito recomendado).
5. **Dominio**: URL gratuita del propio hosting; dominio propio es opcional y para más adelante.

## Cómo crear el repositorio Git (paso a paso)

1. Instalar Git: [git-scm.com](https://git-scm.com/)
2. Crear cuenta en [GitHub](https://github.com) si no se tiene.
3. Crear un repositorio vacío en GitHub (botón "New repository", sin inicializar con README).
4. Desde una terminal, dentro de `webapp_porra/`:
   ```
   git init
   git add .
   git commit -m "Primer commit"
   git branch -M main
   git remote add origin https://github.com/tu-usuario/porra-webapp.git
   git push -u origin main
   ```
5. A partir de ahí, para guardar avances:
   ```
   git add .
   git commit -m "Descripción del cambio"
   git push
   ```

**Alternativa sin terminal:** [GitHub Desktop](https://desktop.github.com/) — interfaz gráfica con botones ("Commit", "Push") en vez de comandos.

## Próximos pasos posibles (sin decidir todavía)

- Crear el repositorio git de verdad.
- Definir el modelo de datos (equipos, participantes, calendario, resultados, puntos).
- Revisar el Excel para identificar exactamente las fórmulas de `PartiduenEmaitzak` que hay que portar.
- Elegir stack concreto de backend/frontend.
