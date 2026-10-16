# ASTRA-LOG: Predictive Logistics & Forward Supply Chain

Indian Army | SIH 2026 | PS SIH26251 | Team VisionGuard 2.0 2k26


One secure command view that forecasts needs, tracks stock, plans routes and transport mode (road, drone, mule, air) and warns
commanders before stocks run out. Pilot geography: Northern sector (Chandigarh, Jammu and Srinagar depots to Kargil, Drass, Leh,
Padum, Keylong, Diskit, Kaza and Khalsi). Towns, passes and highways are real public geography; waypoints are approximate;
**all stock, troop and consumption numbers are synthetic**.

## What is built (mapped to the presentation, v10)

| Presentation feature | In this prototype |
|---|---|
| Demand forecasting: LSTM + XGBoost | XGBoost quantile models plus a NumPy LSTM, blended (weight picked on a held-out test). p10 / p50 / p90 for 14 days |
| Slow-moving items: Croston / SBA, scored by MASE | Vehicle spares (lumpy demand) use Croston with SBA correction; every item is scored with MAPE and MASE in the app |
| Live stock, RFID (GS1) and edge validation | Edge nodes over MQTT; readings are validated at the edge (negative, invalid or implausible jumps rejected and counted); GS1 GTIN-14 item catalog; RFID tag field on stock entry |
| Offline-first | Cut a node's link: it buffers locally and syncs a batch when the link returns. The assistant below also works with no internet |
| Inventory balancing: surplus to shortfalls | Surplus above 21 days is offered to posts predicted to run short, nearest first; non-moving stock (over 90 days) flagged |
| Priority ranking of scarce items | Importance x troops depending on the post / days left |
| Terrain and weather-aware routing | Risk = 0.4 snow + 0.3 slope + 0.2 visibility on real highway corridors; Route A, B, C lettering; closed passes removed |
| Mode-aware plans: road, drone, robotic mule, air | Cheapest feasible mode within the deadline (road 1, mule 1.6, drone 3, air 8). Urgent light items go by drone, bulk by mule or air |
| Advance winter stocking and snow-closure what-if | Winter tab: need from Dec to Mar history vs stock, tonnes to pre-position, what the road fleet can move before closure, "passes close N days early" |
| What-if simulation | Close passes, snowfall, demand spike, one-click HADR surge, all with before / after |
| SOS override, commander approval, manual override | SOS skips approval (24 h); planner approves, rejects, holds, releases |
| Natural-language query, offline | "Ask ASTRA" understands English and Hinglish ("Post C ka fuel agle 7 din ka") with rules and fuzzy matching, no outside model |
| Fleet GPS and last known position | Transport reports position; GPS lost keeps the last known position (LoRa fallback); maintenance risk per vehicle |
| Plugs into Q-FORCE / ERP by API | API-key REST / JSON / CSV endpoints: read forecast, stock, alerts, convoys; ERP can push stock. No vendor-specific adapter is claimed |
| Dashboard: alert banner, gauges, Zoom Chandigarh to Leh | All present. Alerts read like "Fuel (POL) shortfall forecast at Post C (Leh) in 50 hours. Dispatch 1 truck via Route A" |
| GIS map of India | Leaflet map: street and terrain layers, routes coloured by risk, passes, weather, moving convoys |
| Retrain from actuals | Posts and depots log consumption; Retrain button |
| Impact KPIs | Current vs target chart plus measured MAPE, MASE, stock-out risk, lead time, non-moving %, load utilisation |

**Not built yet:** Kafka (MQTT is used), real IMD / ISRO Bhuvan feeds (Open-Meteo stands in; terrain is slope factors), real RFID / GPS
hardware, drone telemetry (drone is a planning mode), satellite / thermal feeds, offline map tiles, Prophet. Map tiles need internet;
without it routes, posts and passes still draw on a blank map.

## Forecast scores (last 60 days, synthetic data)

Daily MAPE 7.1% for the ensemble (XGBoost alone 7.3%, LSTM alone 7.5%, naive 30-day average 8.9%); MASE 0.95 vs 1.14 naive;
14-day totals about 4.4%; 80% band covers about 78%. Vehicle spares (lumpy demand) are close to the naive baseline (MASE 0.87 vs 0.86):
Croston is the right method but the demand is mostly random, and the app says so.

## Project layout

