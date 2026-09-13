# PROMPT 2 — สร้างแอปมือถือจริง

> **ใช้กับ:** Claude Code / Cursor / Windsurf / Lovable / v0 / Replit Agent
> **ได้ผลลัพธ์:** แอปที่รันได้จริง ดึงข้อมูลจริง แจ้งเตือน push ได้
> **วิธีใช้:** คัดลอกทั้งบล็อกด้านล่างไปวางในเครื่องมือที่เลือก
>
> ทุก API และ URL ในเอกสารนี้ผ่านการทดสอบจริงมาแล้ว ส่วนที่ยังไม่ยืนยันมีระบุไว้ชัดเจน

---

## บล็อกที่ต้องคัดลอก

````
Build a mobile weather app for rain nowcasting, aimed at a civil engineer
supervising a housing-estate construction site in Bang Pakong,
Chachoengsao province, Thailand. All UI text in Thai.

=============================================================
STACK
=============================================================
- React Native with Expo (managed workflow) + TypeScript.
- expo-router for navigation.
- expo-location for GPS.
- expo-notifications for local push notifications.
- expo-task-manager + expo-background-fetch for periodic background checks.
- react-native-maps (or @rnmapbox/maps) for the map screen.
- AsyncStorage for persistence. No backend, no user accounts, no login.
- Font: IBM Plex Sans Thai or Noto Sans Thai via expo-font.

If the target platform is Flutter instead, substitute the equivalent
packages (geolocator, flutter_local_notifications, workmanager,
flutter_map) and keep everything else identical.

=============================================================
DATA SOURCES — ALL FREE, NO API KEY REQUIRED
=============================================================

--- 1. Open-Meteo forecast (PRIMARY data source) ---
Base: https://api.open-meteo.com/v1/forecast
No API key. CORS enabled. Free for non-commercial use.

Single-point request used for the home screen:

  https://api.open-meteo.com/v1/forecast
    ?latitude=13.5233
    &longitude=100.9903
    &current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m
    &hourly=precipitation,precipitation_probability,temperature_2m,wind_gusts_10m
    &daily=precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min
    &timezone=Asia%2FBangkok
    &forecast_days=3

Response shape:
  {
    "current":  { "time": "...", "temperature_2m": 30.1,
                  "relative_humidity_2m": 74, "precipitation": 0,
                  "wind_speed_10m": 11.2 },
    "hourly":   { "time": ["2026-07-25T00:00", ...],
                  "precipitation": [0, 0.2, ...],
                  "precipitation_probability": [10, 35, ...],
                  "temperature_2m": [...], "wind_gusts_10m": [...] },
    "daily":    { "time": [...], "precipitation_sum": [...],
                  "precipitation_probability_max": [...],
                  "temperature_2m_max": [...], "temperature_2m_min": [...] }
  }

Units: precipitation in mm, wind in km/h, temperature in °C.
Timestamps are LOCAL time (because timezone=Asia/Bangkok) with no offset
suffix — parse them as local, do not treat as UTC.

Multi-point request used to build the forecast map. Pass comma-separated
coordinate lists; the response becomes an ARRAY of the object above,
in the same order as the coordinates:

  https://api.open-meteo.com/v1/forecast
    ?latitude=13.82,13.82,13.82,...
    &longitude=100.39,100.54,100.69,...
    &hourly=precipitation
    &timezone=Asia%2FBangkok
    &forecast_days=2

IMPORTANT: when only one coordinate is passed the API returns a single
object, not an array. Normalise with:
  const list = Array.isArray(json) ? json : [json];

Use a 9x9 grid, 0.15 degree spacing (about 16.5 km per cell, covering
roughly 150 km across). Do not poll this endpoint more often than every
15 minutes — it is 81 locations per call and the service is free.

--- 2. Open-Meteo geocoding (place search) ---
  https://geocoding-api.open-meteo.com/v1/search?name=บางปะกง&count=6&language=th&format=json
Returns { results: [ { name, latitude, longitude, admin1, country_code } ] }
Returns no "results" key at all when nothing matches — handle that case.

--- 3. RainViewer radar tiles (live radar overlay) ---
Index: https://api.rainviewer.com/public/weather-maps.json
Returns { host, radar: { past: [ { time, path } ] } }

Tile URL pattern:
  {host}{path}/{size}/{z}/{x}/{y}/{color}/{smooth}_{snow}.png
Example:
  https://tilecache.rainviewer.com/v2/radar/1609401600/256/7/99/59/4/1_1.png

