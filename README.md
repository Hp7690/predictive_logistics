# ASTRA-LOG: Predictive Logistics & Forward Supply Chain

Indian Army | SIH 2026 | PS SIH26251 | Team VisionGuard 2.0

One secure command view that forecasts needs, tracks stock, plans routes and mode (road, air, mule) and warns
commanders before stocks run out. Pilot geography: Northern sector (Chandigarh, Jammu and Srinagar depots to Kargil,
Drass, Leh, Padum, Keylong, Diskit, Kaza and Khalsi). Towns, passes and highways are real public geography;
waypoints are approximate; **all stock, troop and consumption numbers are synthetic**.

## What is built (mapped to the presentation)

| Presentation feature | In this prototype |
|---|---|
| Predictive demand forecasting | XGBoost quantile forecast (p10/p50/p90, 14 days) per post and item; MAPE shown in the app |
| Live inventory tracking (IoT / RFID) | Edge-node simulator over MQTT (LoRa / satellite / radio links), stock stored live, RFID tag counts |
| Terrain and weather-aware routing | Risk = 0.4 snow + 0.3 slope + 0.2 visibility on real highway corridors; closed passes removed |
| Route and mode selection (road, air, mule) | Per post: road routes (Route A, B...) with risk and ETA, plus air maintenance and mule options with a recommendation |
| Early shortfall alerts | Days of Supply, alerts with reason, impact and action; dashboard banner |
| Offline-first edge nodes | Cut a node's link: it keeps working from local cache and syncs a batch when the link returns |
| What-if simulation | Close passes, snowfall scenario, demand spike (%), all with before / after |
| SOS override and manual override | SOS button (skips approval, 24 h deadline, air/mule allowed); planner can hold / release any convoy |
| Dispatch, track, retrain | Convoy flow approve, load, transit, deliver; consumption logging feeds the retrain button |
| GIS map of India | Leaflet map with street and terrain layers, routes coloured by risk, passes, weather, moving convoys |
| Role-based access, encryption | JWT, 5 roles, audit log, lockout. Deploy on-premise / air-gapped |
| Impact KPIs | Current vs target chart and live measured KPIs (MAPE, stock-out risk, lead time) |
| IMD weather, ISRO Bhuvan terrain | Weather feed plug-in (Open-Meteo stands in for IMD); terrain is slope factors per route (no DEM yet) |

**Not built yet:** LSTM (forecast is XGBoost only), Kafka (MQTT is used), real IMD / ISRO Bhuvan feeds, real RFID / GPS hardware,
satellite / drone / thermal feeds, offline map tiles. Map tiles load from the internet; without internet the routes,
posts and passes still draw on a blank map.

## Phases

| Phase | What | Status |
|---|---|---|
| A-E | Setup, database, forecast, route risk and OR-Tools planner, JWT / RBAC / WebSocket | Done |
| F | React frontend, army theme, India map, 5 dashboards | Done |
| G | India pilot data, modes, SOS, edge nodes + MQTT, live weather, retrain loop, KPIs | Done (this release) |
| H | Tests, Docker packaging, offline tiles, LSTM, DEM terrain | Next |

## Project layout

```
predictive_logistics/
├── backend/app/    FastAPI: main.py, auth.py, ws.py, mqtt_bridge.py, models.py, seed.py, services/ (alerts, planner, weather_live, mlops)
├── ml/             india.py (geography), generate_data.py, forecast.py
├── optimizer/      risk.py, vrp.py (OR-Tools)
├── iot_sim/        edge_sim.py (edge nodes over MQTT)
├── frontend/       React + Vite + Leaflet (src/pages = one dashboard per role)
├── tools/          ws_listen.py
└── docker-compose.yml   PostGIS + Redis + Mosquitto
```

## Run it (Windows PowerShell, from the `predictive_logistics` folder)

```powershell
copy .env.example .env            # first time; set JWT_SECRET to a long random string
docker compose up -d              # database, redis, mqtt

cd backend
venv\Scripts\activate             # first time: python -m venv venv, then pip install -r requirements.txt,
                                  # ..\ml\requirements_phase_c.txt and ..\optimizer\requirements.txt
python -m app.seed --reset        # builds the India pilot database (wipes old data)
cd ..
python -m ml.forecast             # trains the forecast model (1-2 min)
cd backend
uvicorn app.main:app --reload     # API on http://localhost:8000
```

Second terminal, frontend: `cd frontend`, `npm install` (first time), `npm run dev`, open http://localhost:5173.

