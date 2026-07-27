#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 rain_alert_telegram.py  —  ระบบเตือนฝน 24 ชม. บางปะกง ฉะเชิงเทรา
=====================================================================
 ดึงข้อมูล : Open-Meteo (พยากรณ์รายชั่วโมง, ฟรี ไม่ต้องใช้ API key)
             RainViewer  (เรดาร์ nowcast ทั่วโลก, ฟรี ไม่ต้องใช้ key)
             TMD         (ประกาศเตือนภัยกรมอุตุนิยมวิทยา)
 ส่งเข้า    : Telegram Bot

 วิธีใช้ครั้งแรก:
   1) pip install requests
   2) สร้าง Telegram Bot -> คุยกับ @BotFather ในแอป Telegram
      พิมพ์ /newbot  แล้วตั้งชื่อ  จะได้ TOKEN หน้าตาแบบ 1234567:AAE...
   3) ทักบอทตัวเองในแอป Telegram 1 ครั้ง (พิมพ์อะไรก็ได้)
   4) เปิด https://api.telegram.org/bot<TOKEN>/getUpdates ในเบราว์เซอร์
      หาเลข "chat":{"id": XXXXXXX}  นั่นคือ CHAT_ID
   5) ใส่ TOKEN กับ CHAT_ID ในช่อง CONFIG ด้านล่าง
   6) ทดสอบ:  python rain_alert_telegram.py --test
   7) ตั้งให้รันอัตโนมัติทุกชั่วโมงด้วย Windows Task Scheduler
      (ดูวิธีในไฟล์คู่มือที่แนบมาด้วยกัน)

 แหล่งข้อมูล: กรมอุตุนิยมวิทยา / Open-Meteo / RainViewer
