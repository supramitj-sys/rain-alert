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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8445798616:AAFfkV44XIRa5Rxcgrjz7ah5WJ8h0gJE4Vc")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "805315744")

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

# ---------------------------------------------------------------------
#  ใช้หลายโมเดลตรวจสอบกันเอง — วิธีลด false alarm ที่ได้ผลที่สุด
# ---------------------------------------------------------------------
#  โมเดลเดี่ยวที่ความละเอียด 9-13 กม. มักสร้างฝนผีขึ้นมาเอง
#  แต่ถ้าโมเดลจากคนละสำนัก คนละวิธีคำนวณ บอกตรงกัน = น่าเชื่อกว่ามาก
#  เทคนิคนี้เรียก model consensus นักพยากรณ์มืออาชีพใช้จริง
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]

# โมเดล WRF ของกรมอุตุนิยมวิทยา — ความละเอียดสูงกว่าโมเดลโลกและปรับจูนสำหรับไทย
# ต้องลงทะเบียนที่ data.tmd.go.th/api/index1.php เพื่อรับโทเคน (ฟรี)
# ใส่ไว้ใน GitHub Secrets ชื่อ TMD_TOKEN — ห้าม commit โทเคนจริงขึ้น repo
TMD_TOKEN = os.environ.get("TMD_TOKEN", "")
USE_TMD = bool(TMD_TOKEN)
MIN_MODEL_AGREE = 2        # ต้องมีอย่างน้อยกี่โมเดลเห็นตรงกันจึงจะเตือน

# --- ใช้ประโยชน์จากตัวแปรอื่นที่ TMD ให้มา นอกเหนือจากฝน ---
# (อ้างอิง: https://data.tmd.go.th/nwpapi/doc/apidoc/location/forecast_hourly.html)
TMD_PRESSURE_DROP_ALERT = 1.5   # hPa — ความกดอากาศลดลงเกินนี้ในช่วงที่ดึงมา
                                 # = สัญญาณความกดอากาศต่ำ/พายุเข้าใกล้ มักมาก่อนโมเดลฝนจะเห็น
TMD_CLOUD_DENSE = 70             # % — เมฆระดับต่ำเกินนี้ถือว่าหนาแน่น ใช้เสริมความมั่นใจของฝน

# ต้องเจอเหตุการณ์เดิมซ้ำ 2 รอบติดกันจึงเตือน
# ถ้าโมเดลเห็นชั่วโมงนี้ พอชั่วโมงถัดไปหายไป = สัญญาณรบกวน ไม่ใช่ฝนจริง
REQUIRE_PERSISTENCE = True

# ใช้เรดาร์ยับยั้งการเตือนฝนเบา — ถ้าโมเดลบอกว่ามีฝนใน 1 ชม.
# แต่เรดาร์ไม่เห็นอะไรเลยในรัศมี 25 กม. แปลว่าโมเดลน่าจะเกลี่ยฝนผิดที่
RADAR_VETO = True

STATE_FILE = "rain_alert_state.json"
ALERT_LOG = "alert_log.csv"   # บันทึกทุกการเตือน ไว้ตรวจย้อนหลังว่าแม่นแค่ไหน


