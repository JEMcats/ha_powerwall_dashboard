# Powerwall Dashboard Integration for Home Assistant
Allows you to connect to a PyPowerwall proxy and an InfluxDB instance to get metrics and control your Tesla Powerwall System.

***Warning, the large majority of the project was written completely by AI!***

## Requirements
- A stable instance of ```influxdb```, ```telegraf```, and ```pypowerwall```.
- A stable instance of Home Assistant (I have only tested it on HA Core 2026.10.2 in a docker container).
- A LAN connection between the two instances or on the same host.

## Limitations
- Real time data will be up to 20 seconds behind live
- All historical data will be 1-2 minutes behind live
- Powerwall Control will only work if you setup PyPowerwall with ```v1r``` mode or ```cloud``` mode!

## Entities
All entities are grouped under one **Powerwall** device. String sensors only exist when **Show strings** is enabled, and the control entities only exist when **Allow controls** is enabled.

| Entity | Platform and when it exists | Source | Value and rules | Limitations |
|---|---|---|---|---|
| **Solar power** | Sensor, always | pypowerwall `/api/meters/aggregates` → `solar` | kW, from `instant_power / 1000`. Power device class, shows 2 decimals. | If `aggregates` fails, every pypowerwall sensor goes unavailable. |
| **Battery power** | Sensor, always | same → `battery` | kW, sign exactly as the gateway reports it (not inverted). | Same as above. |
| **Grid power** | Sensor, always | same → `site` (the grid meter) | kW, sign as reported. | Same as above. |
| **Load power** | Sensor, always | same → `load` | kW. | Same as above. |
| **Percentage charged** | Sensor, always | `/api/system_status/soe` | %, battery device class (icon follows the level), 1 decimal. | Optional endpoint: if only it fails, this sensor is unknown while the others keep working. |
| **Grid status** | Sensor (enum), always | `/api/system_status/grid_status` | States: `connected` (SystemGridConnected), `disconnected` (SystemIslandedActive), `transitioning` (SystemTransitionToGrid). Shown as Connected / Disconnected / Transitioning. | Any other gateway value shows as unknown. Optional endpoint. |
| **Estimated time remaining** | Sensor, always | `/pw/get_time_remaining` → `{"time_remaining": hours}` | Hours, duration device class, 2 decimals. | `null` or a failed request shows as unknown. Cloud and FleetAPI modes report `0.0` when they don't know, so 0 can mean unknown. |
| **Battery charged** | Sensor, always | InfluxDB, integral of `to_pw` | kWh today. Energy class, `total_increasing`. | Resets at local midnight in your configured timezone. All six energy sensors share one query. If InfluxDB fails, all six go unavailable. |
| **Battery discharged** | Sensor, always | InfluxDB, `from_pw` | kWh today. | Same as above. |
| **Grid exported** | Sensor, always | InfluxDB, `to_grid` | kWh today. | Same as above. |
| **Grid imported** | Sensor, always | InfluxDB, `from_grid` | kWh today. | Same as above. |
| **Home usage** | Sensor, always | InfluxDB, `home` | kWh today. | Same as above. |
| **Solar generated** | Sensor, always | InfluxDB, `solar` | kWh today. | Same as above. No data yet today (just after midnight) reports 0. |
| **String A–F power** | Sensor, only when **Show strings** is on | pypowerwall `/strings` | One sensor per string, in W, rounded to 2 decimals. Attributes: state, voltage, current, connected. Names come from the response keys, falling back to A–F if unreadable at startup. | `/strings` is only requested while the option is on. Switching it off removes the sensors from the registry. Setups that don't serve `/strings` give unknown values. |
| **Firmware** | Update, always | `/api/system/update/status` | Installed version, for example `26.34.3 f2e0e391`. Up to date for `/update_succeeded`, `/update_failed`, `/clear_update_status`, `/update_unknown` and any unrecognized state. Update available for `/download`, `/update_staged` and `/update_downloaded`. In progress during `/download` or an offline update. Attributes include the raw state, last status time and offline-update fields. | Read-only, no install button. The endpoint doesn't report the target version, so "latest version" reads "Update available". Polled every 5 minutes. The state list comes from community docs. |
| **Grid connection** | Switch, only with **Allow controls** | Read `/pw/is_connected`. Write `POST /control/islanding`, JSON body with token in the `Authorization` header. | ON means connected to the grid. Off sends `{"value":"off_grid","confirm":true}`, on sends `{"value":"on_grid"}`. | Off islands your house. The server locks islanding for 1 minute after any request. It's v1r-only, needs a registered RSA key and pypowerwall 0.17.3 or later, and has no cloud fallback. Some firmware may acknowledge without actuating, so verify grid status. Errors (409, 429, 502, 503) are shown. |
| **Backup reserve** | Number, only with controls | Read `/pw/get_reserve`. Write `POST /control/reserve`, form-encoded. | 0–100 %, step 1, slider. | Fractional values round to a whole number. Needs your pypowerwall server's control write path to be working. |
| **Max backup** | Switch, only with controls | Read `/control/max_backup` → `manual_backup.active`. Write `POST /control/max_backup`. | On starts a backup lasting the **Max backup duration**, sent as seconds. Off sends `value=cancel`. | v1r-only. The server minimum is 60 seconds. The server caches the read for 30 seconds. |
| **Max backup duration** | Number, only with controls | Local to Home Assistant (nothing to read back) | Minutes, 1–10080 (7 days), default 60. Remembered across restarts. Nothing is sent until Max backup is switched on. | Doesn't reflect a backup started from the Tesla app. The 7-day cap is set by this integration; the server allows far longer. |
| **Max backup ends** | Sensor (timestamp), only with controls | `/control/max_backup` → `manual_backup.end_time` | A real timestamp, not a countdown. Only shows while a backup is active, otherwise unknown. Estimated immediately after you switch it on, then confirmed by the next read. | Blank when inactive, so a stale past time is never shown. |
| **Storm Watch active** | Binary sensor, only with controls | `/control/max_backup` → `backup_events` | On when `backup_events` is anything other than `[]`, off otherwise. | Independent of manual max backup: a manual backup can be active while this stays off. Unknown if the endpoint is unreadable. |
| **Operating mode** | Select, only with controls | Read `/pw/get_mode`. Write `POST /control/mode`. | Options: Self-Powered (`self_consumption`), Time-Based Control (`autonomous`), Backup-Only (`backup`). | Automations pass the raw value. An unrecognized gateway mode shows as unknown. |
| **Grid charging** | Switch, only with controls | Read `/control/grid_charging`. Write `POST /control/grid_charging`. | On sends `value=true`, off sends `value=false`. | No special limits. |
| **Grid export** | Select, only with controls | Read `/control/grid_export`. Write `POST /control/grid_export`. | Options: Solar and Battery (`battery_ok`), Solar Only (`pv_only`), Off (`never`). | An unrecognized value shows as unknown. |

## Setup
1. Download the integration through HACS/Marketplace:
Add the repository ```https://github.com/JEMcats/ha_powerwall_dashboard.git``` and download the Powerwall-Dashboard through Marketplace/HACS.
2. Add the integration in your Home Assistant Settings:
[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerwall_dashboard)
3. Configure the integration during setup. (Do not enable control if you are not connected with v1r or cloud)