=====================================================================
"""

import os
import sys
import json
import math
import time
import argparse
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("ยังไม่ได้ติดตั้ง requests — รันคำสั่ง:  pip install requests")
    sys.exit(1)


# =====================================================================
#  CONFIG — แก้ตรงนี้
# =====================================================================
#
#  รันบนคอมตัวเอง  → แก้ค่าในบรรทัดข้างล่างนี้ได้เลย
#  รันบน GitHub Actions → ไม่ต้องแก้ ให้ไปใส่ใน Settings > Secrets แทน
#                         (สคริปต์จะอ่านจาก environment variable ก่อนเสมอ)
#  ห้าม commit TOKEN จริงขึ้น GitHub เด็ดขาด ใครเห็นก็ยิงข้อความในนามบอทคุณได้
# =====================================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN","ใส่_TOKEN_ของบอทตรงนี้")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "ใส่_CHAT_ID_ตรงนี้")

# พิกัดบ้าน/ไซต์งาน (บางปะกง ฉะเชิงเทรา)
LAT = float(os.environ.get("WX_LAT", 13.53))
LON = float(os.environ.get("WX_LON", 100.99))
PLACE_NAME = os.environ.get("WX_PLACE", "บางปะกง")

# --- เกณฑ์แจ้งเตือน (ปรับได้ตามความรู้สึกว่าถี่/ห่างไป) ---
RAIN_MM_ALERT = 1.0        # ฝน มม./ชม. ที่ถือว่าเริ่มต้องเตือน
                           # (เดิม 0.5 = ฝนปรอย ทำให้เตือนผิดบ่อย)
RAIN_MM_HEAVY = 7.5        # ฝน มม./ชม. ที่ถือว่าฝนหนัก
RAIN_MM_VERY_HEAVY = 15.0  # ฝน มม./ชม. ที่ถือว่าฝนหนักมาก
PROB_ALERT = 70            # โอกาสฝน % — ใช้เป็นเงื่อนไข "ร่วม" กับปริมาณฝน
                           # ไม่ใช่เงื่อนไขเดี่ยวอีกต่อไป
GUST_ALERT = 40            # ลมกระโชก กม./ชม. ที่ต้องเตือน (งานนั่งร้าน/เครน)
GUST_DANGER = 60           # ลมกระโชก กม./ชม. ที่อันตรายชัดเจน
LOOKAHEAD_HOURS = 3        # มองล่วงหน้ากี่ชั่วโมง

# --- เกณฑ์ความเสี่ยงเพิ่มเติม ---
CAPE_ALERT = 2500          # J/kg — เกินนี้ถือว่าเสี่ยงพายุรุนแรง
HEAT_ALERT = 41            # °C อุณหภูมิที่รู้สึกได้ — เกินนี้เสี่ยงเพลียแดด
TIDE_CLASH_MM = 7.5        # ฝน มม./ชม. ที่ถือว่าหนักพอจะเตือนเมื่อตรงกับน้ำขึ้น

# เรดาร์ nowcast: รัศมีที่ถือว่า "ฝนใกล้ตัว" (กม.)
RADAR_RADIUS_KM = 25

# ส่งข้อความ "ปกติดี" ด้วยไหม (False = ส่งเฉพาะตอนมีฝน/ลม/ประกาศเตือนภัย)
SEND_WHEN_CLEAR = False

# --- กันการเตือนพร่ำเพรื่อ ---
COOLDOWN_MINUTES = 120     # ห้ามเตือนซ้ำภายในกี่นาที (ใช้ร่วมกันทุกประเภท)
                           # ยกเว้นกรณีที่ความรุนแรงเพิ่มขึ้นจากครั้งก่อน

# ช่วงเวลาที่ไม่อยากถูกปลุก — เตือนเฉพาะเรื่องรุนแรงจริงเท่านั้น
QUIET_START = 22           # เริ่มเวลา 22:00
QUIET_END = 5              # ถึง 05:00
QUIET_MIN_RANK = 5         # ระดับความรุนแรงขั้นต่ำที่จะปลุกได้ (ดูตาราง SEVERITY_RANK)

# ใช้เรดาร์ยับยั้งการเตือนฝนเบา — ถ้าโมเดลบอกว่ามีฝนใน 1 ชม.
# แต่เรดาร์ไม่เห็นอะไรเลยในรัศมี 25 กม. แปลว่าโมเดลน่าจะเกลี่ยฝนผิดที่
RADAR_VETO = True

STATE_FILE = "rain_alert_state.json"
ALERT_LOG = "alert_log.csv"   # บันทึกทุกการเตือน ไว้ตรวจย้อนหลังว่าแม่นแค่ไหน


# ระดับความรุนแรง — ใช้ตัดสินว่าจะเตือนซ้ำหรือปลุกกลางดึกไหม
SEVERITY_RANK = {
    "clear": 0, "heat": 2, "gust": 3, "rain": 3, "radar_now": 4,
    "heavy": 5, "storm": 5, "very_heavy": 6, "tide": 6, "warning": 7,
}


# =====================================================================
#  ฟังก์ชันช่วยเหลือ
# =====================================================================

def now_th():
    """
    เวลาปัจจุบันโซนไทย (UTC+7)

    สำคัญ: GitHub Actions รันบนเครื่องที่ตั้งเป็น UTC ถ้าใช้ datetime.now()
    เฉย ๆ เวลาจะเพี้ยนไป 7 ชั่วโมง ทำให้จับคู่กับข้อมูลพยากรณ์ผิดชั่วโมง
    จึงคำนวณจาก UTC บวก 7 เสมอ ไม่พึ่งนาฬิกาของเครื่อง
    """
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)


def send_telegram(text: str) -> bool:
    """ส่งข้อความเข้า Telegram"""
    if "ใส่_" in TELEGRAM_TOKEN or "ใส่_" in TELEGRAM_CHAT_ID:
        print("!! ยังไม่ได้ตั้งค่า TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        print("--- ข้อความที่จะส่ง ---")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        if r.status_code == 200:
            print("ส่ง Telegram สำเร็จ")
            return True
        print(f"ส่ง Telegram ไม่สำเร็จ: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        print(f"ส่ง Telegram ผิดพลาด: {e}")
        return False


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"บันทึก state ไม่ได้: {e}")


def in_cooldown(state: dict, severity: str) -> bool:
    """
    เช็คว่าควรงดเตือนหรือไม่

    ใช้ cooldown ตัวเดียวร่วมกันทุกประเภท (เดิมแยกตามประเภท ทำให้คืนเดียว
    ได้ทั้งเตือนฝน เตือนลม เตือนพายุ เตือนความร้อน = 4 ข้อความ)

    ข้อยกเว้น: ถ้าความรุนแรงเพิ่มขึ้นจากครั้งก่อน จะเตือนได้ทันที
    เช่น เตือน "มีฝน" ไปแล้ว พอกลายเป็น "ฝนหนัก" ต้องเตือนซ้ำ
    """
    ts = state.get("last_alert_at")
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return False

    if (now_th() - last) >= timedelta(minutes=COOLDOWN_MINUTES):
        return False

    prev_rank = state.get("last_rank", 0)
    now_rank = SEVERITY_RANK.get(severity, 0)
    return now_rank <= prev_rank        # รุนแรงขึ้นเท่านั้นจึงผ่าน


def in_quiet_hours() -> bool:
    """อยู่ในช่วงเวลาที่ไม่อยากถูกปลุกหรือไม่"""
    h = now_th().hour
    if QUIET_START <= QUIET_END:
        return QUIET_START <= h < QUIET_END
    return h >= QUIET_START or h < QUIET_END      # ข้ามเที่ยงคืน


def log_alert(severity, forecast, radar, sent):
    """
    บันทึกทุกครั้งที่ระบบ "คิดจะเตือน" ลงไฟล์ CSV
    ไว้ย้อนดูภายหลังว่าที่เตือนไปนั้นฝนตกจริงกี่ครั้ง
    ช่องสุดท้าย rain_actual เว้นไว้ให้กรอกเองว่าตกจริงไหม (Y/N)
    """
    try:
        import csv, os as _os
        new = not _os.path.exists(ALERT_LOG)
        mx = max((f["rain_mm"] for f in forecast), default=0) if forecast else 0
        mp = max((f["prob"] for f in forecast), default=0) if forecast else 0
        rd = ""
        if radar and radar.get("rain_detected"):
            rd = "yes" if radar["rain_detected"].get("now") else "no"
        with open(ALERT_LOG, "a", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)",
                            "โอกาสฝน(%)", "เรดาร์เห็นฝน", "ส่งจริง",
                            "ฝนตกจริง(กรอกเอง Y/N)"])
            w.writerow([f"{now_th():%Y-%m-%d %H:%M}", severity,
                        f"{mx:.1f}", f"{mp:.0f}", rd,
                        "yes" if sent else "no", ""])
    except Exception as e:
        print(f"  บันทึก log ไม่ได้: {e}")


# =====================================================================
#  1) พยากรณ์รายชั่วโมง — Open-Meteo
# =====================================================================

def fetch_forecast():
    """
    ดึงพยากรณ์รายชั่วโมงจาก Open-Meteo
    คืนค่า list ของ dict: [{time, rain_mm, prob, temp, gust}, ...]
    เฉพาะชั่วโมงข้างหน้าตาม LOOKAHEAD_HOURS
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": ("precipitation,precipitation_probability,temperature_2m,"
                   "wind_gusts_10m,cape,apparent_temperature"),
        "timezone": "Asia/Bangkok",
        "forecast_days": 2,
    }
    try:
        r = requests.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ดึง Open-Meteo ไม่ได้: {e}")
        return None

    h = data.get("hourly", {})
    times = h.get("time", [])
    rains = h.get("precipitation", [])
    probs = h.get("precipitation_probability", [])
    temps = h.get("temperature_2m", [])
    gusts = h.get("wind_gusts_10m", [])
    capes = h.get("cape", [])
    heats = h.get("apparent_temperature", [])

    now = now_th()
    out = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        # เอาเฉพาะชั่วโมงตั้งแต่ตอนนี้ไปข้างหน้า
        delta_h = (dt - now).total_seconds() / 3600
        if -1 <= delta_h <= LOOKAHEAD_HOURS:
            out.append({
                "time": dt,
                "rain_mm": rains[i] if i < len(rains) and rains[i] is not None else 0.0,
                "prob": probs[i] if i < len(probs) and probs[i] is not None else 0,
                "temp": temps[i] if i < len(temps) and temps[i] is not None else None,
                "gust": gusts[i] if i < len(gusts) and gusts[i] is not None else 0,
                "cape": capes[i] if i < len(capes) and capes[i] is not None else None,
                "heat": heats[i] if i < len(heats) and heats[i] is not None else None,
            })
    return out


