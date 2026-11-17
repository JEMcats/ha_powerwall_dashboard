# Powerwall Dashboard Integration for Home Assistant
Allows you to connect to a PyPowerwall proxy and an InfluxDB instance to get metrics and control your Tesla Powerwall System.

***Warning, the large majority of the project was written by AI!***

## Requirements
- A stable instance of ```influxdb```, ```telegraf```, and ```pypowerwall```.
- A stable instance of Home Assistant (I have only tested it on HA Core 2026.10.2 in a docker container).
- A LAN connection between the two instances or on the same host.

## Limitations
- Real time data will be up to 20 seconds behind live
- All historical data will be 1-2 minutes behind live
- Powerwall Control will only work if you setup PyPowerwall with ```v1r``` mode or ```cloud``` mode!

## Entities
All entities are grouped under one **Powerwall** device. String sensors only exist when **Show strings** is enabled, and the control entities only exist when **Allow controls** is enabled. The voltage, temperature, fan, capacity, charge and deviation sensors are in the device's **Diagnostic** section. Every entity refreshes at the **Polling interval** you set (default 10 seconds), and a change you make from Home Assistant shows immediately.

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
| **Firmware** | Update, always | `/api/system/update/status` | Installed version, for example `26.34.3 f2e0e391`. Up to date for `/update_succeeded`, `/update_failed`, `/clear_update_status`, `/update_unknown` and any unrecognized state. Update available for `/download`, `/update_staged` and `/update_downloaded`. In progress during `/download` or an offline update. Attributes include the raw state, last status time and offline-update fields. | Read-only, no install button. The endpoint doesn't report the target version, so "latest version" reads "Update available". The state list comes from community docs. |
| **Load voltage**, **Grid voltage**, **Battery voltage**, **Solar voltage** | Sensor (diagnostic), always | `/api/meters/aggregates` → `load`, `site` (the grid meter), `battery`, `solar` → `instant_average_voltage` | V, voltage device class, 1 decimal. Read from the same request as the power sensors, so there is no extra call. | Unknown if the gateway doesn't report a voltage for that meter. Unavailable together with the other live sensors if `aggregates` fails. |
| **PW1 temperature**, **PW2 temperature**, … | Sensor (diagnostic), one per Powerwall that has a temperature | `/temps/pw` → `PW<n>_temp` | Native °C, shown in the **Temperature unit** you pick in the options (Celsius, Fahrenheit or Kelvin). 1 decimal. | PW1 is the leader and PW2, PW3, … are followers, using pypowerwall's numbering. Sensors appear as Powerwalls are discovered, with no reload. A Powerwall with no reading shows unknown. Changing the unit option overrides any unit you set by hand on these sensors the next time the integration loads. |
| **PW1 fan speed**, **PW2 fan speed**, … | Sensor (diagnostic), one per Powerwall that reports fan data | `/fans/pw` → `FAN<n>_actual` | rpm. The state is the average of that Powerwall's two fans; the attributes list each fan's rpm and duty %. | Powerwall 3 only: a Powerwall 2 has no fan data, so it gets no fan sensor. Assumes two fans per Powerwall, numbered in Powerwall order (PW1 owns FAN1–2, PW2 owns FAN3–4). |
| **PW1 total capacity**, **PW2 total capacity**, … | Sensor (diagnostic), one per Powerwall | `/pod` → `PW<n>_POD_nom_full_pack_energy` (Wh) | kWh, energy storage class, 2 decimals. Attributes: model, device name and the spec capacity it is compared to. | A missing or zero reading shows unknown. The Powerwalls are discovered from `/pod`. |
| **PW1 current charge**, **PW2 current charge**, … | Sensor (diagnostic), one per Powerwall | `/pod` → `PW<n>_POD_nom_energy_remaining` (Wh) | kWh, energy storage class, 2 decimals. | Same as above. |
| **PW1 capacity deviation**, **PW2 capacity deviation**, … | Sensor (diagnostic), one per Powerwall | Calculated: total capacity compared with the published capacity | %, from `(capacity − spec) / spec × 100`. Negative means below spec. Attributes: spec kWh and the difference in kWh. | The spec is hard-coded by part number from Tesla's datasheets: 13.5 kWh for Powerwall 2 (`1092170`, `2012170`, `3012170`), Powerwall 3 (`1707000`) and Powerwall 3 Expansion (`1807000`), and also 13.5 kWh for any unknown part. The gateway's "nominal full pack energy" can read above the published usable capacity (a Powerwall 3 in pypowerwall's discussions reports 14.42 kWh), so a healthy unit can show a positive deviation. The trend matters more than the absolute number. Edit `POWERWALL_MODELS` in `const.py` to change the baseline. |
| **Combined total capacity**, **Combined current charge**, **Combined capacity deviation** | Sensor (diagnostic), once at least one Powerwall reports pod data | Sums of the per-Powerwall values | kWh, kWh, and % against the summed spec. | Only Powerwalls that report a capacity are included, and the spec is summed over those same units so the comparison stays fair. |
| **Grid connection** | Switch, only with **Allow controls** | Read `/api/system_status/grid_status` (the same data as the **Grid status** sensor). Write `POST /control/islanding`, JSON body with token in the `Authorization` header. | ON means connected to the grid (`SystemGridConnected`), OFF means islanded (`SystemIslandedActive`), and it is unknown while the gateway transitions back to the grid or reports any other status. Off sends `{"value":"off_grid","confirm":true}`, on sends `{"value":"on_grid"}`. | Off islands your house. The server locks islanding for 1 minute after any request. It's v1r-only, needs a registered RSA key and pypowerwall 0.17.3 or later, and has no cloud fallback. Some firmware may acknowledge without actuating, so verify grid status. Errors (409, 429, 502, 503) are shown. The state is read at your polling interval, like the Grid status sensor. |
| **Backup reserve** | Number, only with controls | Read `/pw/get_reserve`. Write `POST /control/reserve`, form-encoded. | 0–100 %, step 1, slider. | Fractional values round to a whole number. Needs your pypowerwall server's control write path to be working. |
| **Max backup** | Switch, only with controls | Read `/control/max_backup` → `manual_backup.active`. Write `POST /control/max_backup`. | On starts a backup that ends at the **Max backup until** date and time, sent to the gateway as the number of seconds from now. Off sends `value=cancel`. | v1r-only. The server minimum is 60 seconds. The server caches the read for 30 seconds, so after you switch it on or off the new state is held for 32 seconds to stop a cached read flipping it back. Turning it on with no end time set, an end time in the past, or one less than 60 seconds away fails with an error rather than quietly lasting longer than you chose. |
| **Max backup until** | Date and time, only with controls | Local to Home Assistant (nothing to read back) | The date and time the next max backup should end. Starts empty. Remembered across restarts, unless that time has already passed. Nothing is sent until **Max backup** is switched on. | Changing it does not alter a backup that is already running, and it doesn't reflect a backup started from the Tesla app. The **Start Max Backup** action doesn't use it. Existing installs: the old **Max backup duration** number is removed automatically. |
| **Max backup ends** | Sensor (timestamp), only with controls | `/control/max_backup` → `manual_backup.end_time` | A real timestamp, not a countdown. Only shows while a backup is active, otherwise unknown. Estimated immediately after you switch it on, then confirmed by the next read. | Blank when inactive, so a stale past time is never shown. |
| **Storm Watch active** | Binary sensor, only with controls | `/control/max_backup` → `backup_events` | On when `backup_events` is anything other than `[]`, off otherwise. | Independent of manual max backup: a manual backup can be active while this stays off. Unknown if the endpoint is unreadable. |
| **Operating mode** | Select, only with controls | Read `/pw/get_mode`. Write `POST /control/mode`. | Options: Self-Powered (`self_consumption`), Time-Based Control (`autonomous`), Backup-Only (`backup`). | Automations pass the raw value. An unrecognized gateway mode shows as unknown. |
| **Grid charging** | Switch, only with controls | Read `/control/grid_charging`. Write `POST /control/grid_charging`. | On sends `value=true`, off sends `value=false`. | No special limits. |
| **Grid export** | Select, only with controls | Read `/control/grid_export`. Write `POST /control/grid_export`. | Options: Solar and Battery (`battery_ok`), Solar Only (`pv_only`), Off (`never`). | An unrecognized value shows as unknown. |

## Actions
These actions only exist while at least one instance has **Allow controls** enabled. They are removed again when no instance does. Both are available as `powerwall_dashboard.<action>` and appear in Developer Tools → Actions and in the automation editor.

| Action | Fields | What it does | Rules and limitations |
|---|---|---|---|
| **Start Max Backup**<br>`powerwall_dashboard.start_max_backup` | `duration` (required): whole seconds, 60–4294967295.<br>`config_entry_id` (optional): which instance to use. | Starts a manual max backup lasting `duration`, by posting `value=<seconds>` to `/control/max_backup`. The **Max backup** switch and **Max backup ends** sensor update immediately, then are confirmed by the next read. | The server minimum is 60 seconds, and a `duration` outside the allowed range is rejected before anything is sent. v1r-only. Unlike the **Max backup** switch, which works from the **Max backup until** date and time, the action takes a plain number of seconds and does not use or change that entity. `config_entry_id` can be left out when exactly one instance has controls enabled; with several, leaving it out is an error. |
| **Stop Max Backup**<br>`powerwall_dashboard.stop_max_backup` | `config_entry_id` (optional): which instance to use. | Cancels the current max backup, by posting `value=cancel` to `/control/max_backup`. The **Max backup** switch turns off immediately, then is confirmed by the next read. | The cancel is always sent, even if Home Assistant doesn't think a backup is running: its view can be up to 30 seconds old, and a backup started from the Tesla app wouldn't show yet. If the gateway refuses it (for example nothing is running, or the server isn't in v1r mode), the action fails and shows the gateway's reason. Same instance rules as above. |

Example:
```yaml
action: powerwall_dashboard.start_max_backup
data:
  duration: 3600
```

## Setup
1. Download the integration through HACS/Marketplace:
Add the repository ```https://github.com/JEMcats/ha_powerwall_dashboard.git``` and download the Powerwall-Dashboard through Marketplace/HACS.
2. Add the integration in your Home Assistant Settings:
[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerwall_dashboard)
3. Configure the integration during setup. (Do not enable control if you are not connected with v1r or cloud)

## Important Notice
If you are getting instablility in your pypowerwall setup, reduce your polling interval as it may be the cause of the problem!