CRITICAL CONSTRAINTS — these caused real bugs, respect them:
  * Maximum supported zoom on the free tier is 7. Requesting a higher
    zoom returns an image containing the words "Zoom Level Not Supported".
    Set maxNativeZoom to 7 on the tile layer and let the map upscale.
  * The free tier provides PAST frames only — there is NO nowcast or
    forecast array, despite what some older tutorials show. Do not build
    a forecast feature on RainViewer.
  * Rate limit around 100 requests per IP per minute.
Use RainViewer only as an optional "what is actually happening right now"
overlay. All forecasting comes from Open-Meteo.

--- 4. Thai Meteorological Department radar images (verified working) ---
Static JPEG/PNG, refreshed roughly every 10-15 minutes. Append a cache-
busting query string. Note the mixed time zones between stations.

  Suvarnabhumi 120km   13.69, 100.75  UTC
    https://weather.tmd.go.th/svp/svp120_latest.jpg
    loop page: https://weather.tmd.go.th/svp120Loop.php

  Nong Chok (Bangkok)  13.86, 100.86  Thai local time
    https://weather.tmd.go.th/pic_bmanck.jpg
    loop page: https://weather.tmd.go.th/bma_ncLoop.php

  Khao Khiao Nakhon Nayok 240km  14.32, 101.28  UTC
    https://weather.tmd.go.th/kkw/kkw240_latest.jpg
    loop page: https://weather.tmd.go.th/kkw240_HQ_Loop_edit2.php

  Sattahip 240km       12.68, 100.98  UTC
    https://weather.tmd.go.th/sat/sat240_latest.png
    loop page: https://weather.tmd.go.th/satLoop.php

Two more stations follow the same folder pattern but were not individually
verified — probe them at runtime and hide the card if the image 404s:
  https://weather.tmd.go.th/ryg/ryg240_latest.jpg   Rayong    12.68, 101.27
  https://weather.tmd.go.th/skm/skm240_latest.jpg   Samut Songkhram 13.41, 100.00

Station coordinates above are approximate, accurate enough for ranking
stations by distance but do not present them as survey-grade.

--- 5. Thai Meteorological Department satellite (Himawari) ---
Served over plain HTTP, not HTTPS. On Android add a network security
config permitting cleartext for this host; on iOS add an ATS exception.
If the platform blocks it, fall back to opening the page in a browser.

  Infrared:      http://www.sattmet.tmd.go.th/satmet/thai/ir/ir_thai.jpg
  Visible:       http://www.sattmet.tmd.go.th/satmet/thai/vis/vis_thai.jpg
  Water vapour:  http://www.sattmet.tmd.go.th/satmet/thai/wv/wv_thai.jpg

--- 6. TMD official warnings ---
  https://tmd.go.th/warning-and-events/warning-storm
This is an HTML page with no public JSON feed. Do not attempt to scrape
it inside the app. Provide a link that opens it in the system browser.

=============================================================
DOMAIN LOGIC — THIS IS THE HEART OF THE APP
=============================================================

Rainfall severity thresholds (mm per hour):
     < 0.1   ไม่มีฝน          green
  0.1 - 0.5  ฝนปรอย           blue, light
  0.5 - 2    ฝนเบา            blue
    2 - 7.5  ฝนปานกลาง        amber
  7.5 - 15   ฝนหนัก           red
    > 15     ฝนหนักมาก         dark red

Wind gust thresholds (km per hour):
    >= 40    ระวังผ้าใบคลุม แผ่นเมทัลชีท วัสดุแผ่นบาง
    >= 50    ควรหยุดงานยกของด้วยเครน/รถเฮี๊ยบ
    >= 60    หยุดงานที่สูงทั้งหมด ตรวจยึดโยงนั่งร้าน

Construction work advice mapped from the 3-hour rainfall total.
Show exactly one line, chosen by the highest severity crossed:
  no rain      "เหมาะกับงานภายนอก งานเทคอนกรีต และงานที่ต้องการผิวแห้ง"
  light        "ยังทำงานได้ แต่ควรเตรียมผ้าใบไว้ใกล้มือ"
  moderate     "หยุดงานสี งานยาแนว งานปูกระเบื้องภายนอก"
  heavy        "หยุดงานเทคอนกรีต งานฉาบ งานดิน คลุมวัสดุ ตรวจทางระบายน้ำ"
  very heavy   "เสี่ยงน้ำท่วมขัง ตรวจ dewatering ตรวจ slope งานขุด"