# =====================================================================
#  2) เรดาร์ nowcast — RainViewer (ฟรี ไม่ต้องใช้ key)
# =====================================================================

def latlon_to_tile(lat, lon, zoom):
    """แปลงพิกัดเป็นเลข tile ของแผนที่ (Web Mercator)"""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def fetch_radar_nowcast():
    """
    ดึงข้อมูลเรดาร์ nowcast จาก RainViewer
    คืนค่า dict: {has_now: bool, has_soon: bool, frames_ahead: int, url: str}
    หมายเหตุ: RainViewer ให้ทั้งเฟรมอดีตและเฟรมพยากรณ์ล่วงหน้า (nowcast)
    ตรงนี้เราแค่เช็คว่ามีเฟรม nowcast อยู่ไหม แล้วส่งลิงก์ให้ดูเอง
    การอ่านค่าฝนจากภาพ tile ต้องใช้ Pillow — ทำเป็น optional ด้านล่าง
    """
    try:
        r = requests.get("https://api.rainviewer.com/public/weather-maps.json", timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ดึง RainViewer ไม่ได้: {e}")
        return None

    radar = data.get("radar", {})
    nowcast = radar.get("nowcast", []) or []
    past = radar.get("past", []) or []
    host = data.get("host", "https://tilecache.rainviewer.com")

    latest = past[-1] if past else None
    result = {
        "nowcast_frames": len(nowcast),
        "latest_path": latest.get("path") if latest else None,
        "host": host,
        "map_url": f"https://www.rainviewer.com/map.html?loc={LAT},{LON},9",
    }

    # ถ้าติดตั้ง Pillow ไว้ จะอ่านค่าฝนจากภาพ tile ตรงพิกัดได้
    result["rain_detected"] = check_radar_pixel(result, nowcast, past)
    return result


def latlon_to_tile_exact(lat, lon, zoom):
    """
    แปลงพิกัดเป็นตำแหน่ง tile แบบทศนิยม
    คืน (tile_x, tile_y, frac_x, frac_y) โดย frac คือตำแหน่งภายใน tile (0.0-1.0)
    ต้องใช้ค่าทศนิยม ไม่งั้นจะอ่านพิกเซลผิดตำแหน่ง — ของเดิมอ่านกลาง tile
    ซึ่งห่างจากจุดจริงได้ถึง 150 กม.
    """
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    fx = (lon + 180.0) / 360.0 * n
    fy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return int(fx), int(fy), fx - int(fx), fy - int(fy)


def check_radar_pixel(radar_info, nowcast, past):
    """
    อ่านภาพ tile เรดาร์ตรงพิกัดบ้าน แล้วดูว่ามีสีฝนหรือไม่
    ต้องมี Pillow (pip install pillow) — ถ้าไม่มีจะข้ามไป คืนค่า None
    คืนค่า: {"now": bool, "in_30min": bool} หรือ None

    หมายเหตุสำคัญ 2 ข้อ (แก้จากเวอร์ชันแรกที่ผิด):
      1) RainViewer ชั้นฟรีรองรับ tile ถึงระดับซูม 7 เท่านั้น
         ถ้าขอซูมสูงกว่านี้ เซิร์ฟเวอร์จะส่งภาพที่มีข้อความ
         "Zoom Level Not Supported" กลับมา ซึ่งมีพิกเซลทึบเต็มภาพ
         ทำให้ตรวจว่า "มีฝน" ทั้งที่ไม่มี — เป็น false positive ร้ายแรง
      2) ต้องคำนวณตำแหน่งพิกเซลจริงภายใน tile ไม่ใช่ดูกลาง tile
         เพราะที่ซูม 7 หนึ่ง tile กว้างราว 300 กม.
    """
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return None

    ZOOM = 7                      # ค่าสูงสุดที่ชั้นฟรีรองรับ ห้ามเกิน
    TILE_PX = 256
    x, y, fx, fy = latlon_to_tile_exact(LAT, LON, ZOOM)
    host = radar_info["host"]

    # ขนาดจริงของ tile บนพื้นโลก ณ ละติจูดนี้ (กม.)
    tile_km = 40075.0 / (2 ** ZOOM) * math.cos(math.radians(LAT))
    km_per_px = tile_km / TILE_PX
    rad_px = max(3, int(RADAR_RADIUS_KM / km_per_px))   # รัศมีที่ถือว่า "ใกล้ตัว"

    def tile_has_rain(path):
        # color scheme 4 = universal blue, smooth=1, snow=0
        url = f"{host}{path}/{TILE_PX}/{ZOOM}/{x}/{y}/4/1_0.png"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                return False
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            w, h = img.size
            cx, cy = int(fx * w), int(fy * h)

            hits = total = 0
            for px in range(cx - rad_px, cx + rad_px + 1):
                for py in range(cy - rad_px, cy + rad_px + 1):
                    if not (0 <= px < w and 0 <= py < h):
                        continue          # จุดที่ล้นออกนอก tile ข้ามไป
                    if (px - cx) ** 2 + (py - cy) ** 2 > rad_px ** 2:
                        continue          # นับเฉพาะในวงกลม ไม่ใช่สี่เหลี่ยม
                    total += 1
                    if img.getpixel((px, py))[3] > 40:   # alpha > 40 = มีสี = มีฝน
                        hits += 1
            return total > 0 and (hits / total) > 0.02
        except Exception:
            return False

    res = {"now": False, "in_30min": False}
    if past:
        res["now"] = tile_has_rain(past[-1]["path"])
    if nowcast:
        # เฟรม nowcast แรก ๆ = อีกประมาณ 10-30 นาทีข้างหน้า
        for f in nowcast[:3]:
            if tile_has_rain(f["path"]):
                res["in_30min"] = True
                break
    return res


# =====================================================================
#  3) ประกาศเตือนภัยกรมอุตุนิยมวิทยา
# =====================================================================

def fetch_tmd_warning():
    """
    ดึงหน้าประกาศเตือนภัยของกรมอุตุฯ แล้วมองหาคำที่เกี่ยวกับพื้นที่เรา
    คืนค่า str (สรุปสั้น) หรือ None
    """
    url = "https://tmd.go.th/warning-and-events/warning-storm"
    keywords = ["ฉะเชิงเทรา", "ภาคตะวันออก", "กรุงเทพ", "ปริมณฑล",
                "ฝนตกหนัก", "พายุฤดูร้อน", "พายุ"]
    try:
        r = requests.get(url, timeout=25, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print(f"ดึงประกาศเตือนภัย TMD ไม่ได้: {e}")
        return None

    found = [k for k in keywords if k in text]
    # เช็คว่ามีคำที่บ่งชี้ประกาศที่ยังมีผลอยู่
    if "ฝนตกหนัก" in found or "พายุ" in found:
        area_hits = [k for k in ["ฉะเชิงเทรา", "ภาคตะวันออก", "กรุงเทพ", "ปริมณฑล"] if k in found]
        if area_hits:
            return f"พบประกาศเตือนภัยที่อาจเกี่ยวกับพื้นที่ ({', '.join(area_hits)}) — เปิดดูรายละเอียด: {url}"
    return None


# =====================================================================
#  4) น้ำขึ้น-น้ำลง — เตือนเมื่อฝนหนักตรงกับน้ำขึ้นสูง
# =====================================================================

def fetch_tide_clash(forecast):
    """
    เช็คว่ามีชั่วโมงไหนที่ฝนหนักตรงกับช่วงน้ำขึ้นสูงหรือไม่
    บางปะกงอยู่ปากแม่น้ำ ถ้าเจอพร้อมกันน้ำจะระบายไม่ทัน
    คืนค่า str (ข้อความเตือน) หรือ None
    """
    if not forecast:
        return None
    try:
        r = requests.get("https://marine-api.open-meteo.com/v1/marine", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "sea_level_height_msl",
            "timezone": "Asia/Bangkok", "forecast_days": 2,
            "cell_selection": "sea",
        }, timeout=25)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"  ดึงข้อมูลน้ำไม่ได้: {e}")
        return None

    t = d["hourly"]["time"]
    v = d["hourly"]["sea_level_height_msl"]
    if not v or all(x is None for x in v):
        return None

    # หาจุดน้ำขึ้นสูงสุดเฉพาะที่
    highs = []
    for i in range(1, len(v) - 1):
        if v[i] is None or v[i-1] is None or v[i+1] is None:
            continue
        if v[i] >= v[i-1] and v[i] >= v[i+1]:
            tm = datetime.fromisoformat(t[i])
            if tm >= now_th():
                if highs and (tm - highs[-1][0]).total_seconds() < 4 * 3600:
                    if v[i] > highs[-1][1]:
                        highs[-1] = (tm, v[i])
                    continue
                highs.append((tm, v[i]))

    for tm, lvl in highs:
        for f in forecast:
            if f["rain_mm"] >= TIDE_CLASH_MM and \
               abs((f["time"] - tm).total_seconds()) <= 90 * 60:
                return (f"ฝน {f['rain_mm']:.1f} มม./ชม. ตรงกับน้ำขึ้นสูง "
                        f"{lvl:+.2f} ม. เวลา {tm:%H:%M}\n"
                        f"น้ำระบายลงแม่น้ำช้ากว่าปกติ เสี่ยงท่วมขังในไซต์ "
                        f"— ตรวจปั๊มสูบน้ำ ทางระบายน้ำ และความลาดชันบ่อขุด")
    return None