Third terminal, optional live IoT stream (venv active, project root): `python -m iot_sim.edge_sim`
(`--chaos` makes random link outages; `--hours 6` makes stock fall faster for demos).

## Demo accounts (change for real use)

`planner/planner123` | `transport/transport123` | `depot/depot123` | `post/post123` | `admin/admin123`

## 5-minute demo

1. `planner`, Command tab: map of Ladakh, Post C (Leh) shows fuel and medical low, alert banner, route options (Route A/B) and mode advice.
2. Planning tab: **Refresh alerts**, **Generate AI plan**, approve the convoy.
3. Close **Zoji La** (what-if): routes switch to the Manali-Leh highway. Close **Baralacha La** too and generate again: posts with no road go by air or mule.
4. Add a demand spike (+50% at P3) and watch days of supply drop.
5. `post`: press SOS. All users see it instantly; the planner's plan treats it as top priority.
6. `transport` (second window): mark the convoy loaded, in transit, delivered; stock at the post rises.
7. Weather and edge nodes tab: cut an edge node's link (offline), restore it (sync). Analytics tab: impact chart, MAPE, **Retrain**.

## How it works

- **Forecast:** one XGBoost model per quantile. Features: season, weekday, expected snowfall, altitude, troop strength, last 7/30 days.
  Last-60-day test: daily MAPE about 6.9%, 14-day total about 4.1%, 80% band covers about 79%.
- **Days of supply:** days until the cumulative p50 forecast uses the stock. Critical under 3 days, warning under 7.
- **Routes:** cost = km x (1 + 3 x risk). ETA assumes a 30 km/h baseline and an 8 h halt after each 10 h of driving.
- **Convoys:** OR-Tools multi-depot VRP with capacity, deadlines (SOS 24 h, critical 72 h, warning 7 days) and priority penalties.
  Posts that roads cannot serve in time go to air maintenance (2500 kg per sortie, needs 3 km visibility) or mule strings (600 kg, 36 h).
- **Edge nodes:** publish `astra/stock/<LOC>` and `astra/heartbeat/<LOC>`; the API subscribes, stores stock and pushes live events.
- **Access:** every endpoint checks the role; posts and depots see only their own area.

## API quick reference (login needed except /health, /login)

`POST /login` | `GET /me` | `GET /dos` | `GET /alerts` | `POST /alerts/refresh` | `GET /forecast/{post}/{item}` | `GET /routes` |
`GET /routes/options/{post}` | `GET /map` | `GET /weather` | `POST /weather/sync` | `GET /edge-nodes` | `POST /edge-nodes/{code}/link` |
`GET /inventory` | `GET /vehicles` | `POST /plan/generate` | `GET /convoys` | `POST /convoy/{code}/status` | `POST /convoy/{code}/override` |
`POST /whatif/pass` | `GET|POST /requests` | `POST /requests/{id}/decision` | `POST /sos` | `POST /consumption` | `POST /inventory/update` |
`GET /kpis` | `GET /ml/status` | `POST /ml/retrain` | `GET /audit` | `GET|POST /users` | `WS /ws`

`demand_pct`, `spike_post` and `snow_cm` query parameters on `/dos`, `/alerts/refresh` and `/plan/generate` run what-if scenarios.

## Troubleshooting

- `docker` not recognised: restart PowerShell; check Docker Desktop shows "Engine running"; add `C:\Program Files\Docker\Docker\resources\bin` to PATH if needed.
- "Virtualization support not detected": enable VT-x / SVM in BIOS, then in Administrator PowerShell run `bcdedit /set hypervisorlaunchtype auto` and `wsl --install`, restart.
- `No module named 'psycopg'`: database URL must start with `postgresql+psycopg2://`.
- After updating from an older version you must run `python -m app.seed --reset` and `python -m ml.forecast` (new places, new data).
- Map is grey: no internet for tiles. Routes and posts still show. Switch layers at the top-right of the map.
- "Pull live weather" says service not reachable: the machine needs internet; synthetic weather is used otherwise.
- Edge nodes show "No data": start `python -m iot_sim.edge_sim` and make sure `docker compose ps` shows `mqtt` running.
- "Session expired": tokens last 30 minutes; log in again.

## Notes

All data is synthetic and for demonstration; locations are public towns and passes, not operational positions.
The login token is kept in the browser's local storage (fine for a prototype). Production needs HTTPS, 2FA / SSO and an
air-gapped on-premise deployment, as in the presentation.