CONCRETE POUR WINDOW FINDER — the app's signature feature.
Scan the next 24 hourly precipitation values and find every run of
6 or more consecutive hours where precipitation stays below 0.2 mm.
Present each run as "ช่วงเทคอนกรีตได้ HH:MM-HH:MM (N ชม.)".
Rationale to surface in the UI: fresh concrete needs roughly 4-6 hours
of dry weather after placement; rain within the first 2 hours damages
the surface finish.
If no qualifying window exists today, say so plainly rather than showing
an empty list.

RAIN ARRIVAL COUNTDOWN.
Find the first upcoming hour whose precipitation is at or above 0.5 mm.
Report the gap in minutes, rounded to the nearest 10.
Be honest about the resolution limit: the underlying data is hourly, so
label it as an approximation ("ประมาณ") rather than implying
minute-level precision.

NEAREST RADAR STATION.
Compute great-circle distance from the selected site to each station and
sort ascending. Badge the closest one. Also surface this explanation once,
as a dismissible tip, because it changes how the user reads the data:

  "ยิ่งสถานีเรดาร์อยู่ไกล ลำแสงยิ่งยกตัวสูงจากพื้น ที่ระยะ 60 กม.
   ลำแสงอยู่สูงราว 700-900 ม. ฝนก้อนเตี้ยจึงถูกยิงข้ามหัวไป
   เรดาร์ที่ใกล้กว่าจึงเชื่อถือได้มากกว่าเสมอ"

=============================================================
SCREENS
=============================================================

1. หน้าหลัก — verdict hero, rain countdown, four metric tiles,
   24-hour bar chart, concrete pour windows.
2. แผนที่พยากรณ์ — map with a 9x9 coloured forecast grid, 24-hour time
   scrubber with play/pause, optional live radar overlay toggle,
   tap anywhere to move the analysis point.
3. เรดาร์ & ดาวเทียม — TMD station cards sorted by distance with the
   nearest badged; satellite tab with IR, visible, and water vapour,
   each carrying a short plain-Thai note on when it is useful.
4. ตั้งค่าแจ้งเตือน — threshold sliders with live plain-Thai preview,
   lead time, quiet hours, cooldown, per-site toggles.
5. เลือกตำแหน่ง — GPS button, search, saved sites, preset districts,
   manual pin drop.

Preset districts for Chachoengsao (name, lat, lon):
  บางปะกง 13.5233 100.9903 | เมืองฉะเชิงเทรา 13.6904 101.0700
  บ้านโพธิ์ 13.6300 101.0600 | บางน้ำเปรี้ยว 13.8500 101.0000
  บางคล้า 13.7300 101.2100 | คลองเขื่อน 13.8000 101.1800
  ราชสาส์น 13.7800 101.3600 | พนมสารคาม 13.7500 101.3500
  แปลงยาว 13.6300 101.3000 | สนามชัยเขต 13.7200 101.6000
  ท่าตะเกียบ 13.4500 101.6500
Nearby provinces:
  กรุงเทพมหานคร 13.7563 100.5018 | สมุทรปราการ 13.5991 100.5998
  ชลบุรี 13.3611 100.9847 | ศรีราชา 13.1740 100.9300
  พัทยา 12.9236 100.8825 | ระยอง 12.6814 101.2777
  ปราจีนบุรี 14.0500 101.3700 | นครนายก 14.2069 101.2130
(District coordinates are approximate district-centre points.)

=============================================================
BACKGROUND ALERTS
=============================================================
Register a background fetch task running roughly hourly. On each run:
  1. Read the saved site coordinates from storage.
  2. Fetch the single-point Open-Meteo forecast.
  3. Evaluate against the user's configured thresholds over the
     configured lead time.
  4. If a threshold is crossed AND the cooldown has expired AND the
     current time is outside quiet hours, fire a local notification.
  5. Persist the timestamp so cooldown works across app restarts.

Notification copy, in Thai, short enough to read on a lock screen:
  rain     "🌧️ ฝนเข้าบางปะกง ~40 นาที · คาด 3.2 มม./ชม."
  heavy    "⛈️ ฝนหนัก 12 มม./ชม. ช่วง 15:00-16:00 · หยุดงานเทคอนกรีต"
  wind     "💨 ลมกระโชก 55 กม./ชม. · ระวังนั่งร้านและผ้าใบคลุม"
  morning  "☀️ วันนี้โอกาสฝน 40% ช่วงบ่าย · ฝนรวม 5 มม. · ลมสูงสุด 30 กม./ชม."