# ระดับความรุนแรง — ใช้ตัดสินว่าจะเตือนซ้ำหรือปลุกกลางดึกไหม
SEVERITY_RANK = {
    "clear": 0, "heat": 2, "gust": 3, "rain": 3, "radar_now": 4,
    "pressure": 4, "heavy": 5, "storm": 5, "very_heavy": 6, "tide": 6,
    "warning": 7,
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


def wind_compass(deg):
    """
    แปลงองศาทิศทางลม (ตามที่ TMD ให้มา) เป็นสิ่งที่อ่านแล้วเห็นภาพทันที

    หลักการ: ตัวเลขทิศทางลมทางอุตุนิยมวิทยาบอก "ทิศที่ลมพัดมาจาก" ไม่ใช่ทิศที่พัดไป
    เช่น 0°/เหนือ = ลมพัดมาจากทิศเหนือ แล้ววิ่งลงไปทางใต้
    ฟังก์ชันนี้จึงคืนทั้งป้ายกำกับ "มาจากทิศไหน" (คนอ่านเข้าใจง่ายสุด)
    และลูกศรที่ชี้ไปทิศที่ลมกำลังพัดไปหา (ทิศตรงข้าม) ไว้แปะในข้อความให้เห็นภาพ

    คืนค่า dict {from_th, from_code, arrow} หรือ None ถ้าไม่มีข้อมูล
    """
    if deg is None:
        return None
    deg = float(deg) % 360
    idx = int((deg / 45) + 0.5) % 8
    flow_idx = (idx + 4) % 8      # ทิศตรงข้าม = ทิศที่ลมพัดไปหา
    names = ["เหนือ", "ตะวันออกเฉียงเหนือ", "ตะวันออก", "ตะวันออกเฉียงใต้",
             "ใต้", "ตะวันตกเฉียงใต้", "ตะวันตก", "ตะวันตกเฉียงเหนือ"]
    codes = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    arrows = ["⬆️", "↗️", "➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️"]   # ชี้ไปทิศนั้น ๆ (เหนืออยู่บน)
    return {"from_th": names[idx], "from_code": codes[idx], "arrow": arrows[flow_idx]}


# รหัสสภาพอากาศจาก TMD (cond) — อ้างอิงเอกสาร nwpapi
TMD_COND_TEXT = {
    1: "ท้องฟ้าแจ่มใส", 2: "มีเมฆบางส่วน", 3: "เมฆเป็นส่วนมาก", 4: "มีเมฆมาก",
    5: "ฝนตกเล็กน้อย", 6: "ฝนปานกลาง", 7: "ฝนตกหนัก", 8: "ฝนฟ้าคะนอง",
    9: "อากาศหนาวจัด", 10: "อากาศหนาว", 11: "อากาศเย็น", 12: "อากาศร้อนจัด",
}


def check_persistence(state, rain_hours):
    """
    ตรวจว่าเหตุการณ์ฝนนี้เคยถูกทำนายในรอบก่อนหรือไม่

    เหตุผล: โมเดลที่มั่นใจจริงจะทำนายชั่วโมงเดิมซ้ำหลายรอบ
    ส่วนฝนผีมักโผล่มารอบเดียวแล้วหายไปรอบถัดไป
    การบังคับให้เจอซ้ำ 2 รอบจึงกรองสัญญาณรบกวนออกได้มาก
    แลกกับการเตือนช้าลงราว 1 ชั่วโมง

    คืนค่า (ผ่านหรือไม่, ชั่วโมงที่ควรบันทึกไว้ใช้รอบหน้า)
    """
    now_hours = sorted({f["time"].strftime("%Y-%m-%dT%H") for f in rain_hours})
    if not REQUIRE_PERSISTENCE:
        return True, now_hours

    prev = set(state.get("last_rain_hours") or [])
    overlap = prev & set(now_hours)
    return bool(overlap), now_hours


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
        ag = max((f["agree"] for f in forecast), default=0) if forecast else 0
        nm = max((f["n_models"] for f in forecast), default=0) if forecast else 0
        rd = ""
        if radar and radar.get("rain_detected"):
            rd = "yes" if radar["rain_detected"].get("now") else "no"
        with open(ALERT_LOG, "a", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)",
                            "โอกาสฝน(%)", "โมเดลตรงกัน", "จำนวนโมเดล",
                            "TMD_WRF(มม.)", "เรดาร์เห็นฝน", "ส่งจริง",
                            "ฝนตกจริง(กรอกเอง Y/N)"])
            tmds = [f.get("tmd_mm") for f in (forecast or [])
                    if f.get("tmd_mm") is not None]
            td = f"{max(tmds):.1f}" if tmds else ""
            w.writerow([f"{now_th():%Y-%m-%d %H:%M}", severity,
                        f"{mx:.1f}", f"{mp:.0f}", ag, nm, td, rd,
                        "yes" if sent else "no", ""])
    except Exception as e:
        print(f"  บันทึก log ไม่ได้: {e}")


# =====================================================================
#  1) พยากรณ์รายชั่วโมง — Open-Meteo
# =====================================================================