# =====================================================================
#  ประกอบข้อความแจ้งเตือน
# =====================================================================

def build_message(forecast, radar, warning, always_send=False, tide_clash=None):
    """
    สร้างข้อความแจ้งเตือน คืนค่า (text, severity_key) หรือ (None, None) ถ้าไม่ต้องเตือน

    always_send=True  → ส่งข้อความเสมอแม้ไม่มีฝน (ใช้กับสรุปประจำวันตอนเช้า)
    """
    lines = []
    severity = None
    t_now = now_th().strftime("%H:%M")

    # --- ฝนหนักตรงกับน้ำขึ้นสูง (เฉพาะพื้นที่ปากแม่น้ำ) ---
    if tide_clash:
        lines.append(f"🌊 <b>ฝนหนักตรงกับน้ำขึ้นสูง</b>\n{tide_clash}")
        severity = "tide"

    # --- ประกาศเตือนภัย ---
    if warning:
        lines.append(f"⚠️ <b>ประกาศเตือนภัย</b>\n{warning}")
        severity = "warning"

    # --- เรดาร์ nowcast ---
    radar_line = None
    if radar and radar.get("rain_detected"):
        rd = radar["rain_detected"]
        if rd.get("now"):
            radar_line = f"📡 เรดาร์: มีฝนอยู่เหนือ{PLACE_NAME}แล้วตอนนี้"
            severity = severity or "radar_now"
        elif rd.get("in_30min"):
            radar_line = f"📡 เรดาร์: มีกลุ่มฝนกำลังเข้า{PLACE_NAME} ใน ~30 นาที"
            severity = severity or "radar_soon"
    if radar_line:
        lines.append(radar_line)

    # --- พยากรณ์รายชั่วโมง ---
    if forecast:
        max_rain = max((f["rain_mm"] for f in forecast), default=0)
        max_prob = max((f["prob"] for f in forecast), default=0)
        max_gust = max((f["gust"] for f in forecast), default=0)

        # เงื่อนไขฝน: ต้องเข้า "ทั้ง" ปริมาณและโอกาส
        # เดิมใช้ปริมาณอย่างเดียว แล้วมีอีกกิ่งที่ใช้โอกาสอย่างเดียว
        # ทำให้เตือนแม้ฝน 0 มม. ขอแค่โอกาส 60% ซึ่งเป็นสาเหตุหลักของการเตือนผิด
        rain_hours = [f for f in forecast
                      if f["rain_mm"] >= RAIN_MM_ALERT and f["prob"] >= PROB_ALERT]

        # ---------------------------------------------------------------
        #  เรดาร์ยับยั้งการเตือนฝนเบา
        # ---------------------------------------------------------------
        #  ปัญหาที่เจอจริง: โมเดลความละเอียด 9-13 กม. มักเกลี่ยฝนกระจาย
        #  ทำให้บอกว่ามีฝน 1-3 มม. ทั้งที่ไม่ตกจริงตรงจุดเรา
        #
        #  กฎ: ถ้าเรดาร์ไม่เห็นฝนเลยในรัศมี 25 กม. และฝนที่ทำนายยังไม่ถึง
        #      ระดับหนัก → งดเตือน เพราะโอกาสเตือนผิดสูงกว่าโอกาสถูก
        #      แต่ถ้าเป็นฝนหนัก (>= 7.5 มม./ชม.) เตือนเสมอ
        #      เพราะราคาของการพลาดสูงกว่าราคาของการเตือนเกิน
        # ---------------------------------------------------------------
        vetoed = False
        if RADAR_VETO and rain_hours and radar is not None:
            rd = radar.get("rain_detected")
            radar_clear = (rd is not None
                           and not rd.get("now") and not rd.get("in_30min"))
            light_only = max(f["rain_mm"] for f in rain_hours) < RAIN_MM_HEAVY
            if radar_clear and light_only:
                rain_hours = []
                vetoed = True

        if rain_hours:
            if max_rain >= RAIN_MM_VERY_HEAVY:
                head, sev = "⛈️ <b>ฝนหนักมาก</b>", "very_heavy"
            elif max_rain >= RAIN_MM_HEAVY:
                head, sev = "⛈️ <b>ฝนหนัก</b>", "heavy"
            else:
                head, sev = "🌧️ <b>มีฝน</b>", "rain"
            severity = severity or sev

            slots = ", ".join(
                f"{f['time'].strftime('%H:%M')} ({f['rain_mm']:.1f} มม.)"
                for f in rain_hours
            )
            conf = "—"
            if radar and radar.get("rain_detected") is not None:
                conf = ("เรดาร์ยืนยันแล้ว ✓" if radar["rain_detected"].get("now")
                        else "เรดาร์ยังไม่เห็น (อาจไม่ตกจริง)")
            lines.append(f"{head} ที่{PLACE_NAME}\nช่วงเวลา: {slots}\n"
                         f"โอกาสฝน {max_prob:.0f}% · {conf}")

        elif vetoed:
            # ไม่เตือน แต่พิมพ์ลง log ให้เห็นว่าระบบยับยั้งไป
            print("  → เรดาร์ยับยั้งการเตือนฝนเบา (โมเดลว่ามี แต่เรดาร์ไม่เห็น)")

        # --- ความเสี่ยงพายุฟ้าคะนอง (CAPE) ---
        capes = [f["cape"] for f in forecast if f["cape"] is not None]
        if capes and max(capes) >= CAPE_ALERT:
            severity = severity or "storm"
            lines.append(f"⚡ <b>บรรยากาศไม่เสถียรมาก (CAPE {max(capes):.0f} J/kg)</b>\n"
                         f"เสี่ยงพายุฝนฟ้าคะนองรุนแรง ลมกระโชก และฟ้าผ่า\n"
                         f"→ เตรียมหยุดงานที่สูงและงานเครน ถอดปลั๊กเครื่องมือไฟฟ้า")

        # --- ความร้อน (ความปลอดภัยคนงาน) ---
        heats = [f["heat"] for f in forecast if f["heat"] is not None]
        if heats and max(heats) >= HEAT_ALERT:
            severity = severity or "heat"
            lines.append(f"🥵 <b>อุณหภูมิที่รู้สึกได้ {max(heats):.0f}°C</b>\n"
                         f"เสี่ยงตะคริวและเพลียแดด — เพิ่มรอบพัก จัดน้ำดื่มและจุดพักในร่ม")

        # --- ลมกระโชก (สำคัญกับงานก่อสร้าง) ---
        if max_gust >= GUST_DANGER:
            severity = severity or "gust"
            lines.append(f"💨 <b>ลมกระโชกแรงมาก {max_gust:.0f} กม./ชม.</b>\n"
                         f"→ ควรหยุดงานนั่งร้าน/เครน/ยกของสูง และรัดผ้าใบคลุมให้แน่น")
        elif max_gust >= GUST_ALERT:
            severity = severity or "gust"
            lines.append(f"💨 ลมกระโชก {max_gust:.0f} กม./ชม. — ระวังงานที่สูง นั่งร้าน ผ้าใบคลุม")

    # --- ไม่มีอะไรต้องเตือน ---
    if severity is None:
        if SEND_WHEN_CLEAR or always_send:
            extra = ""
            if forecast:
                mx = max((f["rain_mm"] for f in forecast), default=0)
                mp = max((f["prob"] for f in forecast), default=0)
                mg = max((f["gust"] for f in forecast), default=0)
                extra = (f"\nโอกาสฝนสูงสุด {mp:.0f}% · ฝนสูงสุด {mx:.1f} มม./ชม. "
                         f"· ลมกระโชกสูงสุด {mg:.0f} กม./ชม.")
            return (f"✅ <b>{PLACE_NAME}</b> {t_now} — ไม่มีฝนใน {LOOKAHEAD_HOURS} ชม.ข้างหน้า "
                    f"ไม่มีประกาศเตือนภัย{extra}"
                    f"\n<i>ที่มา: กรมอุตุนิยมวิทยา / Open-Meteo</i>"), "clear"
        return None, None

    header = f"🌏 <b>เตือนสภาพอากาศ {PLACE_NAME}</b>  ({t_now})"
    footer = "\n<i>ที่มา: กรมอุตุนิยมวิทยา / Open-Meteo / RainViewer</i>"
    if radar and radar.get("map_url"):
        footer = f"\n<a href=\"{radar['map_url']}\">ดูเรดาร์สด</a>" + footer

    return header + "\n\n" + "\n\n".join(lines) + footer, severity