Also schedule one daily summary notification at a user-configurable time,
defaulting to 06:00.

State clearly in the settings screen that iOS throttles background fetch
and may not honour an exact hourly cadence — promising precise timing
would be misleading.

=============================================================
ENGINEERING REQUIREMENTS
=============================================================
- Cache the last successful response. When offline, render it with a
  visible stale-data banner showing the age. Never let stale data look live.
- Debounce map taps so dragging the pin does not fire many API calls.
- Handle the permission-denied path for location without dead-ending:
  fall back to the saved site or the district picker.
- Timeout every network call at 15 seconds with a retry affordance.
- Round displayed rainfall to one decimal, wind and temperature to whole
  numbers. Never show more precision than the model provides.
- Include an attribution line: ข้อมูลจาก กรมอุตุนิยมวิทยา, Open-Meteo,
  RainViewer. Thai Meteorological Department data is protected under
  the Thai Copyright Act B.E. 2537 — attribution is required and
  commercial use needs permission, so keep this app non-commercial.
- Write unit tests for the threshold logic, the concrete-window finder,
  and the distance calculation. These encode the domain rules and must
  not silently drift.

=============================================================
EXPLICIT NON-GOALS
=============================================================
- No user accounts, no cloud sync, no analytics SDK.
- No scraping of TMD HTML pages.
- No paid API tiers.
- Do not invent a rain-arrival time more precise than the hourly source
  data supports.
````

---

## ลำดับที่แนะนำให้สั่ง AI ทำ

อย่าสั่งสร้างทั้งแอปรวดเดียว จะได้ของที่รันไม่ผ่าน ให้แบ่งเป็น 5 รอบ:

1. **ตั้งโปรเจกต์ + หน้าหลัก** — ดึง Open-Meteo จุดเดียว แสดง verdict + สถิติ + กราฟ
2. **ตรรกะโดเมน + เทส** — thresholds, concrete window finder, distance ให้เขียนเทสด้วย
3. **ระบบเลือกตำแหน่ง** — GPS, ค้นหา, preset, บันทึกลง storage
4. **แผนที่พยากรณ์** — กริด 9×9 + time scrubber (ส่วนที่ยากที่สุด ทำทีหลัง)
5. **แจ้งเตือน background** — ทำท้ายสุด เพราะทดสอบยากที่สุด

หลังแต่ละรอบให้สั่งว่า "รันแล้วแก้ error ให้หมดก่อนไปขั้นต่อไป"

---

## จุดที่ AI มักทำพลาด — บอกดักไว้เลย

| ปัญหา | สั่งเพิ่มว่า |
|---|---|
| ไปเรียก nowcast ของ RainViewer | "RainViewer free tier has no nowcast array — forecasting comes only from Open-Meteo" |
| แผนที่ขึ้น Zoom Level Not Supported | "Set maxNativeZoom to 7 on the RainViewer tile layer" |
| Parse เวลาผิดเป็น UTC | "Open-Meteo returns local timestamps without offset when timezone is set — parse as local" |
| ยิง API ถี่เกิน | "Throttle the 81-point grid request to once per 15 minutes minimum" |
| ภาพดาวเทียมไม่ขึ้นบนมือถือ | "TMD satellite images are HTTP — add cleartext traffic permission for that host" |
| บอกเวลาฝนแม่นเกินจริง | "Never present sub-hourly precision; the source data is hourly" |

---

## หมายเหตุเรื่องความถูกต้องของสเปค

**ยืนยันแล้วจากการทดสอบจริง:** URL เรดาร์ TMD 4 สถานีแรก, URL ภาพดาวเทียมทั้ง 3,
โครงสร้าง response ของ Open-Meteo, ข้อจำกัดซูม 7 และการไม่มี nowcast ของ RainViewer

**ยังไม่ได้ยืนยัน:** URL เรดาร์ระยองกับสมุทรสงคราม (เดาจาก pattern เดียวกัน),
พิกัดสถานีเรดาร์ทั้งหมด (ประมาณการ), พิกัดศูนย์กลางอำเภอ (ประมาณการ)
— ทั้งหมดนี้เขียนกำกับไว้ใน prompt แล้วว่าให้ AI เช็คตอนรันไทม์

**ไม่มีอยู่จริง:** URL ภาพเรดาร์คอมโพสิทกับ QPE แบบตรง ๆ (หน้าเว็บโหลดด้วย JavaScript
อ่าน URL ไม่ได้) จึงไม่ได้ใส่ไว้ใน prompt เลย