```
predictive_logistics/
├── backend/app/    FastAPI: main.py, auth.py, ws.py, mqtt_bridge.py, models.py, seed.py,
│                   services/ (alerts, planner, nlp, weather_live, mlops)
├── ml/             india.py (geography, catalog), generate_data.py, forecast.py, lstm.py
├── optimizer/      risk.py, vrp.py (OR-Tools)
├── iot_sim/        edge_sim.py (edge nodes over MQTT)
├── frontend/       React + Vite + Leaflet (src/pages = one dashboard per role)
├── tools/          ws_listen.py
└── docker-compose.yml   PostGIS + Redis + Mosquitto
```

## Run it (Windows PowerShell, from the `predictive_logistics` folder)

```powershell
docker compose up -d              # database, redis, mqtt (Docker Desktop must be running)

cd backend
venv\Scripts\activate
python -m app.seed --reset        # builds the India pilot database (wipes old data)
cd ..
python -m ml.forecast             # trains XGBoost + LSTM + Croston (2-4 min)
cd backend
uvicorn app.main:app --reload     # API on http://localhost:8000
```

Frontend (second terminal): `cd frontend`, `npm install` (first time), `npm run dev`, open http://localhost:5173.
Live IoT stream (third terminal, venv active, project root): `python -m iot_sim.edge_sim` (`--chaos` link outages, `--noise` bad readings to show validation, `--hours 6` faster stock fall).

`.env` needs `DATABASE_URL`, `JWT_SECRET`; set `INTEGRATION_API_KEY` to switch the Q-FORCE / ERP API on.

## Demo accounts (change for real use)

`planner/planner123` | `transport/transport123` | `depot/depot123` | `post/post123` | `admin/admin123`

## 6-minute demo

1. `planner`, Command: Ladakh map, "Zoom: Chandigarh to Leh", Post C (Leh) gauges, alert banner, Route A/B and mode table.
2. Ask ASTRA: "Post C ka fuel agle 7 din ka" and "which posts are critical".
3. Planning: Refresh alerts, Generate AI plan, approve. Close Zoji La, then Baralacha La, generate again: urgent items by drone, bulk by air.
4. Inventory & balancing: transfers from surplus posts to shortfalls, non-moving stock, priority ranking.
5. Winter stocking: tonnes to pre-position and "passes close 20 days early".
6. `post`: SOS. `transport`: mark loaded, in transit, report GPS, then "GPS lost".
7. Weather and edge nodes: cut a link, restore it; run the simulator with `--noise` to see rejected readings. Analytics: MASE, Croston, KPIs, Retrain.

## API quick reference (login needed except /health, /login; integration uses X-API-Key)

`POST /login` | `GET /dos` | `GET /alerts` | `POST /alerts/refresh` | `GET /forecast/{post}/{item}` | `GET /routes/options/{post}` | `GET /map` |
`POST /plan/generate` | `GET /convoys` | `POST /convoy/{code}/status|override|position` | `POST /whatif/pass` | `GET /balancing` | `GET /priority` |
`GET /winter` | `POST /ask` | `POST /sos` | `GET|POST /requests` | `POST /consumption` | `POST /inventory/update` | `GET /edge-nodes` | `GET /kpis` |
`GET /ml/status` | `POST /ml/retrain` | `GET /catalog` | `GET /audit` | `GET|POST /users` | `WS /ws` |
`GET /integration/v1/ping|forecast|dos|convoys|stock|stock.csv` | `POST /integration/v1/stock`

## Troubleshooting

- `docker` not recognised: restart PowerShell; Docker Desktop must show "Engine running"; PC restarts stop it, so start it first.
- `Connection refused ... 5432`: containers are not running; `docker compose up -d`, wait 15 s.
- `value too long for type character varying`: update `backend/app/models.py` (route names need a longer column), then seed again.
- After updating from an older version run `python -m app.seed --reset` and `python -m ml.forecast`.
- Map is grey: no internet for tiles; routes and posts still show.
- Edge nodes show "No data": start `python -m iot_sim.edge_sim` and check `docker compose ps` shows `mqtt`.
- "Session expired": tokens last 30 minutes; log in again.

## Notes

All data is synthetic and for demonstration; locations are public towns and passes, not operational positions. The login token is kept in
the browser's local storage (fine for a prototype). Production needs HTTPS, 2FA / SSO and an air-gapped on-premise deployment.