# =====================================================================
#  MAIN
# =====================================================================

def main():
    ap = argparse.ArgumentParser(description="เตือนฝนบางปะกง เข้า Telegram")
    ap.add_argument("--test", action="store_true",
                    help="ส่งข้อความทดสอบเข้า Telegram แล้วจบ")
    ap.add_argument("--force", action="store_true",
                    help="ส่งข้อความเสมอ แม้ไม่มีฝน และข้าม cooldown (ใช้กับสรุปประจำวัน)")
    args = ap.parse_args()

    if args.test:
        ok = send_telegram("✅ ทดสอบระบบเตือนฝนบางปะกง — เชื่อมต่อ Telegram สำเร็จแล้ว")
        sys.exit(0 if ok else 1)

    print(f"[{now_th():%Y-%m-%d %H:%M:%S}] เริ่มเช็คสภาพอากาศ {PLACE_NAME} ({LAT}, {LON})")

    forecast = fetch_forecast()
    if forecast:
        print(f"  พยากรณ์: ได้ {len(forecast)} ชั่วโมงข้างหน้า")
        for f in forecast:
            print(f"    {f['time']:%H:%M}  ฝน {f['rain_mm']:.1f} มม.  "
                  f"โอกาส {f['prob']}%  ลมกระโชก {f['gust']:.0f} กม./ชม.  "
                  f"CAPE {f['cape'] if f['cape'] is not None else '-'}  "
                  f"รู้สึก {f['heat'] if f['heat'] is not None else '-'}°C")
    else:
        print("  พยากรณ์: ดึงไม่ได้")

    radar = fetch_radar_nowcast()
    if radar:
        rd = radar.get("rain_detected")
        if rd is None:
            print("  เรดาร์: ข้ามการอ่านภาพ (ยังไม่ได้ติดตั้ง Pillow — pip install pillow)")
        else:
            print(f"  เรดาร์: ฝนตอนนี้={rd['now']}  ฝนใน 30 นาที={rd['in_30min']}")
    else:
        print("  เรดาร์: ดึงไม่ได้")

    warning = fetch_tmd_warning()
    print(f"  ประกาศเตือนภัย: {'พบ' if warning else 'ไม่พบ'}")

    tide_clash = fetch_tide_clash(forecast)
    print(f"  ฝนหนักตรงน้ำขึ้น: {'พบ' if tide_clash else 'ไม่พบ'}")

    text, severity = build_message(forecast, radar, warning,
                                   always_send=args.force, tide_clash=tide_clash)

    if text is None:
        print("  → ไม่มีอะไรต้องเตือน ไม่ส่งข้อความ")
        return

    state = load_state()
    rank = SEVERITY_RANK.get(severity, 0)

    # ช่วงเวลาห้ามปลุก — ผ่านได้เฉพาะเรื่องรุนแรงจริง
    if not args.force and in_quiet_hours() and rank < QUIET_MIN_RANK:
        print(f"  → อยู่ในช่วงงดรบกวน ({QUIET_START}:00-{QUIET_END}:00) "
              f"และความรุนแรงระดับ {rank} ยังไม่ถึงเกณฑ์ปลุก ({QUIET_MIN_RANK}) ไม่ส่ง")
        log_alert(severity, forecast, radar, sent=False)
        return

    if not args.force and in_cooldown(state, severity):
        print(f"  → เพิ่งเตือนไปภายใน {COOLDOWN_MINUTES} นาที "
              f"และความรุนแรงไม่ได้เพิ่มขึ้น ไม่ส่งซ้ำ")
        log_alert(severity, forecast, radar, sent=False)
        return

    print("--- ข้อความ ---")
    print(text)
    ok = send_telegram(text)
    log_alert(severity, forecast, radar, sent=ok)
    if ok:
        state["last_alert_at"] = now_th().isoformat()
        state["last_rank"] = rank
        state["last_severity"] = severity
        save_state(state)


if __name__ == "__main__":
    main()