def fetch_forecast():
    """
    ดึงพยากรณ์รายชั่วโมงจากหลายโมเดลพร้อมกัน (model consensus)

    เมื่อส่ง &models=a,b,c ทาง Open-Meteo จะเติมชื่อโมเดลต่อท้ายทุกตัวแปร
    เช่น precipitation_ecmwf_ifs025, precipitation_gfs_seamless
    โค้ดนี้จึงไม่ hardcode ชื่อคีย์ แต่ค้นหาเอาจากผลลัพธ์จริง
    ถ้าชื่อโมเดลตัวไหนผิดหรือไม่รองรับ ก็จะหายไปเฉย ๆ ไม่ทำให้ทั้งระบบพัง

    คืนค่า list ของ dict:
      {time, rain_mm (ค่ากลาง), rain_max, agree (จำนวนโมเดลที่เห็นฝน),
       n_models, prob, temp, gust, cape, heat, per_model {ชื่อ: มม.}}
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": ("precipitation,precipitation_probability,temperature_2m,"
                   "wind_gusts_10m,cape,apparent_temperature"),
        "timezone": "Asia/Bangkok",
        "forecast_days": 2,
        "models": ",".join(MODELS),
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ดึง Open-Meteo ไม่ได้: {e}")
        return None

    h = data.get("hourly", {})
    times = h.get("time", [])
    if not times:
        return None

    def keys_for(var):
        """หาคีย์ทั้งหมดของตัวแปรนี้ (ทุกโมเดล) จากผลลัพธ์จริง"""
        exact = [k for k in h if k == var]
        pref = [k for k in h if k.startswith(var + "_")]
        # กัน precipitation_probability ถูกจับเป็น precipitation
        if var == "precipitation":
            pref = [k for k in pref if not k.startswith("precipitation_probability")]
        return exact + pref

    rain_keys = keys_for("precipitation")
    prob_keys = keys_for("precipitation_probability")
    temp_keys = keys_for("temperature_2m")
    gust_keys = keys_for("wind_gusts_10m")
    cape_keys = keys_for("cape")
    heat_keys = keys_for("apparent_temperature")

    if not rain_keys:
        print("  !! ไม่พบข้อมูลฝนในผลลัพธ์ — ชื่อโมเดลอาจไม่ถูกต้อง")
        return None
    print(f"  โมเดลที่ใช้ได้จริง {len(rain_keys)} ตัว: "
          + ", ".join(k.replace("precipitation_", "") or "default" for k in rain_keys))

    def vals(keys, i):
        out = []
        for k in keys:
            arr = h.get(k) or []
            if i < len(arr) and arr[i] is not None:
                out.append(arr[i])
        return out

    now = now_th()
    out = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        delta_h = (dt - now).total_seconds() / 3600
        if not (-1 <= delta_h <= LOOKAHEAD_HOURS):
            continue

        rains = vals(rain_keys, i)
        if not rains:
            continue
        rains_sorted = sorted(rains)
        median = rains_sorted[len(rains_sorted) // 2]

        probs = vals(prob_keys, i)
        temps = vals(temp_keys, i)
        gusts = vals(gust_keys, i)
        capes = vals(cape_keys, i)
        heats = vals(heat_keys, i)

        out.append({
            "time": dt,
            "tmd_mm": None,      # เติมทีหลังใน merge_tmd()
            # ใช้ค่ากลาง ไม่ใช่ค่าสูงสุด — โมเดลตัวเดียวที่หลุดโด่งจะไม่ลากทั้งกลุ่ม
            "rain_mm": median,
            "rain_max": max(rains),
            "agree": sum(1 for v in rains if v >= RAIN_MM_ALERT),
            "n_models": len(rains),
            "per_model": {k.replace("precipitation_", "") or "default": v
                          for k, v in zip(rain_keys, rains)},
            "prob": max(probs) if probs else 0,
            "temp": sum(temps) / len(temps) if temps else None,
            "gust": max(gusts) if gusts else 0,
            "cape": max(capes) if capes else None,
            "heat": max(heats) if heats else None,
        })
    return out


def merge_tmd(forecast, tmd):
    """
    รวมผลจากโมเดล WRF ของกรมอุตุฯ เข้ากับผลจากโมเดลโลก

    - ฝน: ถือเป็นอีก 1 เสียงใน consensus (น้ำหนักเพิ่มเพราะละเอียดกว่าและปรับจูนสำหรับไทย)
    - อุณหภูมิ/ความชื้น/ลม(ความเร็ว+ทิศทาง)/ความกดอากาศ/รหัสสภาพอากาศ/เมฆ:
      แนบไว้ที่ f['tmd'] เพื่อใช้เสริมข้อความแจ้งเตือน (ไม่ได้เอาไปโหวตร่วมกับฝน)
    """
    if not forecast or not tmd:
        return forecast

    hit = 0
    for f in forecast:
        key = f["time"].strftime("%Y-%m-%dT%H")
        td = tmd.get(key)
        if td is None:
            continue
        hit += 1
        mm = td["rain"]
        f["tmd_mm"] = mm
        f["tmd"] = td
        f["n_models"] += 1
        if mm >= RAIN_MM_ALERT:
            f["agree"] += 1
        f["per_model"]["tmd_wrf"] = mm
        # คำนวณค่ากลางใหม่โดยรวม TMD เข้าไปด้วย
        vals = sorted(f["per_model"].values())
        f["rain_mm"] = vals[len(vals) // 2]
        f["rain_max"] = max(vals)

    if hit:
        print(f"  รวมโมเดล TMD เข้ากับ consensus ได้ {hit} ชั่วโมง")
    return forecast


def tmd_pressure_trend(tmd):
    """
    เช็คแนวโน้มความกดอากาศ (slp) จากข้อมูล TMD ในช่วงที่ดึงมา

    ความกดอากาศที่ลดลงเร็วมักเป็นสัญญาณล่วงหน้าของระบบความกดอากาศต่ำ/พายุ
    ที่มาก่อนโมเดลฝนรายชั่วโมงจะทำนายฝนได้ทัน จึงใช้เป็นสัญญาณเตือนล่วงหน้าอีกชั้น

    คืนค่า (delta_hpa, จำนวนชั่วโมงที่ครอบคลุม) หรือ (None, 0) ถ้าข้อมูลไม่พอ
    """
    if not tmd:
        return None, 0
    pts = [(k, v["slp"]) for k, v in tmd.items() if v.get("slp") is not None]
    if len(pts) < 2:
        return None, 0
    pts.sort(key=lambda x: x[0])
    delta = pts[-1][1] - pts[0][1]
    return delta, len(pts) - 1


# =====================================================================
#  1b) โมเดล WRF ของกรมอุตุนิยมวิทยา (NWP API)
# =====================================================================

def fetch_tmd_forecast(hours=None):
    """
    ดึงพยากรณ์รายชั่วโมงจากโมเดล WRF ของกรมอุตุฯ — ดึงให้ครบทุกตัวที่มีประโยชน์
    ไม่ใช่แค่ฝน แต่รวมอุณหภูมิ ความชื้น ลม(ความเร็ว+ทิศทาง) ความกดอากาศ
    รหัสสภาพอากาศ (cond) และเมฆระดับต่ำ เพื่อใช้เสริมข้อความแจ้งเตือน

    เอกสาร: https://data.tmd.go.th/nwpapi/doc/apidoc/location/forecast_hourly.html
    โทเคนต้องส่งใน header ไม่ใช่ query string
    (ตรงนี้คือจุดที่คนพลาดบ่อย เพราะเอา URL ไปเปิดในเบราว์เซอร์เฉย ๆ ไม่ได้)

    ดึงยาวกว่าที่ merge เข้ากับฝนเล็กน้อย (อย่างน้อย 6 ชม.) เพื่อให้เห็นแนวโน้ม
    ความกดอากาศได้ชัดกว่าการดูแค่ช่วง LOOKAHEAD_HOURS

    คืนค่า dict {'YYYY-MM-DDTHH': {rain, tc, rh, ws10m, wd10m, slp, cond, cloudlow}}
    หรือ None ถ้าดึงไม่ได้
    """
    if not USE_TMD:
        return None

    hours = hours or max(LOOKAHEAD_HOURS + 1, 6)
    t = now_th()
    url = "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/at"
    headers = {
        "accept": "application/json",
        "authorization": "Bearer " + TMD_TOKEN,
    }

    # ลองชุดตัวแปรแบบเต็มก่อน ถ้าไม่ผ่านค่อยถอยไปชุดพื้นฐานที่ยืนยันแล้วว่าใช้ได้
    field_sets = (
        "tc,rh,rain,ws10m,wd10m,slp,cond,cloudlow",
        "tc,rh,rain,ws10m,wd10m,cond",
        "tc,rh,rain",
    )
    for fields in field_sets:
        params = {
            "lat": LAT, "lon": LON, "fields": fields,
            "date": f"{t:%Y-%m-%d}", "hour": t.hour, "duration": hours,
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=25)
            if r.status_code == 401:
                print("  TMD: โทเคนไม่ถูกต้องหรือหมดอายุ")
                return None
            if r.status_code != 200:
                print(f"  TMD: ตอบ {r.status_code} (ลองชุดตัวแปรถัดไป)")
                continue
            d = r.json()
        except Exception as e:
            print(f"  TMD: ดึงไม่ได้ ({e})")
            continue

        try:
            fc = d["WeatherForecasts"][0]["forecasts"]
        except (KeyError, IndexError, TypeError):
            print("  TMD: รูปแบบผลลัพธ์ไม่ตรงที่คาด")
            continue

        out = {}
        for f in fc:
            tm = f.get("time")
            data = f.get("data") or {}
            rain = data.get("rain")
            if tm is None or rain is None:
                continue
            try:
                # เวลาอาจมาในหลายรูปแบบ ตัดเอาเฉพาะ YYYY-MM-DDTHH
                key = str(tm).replace(" ", "T")[:13]
                out[key] = {
                    "rain": float(rain),
                    "tc": data.get("tc"),
                    "rh": data.get("rh"),
                    "ws10m": data.get("ws10m"),
                    "wd10m": data.get("wd10m"),
                    "slp": data.get("slp"),
                    "cond": data.get("cond"),
                    "cloudlow": data.get("cloudlow"),
                }
            except (ValueError, TypeError):
                continue

        if out:
            print(f"  TMD WRF: ได้ข้อมูล {len(out)} ชั่วโมง (fields={fields}, "
                  f"ฝนสูงสุด {max(v['rain'] for v in out.values()):.1f} มม.)")
            return out

    return None


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

def build_message(forecast, radar, warning, always_send=False, tide_clash=None,
                  persistence_ok=True, slp_delta=None, slp_span=0):
    """
    สร้างข้อความแจ้งเตือน คืนค่า (text, severity_key) หรือ (None, None) ถ้าไม่ต้องเตือน

    always_send=True  → ส่งข้อความเสมอแม้ไม่มีฝน (ใช้กับสรุปประจำวันตอนเช้า)
    slp_delta/slp_span → แนวโน้มความกดอากาศจาก TMD (ดู tmd_pressure_trend())
    """

    def _bump(sev, candidate):
        """ยกระดับ severity เฉพาะเมื่อ candidate รุนแรงกว่าที่มีอยู่แล้วเท่านั้น
        (กันไม่ให้สัญญาณที่มาทีหลังในโค้ดไปเบียดสัญญาณที่รุนแรงกว่าซึ่งเจอไปก่อนหน้า)"""
        return candidate if SEVERITY_RANK.get(sev, 0) < SEVERITY_RANK.get(candidate, 0) else sev
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

        # ---------------------------------------------------------------
        #  เงื่อนไขฝน 3 ชั้น
        # ---------------------------------------------------------------
        #  1) ค่ากลางของทุกโมเดลต้องถึงเกณฑ์ปริมาณ
        #  2) โอกาสฝนต้องถึงเกณฑ์
        #  3) ต้องมีโมเดลเห็นฝนตรงกันอย่างน้อย MIN_MODEL_AGREE ตัว
        #     ชั้นที่ 3 คือตัวกรอง false alarm ที่ได้ผลที่สุด เพราะโมเดลเดี่ยว
        #     ที่ความละเอียด 9-13 กม. มักสร้างฝนขึ้นมาเองโดยไม่มีจริง
        # ---------------------------------------------------------------
        rain_hours = [f for f in forecast
                      if f["rain_mm"] >= RAIN_MM_ALERT
                      and f["prob"] >= PROB_ALERT
                      and f["agree"] >= min(MIN_MODEL_AGREE, f["n_models"])]

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

        # ฝนหนักมากข้ามการตรวจความต่อเนื่อง — รอไม่ได้
        if rain_hours and persistence_ok is False and \
           max(f["rain_mm"] for f in rain_hours) < RAIN_MM_HEAVY:
            print("  → รอยืนยันอีก 1 รอบ (โมเดลเพิ่งเห็นฝนนี้ครั้งแรก)")
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
                        else "เรดาร์ยังไม่เห็น")
            best = max(rain_hours, key=lambda f: f["agree"])
            agree_txt = f"{best['agree']}/{best['n_models']} โมเดลตรงกัน"
            tmd_txt = ""
            tmds = [f["tmd_mm"] for f in rain_hours if f.get("tmd_mm") is not None]
            if tmds:
                mx_tmd = max(tmds)
                tmd_txt = ("\n🇹🇭 โมเดลกรมอุตุฯ (WRF): "
                           + (f"{mx_tmd:.1f} มม. — เห็นตรงกัน ✓"
                              if mx_tmd >= RAIN_MM_ALERT
                              else f"{mx_tmd:.1f} มม. — ไม่เห็นฝน"))

            # เมฆระดับต่ำจาก TMD — เสริมความมั่นใจว่าฝนจะตกจริง (นอกเหนือจากเรดาร์)
            cloud_txt = ""
            clouds = [f["tmd"]["cloudlow"] for f in rain_hours
                      if f.get("tmd", {}).get("cloudlow") is not None]
            if clouds and max(clouds) >= TMD_CLOUD_DENSE:
                cloud_txt = f"\n☁️ เมฆระดับต่ำหนาแน่น {max(clouds):.0f}% (TMD) — เสริมความมั่นใจว่าฝนจะตกจริง"

            lines.append(f"{head} ที่{PLACE_NAME}\nช่วงเวลา: {slots}\n"
                         f"โอกาสฝน {max_prob:.0f}% · {agree_txt} · {conf}{tmd_txt}{cloud_txt}")

        elif vetoed:
            # ไม่เตือน แต่พิมพ์ลง log ให้เห็นว่าระบบยับยั้งไป
            print("  → เรดาร์ยับยั้งการเตือนฝนเบา (โมเดลว่ามี แต่เรดาร์ไม่เห็น)")

        # --- รหัสสภาพอากาศจาก TMD (cond) — ฝนฟ้าคะนอง/ฝนหนัก ระบุชัดจากโมเดลไทยโดยตรง ---
        cond_hours = [f for f in forecast if f.get("tmd", {}).get("cond") in (7, 8)]
        if cond_hours:
            worst = max(f["tmd"]["cond"] for f in cond_hours)
            severity = _bump(severity, "storm" if worst == 8 else "heavy")
            when = ", ".join(f["time"].strftime("%H:%M") for f in cond_hours[:3])
            label = TMD_COND_TEXT.get(worst, str(worst))
            icon = "⛈️" if worst == 8 else "🌧️"
            lines.append(f"{icon} <b>TMD ระบุสภาพอากาศ: {label}</b> (cond={worst})\n"
                         f"ช่วงเวลา: {when}")

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
        wind_hours = [f for f in forecast if f.get("tmd", {}).get("wd10m") is not None]
        if max_gust >= GUST_DANGER:
            severity = severity or "gust"
            lines.append(f"💨 <b>ลมกระโชกแรงมาก {max_gust:.0f} กม./ชม.</b>\n"
                         f"→ ควรหยุดงานนั่งร้าน/เครน/ยกของสูง และรัดผ้าใบคลุมให้แน่น")
        elif max_gust >= GUST_ALERT:
            severity = severity or "gust"
            lines.append(f"💨 ลมกระโชก {max_gust:.0f} กม./ชม. — ระวังงานที่สูง นั่งร้าน ผ้าใบคลุม")

        # --- ทิศทางลมจาก TMD (ถ้ามี) — บอกด้านที่ลมมาจริง ๆ ไว้กางผ้าใบ/ป้องกันให้ถูกด้าน ---
        if max_gust >= GUST_ALERT and wind_hours:
            wf = max(wind_hours, key=lambda f: f.get("tmd", {}).get("ws10m") or 0)
            wc = wind_compass(wf["tmd"]["wd10m"])
            if wc:
                lines.append(
                    f"🧭 ลมมาจากทิศ{wc['from_th']} ({wc['from_code']}) {wc['arrow']}\n"
                    f"→ กางของ/ผูกผ้าใบด้านรับลมทิศ{wc['from_code']}ให้แน่นที่สุด"
                )

        # --- ความกดอากาศจาก TMD: สัญญาณเตือนล่วงหน้าก่อนโมเดลฝนจะฟันธง ---
        if slp_delta is not None and slp_delta <= -TMD_PRESSURE_DROP_ALERT:
            severity = _bump(severity, "pressure")
            lines.append(
                f"🇹🇭 <b>ความกดอากาศลดลง {abs(slp_delta):.1f} hPa ใน {slp_span} ชม.</b>\n"
                f"สัญญาณเริ่มมีระบบความกดอากาศต่ำ/พายุเข้าใกล้ — จับตาต่อเนื่อง"
                f" แม้โมเดลฝนยังไม่ฟันธง"
            )

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

    # รวมโมเดล WRF ของกรมอุตุฯ เข้าไปด้วย (ถ้าตั้งโทเคนไว้)
    tmd_raw = None
    if forecast and USE_TMD:
        tmd_raw = fetch_tmd_forecast()
        forecast = merge_tmd(forecast, tmd_raw)
    elif not USE_TMD:
        print("  (ยังไม่ได้ตั้ง TMD_TOKEN — ใช้เฉพาะโมเดลโลก)")

    slp_delta, slp_span = tmd_pressure_trend(tmd_raw)
    if slp_delta is not None:
        print(f"  TMD ความกดอากาศ: {'ลดลง' if slp_delta < 0 else 'เพิ่มขึ้น'} "
              f"{abs(slp_delta):.1f} hPa ใน {slp_span} ชม.")

    if forecast:
        print(f"  พยากรณ์: ได้ {len(forecast)} ชั่วโมงข้างหน้า")
        for f in forecast:
            td = f.get("tmd") or {}
            wc = wind_compass(td.get("wd10m"))
            wind_txt = f"จาก{wc['from_code']}" if wc else "-"
            print(f"    {f['time']:%H:%M}  ฝน {f['rain_mm']:.1f} มม.  "
                  f"โอกาส {f['prob']}%  ลมกระโชก {f['gust']:.0f} กม./ชม.  "
                  f"CAPE {f['cape'] if f['cape'] is not None else '-'}  "
                  f"รู้สึก {f['heat'] if f['heat'] is not None else '-'}°C  "
                  f"TMD {f.get('tmd_mm') if f.get('tmd_mm') is not None else '-'}  "
                  f"cond {td.get('cond', '-')}  ลม(TMD) {wind_txt}")
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

    state = load_state()

    # ตรวจความต่อเนื่อง — ใช้เกณฑ์เดียวกับที่ใช้คัดชั่วโมงฝน
    cand = [f for f in (forecast or [])
            if f["rain_mm"] >= RAIN_MM_ALERT and f["prob"] >= PROB_ALERT
            and f["agree"] >= min(MIN_MODEL_AGREE, f["n_models"])]
    persist_ok, cur_hours = check_persistence(state, cand)
    if cand:
        print(f"  ชั่วโมงที่เข้าเกณฑ์: {len(cand)} | "
              f"เคยเห็นรอบก่อน: {'ใช่' if persist_ok else 'ยังไม่เคย'}")

    text, severity = build_message(forecast, radar, warning,
                                   always_send=args.force, tide_clash=tide_clash,
                                   persistence_ok=persist_ok,
                                   slp_delta=slp_delta, slp_span=slp_span)

    # บันทึกชั่วโมงที่เข้าเกณฑ์ไว้เทียบรอบหน้าเสมอ แม้จะไม่ได้ส่งข้อความ
    state["last_rain_hours"] = cur_hours
    save_state(state)

    if text is None:
        print("  → ไม่มีอะไรต้องเตือน ไม่ส่งข้อความ")
        return

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
