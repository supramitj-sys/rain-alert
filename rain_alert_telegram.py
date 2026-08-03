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
#  CONFIG
# =====================================================================
#
#  ไฟล์นี้ถูกใช้ 2 ที่พร้อมกัน จึงต้องอ่านค่าลับจาก 2 แหล่ง:
#
#    รันบน GitHub Actions → อ่านจาก environment variable
#                           (ตั้งใน Settings > Secrets and variables > Actions)
#    รันบนเครื่องตัวเอง    → อ่านจากไฟล์ .txt ในโฟลเดอร์เดียวกัน
#                           (ไฟล์พวกนี้อยู่ใน .gitignore แล้ว จะไม่ถูกอัปขึ้น GitHub)
#
#  ห้ามพิมพ์ TOKEN ลงในไฟล์ .py นี้เด็ดขาด เพราะไฟล์ .py ต้องอัปขึ้น GitHub
#  ใครเห็น TOKEN ก็ยิงข้อความในนามบอทคุณได้
# =====================================================================

def _secret(env_name, filename):
    """
    อ่านค่าลับจาก environment variable ก่อน ถ้าไม่มีค่อยอ่านจากไฟล์ข้าง ๆ สคริปต์

    เรียงลำดับแบบนี้เพราะ GitHub Actions จะตั้ง env var ให้เสมอ ส่วนบนเครื่อง
    ตัวเองไม่มี env var จึงตกมาอ่านไฟล์แทน ไฟล์เดียวกันจึงใช้ได้ทั้งสองที่
    โดยไม่ต้องแก้โค้ดสลับไปมา

    .strip('<>') เผื่อคัดลอกวงเล็บจากตัวอย่างติดมาด้วย ซึ่งเป็นความผิดพลาดที่เจอบ่อย
    """
    v = os.environ.get(env_name, "").strip()
    if v:
        return v
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path, encoding="utf-8-sig") as f:
            return f.read().strip().strip("<>").strip()
    except Exception:
        return ""


TELEGRAM_TOKEN = _secret("TELEGRAM_TOKEN", "telegram_token.txt")
TELEGRAM_CHAT_ID = _secret("TELEGRAM_CHAT_ID", "telegram_chat_id.txt")

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

# ---------------------------------------------------------------------
#  เรดาร์ nowcast — แยก "ฝนอยู่เหนือหัวเรา" ออกจาก "ฝนอยู่แถว ๆ นี้"
# ---------------------------------------------------------------------
#  เวอร์ชันก่อนใช้เกณฑ์เดียว: มีสีฝน 2% ของวงรัศมี 25 กม. = "ฝนอยู่เหนือ
#  บางปะกงแล้ว" ซึ่งกว้างเกินไปมาก ก้อนฝนเล็ก ๆ ที่ห่างออกไป 30 กม.
#  ก็ทำให้ประกาศว่าฝนตกอยู่บนหัวแล้ว
#  ผลจริงจาก alert_log.csv สัปดาห์แรก: radar_now ยิง 39 ครั้ง ตกจริง 13%
#
#  จึงแยกเป็นสองวง คนละหน้าที่:
#    OVER = วงแคบรอบจุดจริง  -> ใช้ "เป็นเหตุผล" ในการเตือน
#    NEAR = วงกว้าง 25 กม.    -> ใช้ "ยับยั้ง" การเตือนฝนเบาเท่านั้น (RADAR_VETO)
#           และใช้เป็นข้อมูลประกอบว่ามีฝนแถวนี้แต่ยังไม่ถึงเรา
# ---------------------------------------------------------------------
RADAR_OVER_KM = 6          # รัศมีที่ถือว่า "ฝนอยู่เหนือจุดนี้จริง"
RADAR_NEAR_KM = 25         # รัศมีที่ถือว่า "มีฝนอยู่แถวนี้"
RADAR_OVER_COVERAGE = 0.25  # ต้องมีฝนคลุมเกิน 25% ของวงแคบ จึงนับว่าตกอยู่จริง
RADAR_NEAR_COVERAGE = 0.02  # แค่ 2% ของวงกว้างก็พอ เพราะใช้แค่ "ยับยั้ง" ไม่ใช่ "เตือน"
RADAR_ALPHA_MIN = 70        # ความเข้มสีขั้นต่ำที่นับว่าเป็นฝน (เดิม 40 = เก็บละอองจาง ๆ ด้วย)

#  ⚠️ ค่า RADAR_OVER_COVERAGE กับ RADAR_ALPHA_MIN สองตัวนี้ยัง "ตั้งจากเหตุผล"
#  ไม่ใช่ "ตั้งจากข้อมูล" เพราะ log รอบก่อนบันทึกแค่ yes/no ไม่ได้บันทึกว่า
#  ฝนคลุมกี่ % จึงย้อนไปหาจุดตัดที่ดีที่สุดไม่ได้
#  ตอนนี้ log บันทึก % ไว้แล้ว เก็บอีกสัปดาห์แล้วรัน analyze_alerts.py
#  หัวข้อ "ฝนต้องคลุมกี่ % ถึงจะเชื่อได้" จะบอกจุดตัดที่ถูกต้องจากของจริง

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
TMD_TOKEN = _secret("TMD_TOKEN", "tmd_token.txt")
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
# แต่เรดาร์ไม่เห็นอะไรเลยแม้แต่ในวงกว้าง RADAR_NEAR_KM แปลว่าโมเดลน่าจะเกลี่ยฝนผิดที่
RADAR_VETO = True

# ---------------------------------------------------------------------
#  ทริกเกอร์ที่ "ห้ามเตือนลำพัง" — ต้องมีหลักฐานฝนจริงมายืนยันก่อน
# ---------------------------------------------------------------------
#  จาก alert_log.csv สัปดาห์แรก (26 แถวที่กรอกผลจริงแล้ว):
#    pressure (ความกดอากาศลด) ยิง 11 ครั้ง กรอกแล้ว 6 -> ตกจริง 0 ครั้ง
#    storm    (CAPE สูง)      ยิง  7 ครั้ง กรอกแล้ว 5 -> ตกจริง 0 ครั้ง
#  ทั้งสองตัวคือ "สภาพแวดล้อมที่เอื้อให้เกิดฝน" ไม่ใช่ "ฝนที่กำลังจะตก"
#  ในเขตร้อน CAPE เกิน 2500 เป็นเรื่องปกติเกือบทุกบ่าย ถ้าเตือนทุกครั้ง
#  จะกลายเป็นเสียงรบกวนจนคนเลิกอ่าน
#
#  เปลี่ยนเป็น: ยังคำนวณและแสดงผลอยู่ แต่ย้ายไปอยู่ท้ายข้อความในหมวด
#  "ข้อมูลประกอบ" และจะยกระดับเป็นการเตือนก็ต่อเมื่อมีฝนจริงยืนยัน
#  (เรดาร์เห็นฝนในวงกว้าง หรือโมเดลฝนถึงเกณฑ์)
REQUIRE_RAIN_EVIDENCE = True

STATE_FILE = "rain_alert_state.json"
ALERT_LOG = "alert_log.csv"   # บันทึกทุกการเตือน ไว้ตรวจย้อนหลังว่าแม่นแค่ไหน

# ---------------------------------------------------------------------
#  สมุดจดค่าเรดาร์ — บันทึก "ทุกรอบที่รัน" ไม่ใช่เฉพาะตอนเตือน
# ---------------------------------------------------------------------
#  ปัญหาที่ต้องแก้: alert_log.csv บันทึกเฉพาะตอนระบบคิดจะเตือน พอรัดเกณฑ์
#  ให้เข้มขึ้น ระบบก็เตือนน้อยลง เขียน log น้อยลง จนไม่เหลือข้อมูลให้จูน
#  และถ้าเกณฑ์เข้มเกินจนพลาดฝนจริง จะไม่มีอะไรบันทึกไว้ให้รู้เลย
#  = ยิ่งตั้งเข้ม ยิ่งมองไม่เห็นความผิดพลาดของตัวเอง
#
#  ไฟล์นี้จึงจดค่าที่วัดได้ทุก 20 นาทีตลอดวัน (~72 แถว/วัน) โดยไม่ส่งข้อความ
#  ไม่มีช่องให้กรอกมือ เพราะกรอก 72 แถว/วันเป็นไปไม่ได้ — ผลจริงมาจาก
#  rain_times.txt ที่จดแค่ "ฝนตกช่วงไหน" แล้ว analyze_alerts.py จับคู่ให้เอง
# ---------------------------------------------------------------------
WATCH_LOG = "radar_watch.csv"
WATCH_COLUMNS = ["เวลา", "เรดาร์คลุมวงแคบ(%)", "เรดาร์คลุมวงกว้าง(%)",
                 "ตัดสินว่าฝนตกเหนือจุดนี้", "ฝนเข้าใน30นาที",
                 "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)", "โมเดลตรงกัน",
                 "จำนวนโมเดล", "TMD_WRF(มม.)", "CAPE",
                 "ความกดอากาศเปลี่ยน(hPa)", "ระดับที่จะเตือน", "ทริกเกอร์",
                 "ส่งจริง"]


# ระดับความรุนแรง — ใช้ตัดสินว่าจะเตือนซ้ำหรือปลุกกลางดึกไหม
#  "radar_soon" เคยตกหล่นจากตารางนี้ ทำให้ได้ rank 0 เท่ากับ "clear"
#  ผลคือการเตือน "ฝนกำลังเข้าใน 30 นาที" ถูก cooldown และช่วงงดรบกวน
#  กดทิ้งแทบทุกครั้ง ทั้งที่เป็นการเตือนที่มีเวลาให้เตรียมตัวมากที่สุด
SEVERITY_RANK = {
    "clear": 0, "heat": 2, "gust": 3, "rain": 3,
    "radar_soon": 4, "radar_now": 4, "pressure": 4,
    "heavy": 5, "storm": 5, "very_heavy": 6, "tide": 6,
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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or "ใส่_" in TELEGRAM_TOKEN:
        print("!! ยังไม่ได้ตั้งค่า TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
        print("   บนเครื่องตัวเอง: สร้างไฟล์ telegram_token.txt และ telegram_chat_id.txt")
        print("   บน GitHub Actions: ตั้งใน Settings > Secrets and variables > Actions")
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


# ---------------------------------------------------------------------
#  โครงคอลัมน์ของ alert_log.csv
# ---------------------------------------------------------------------
#  ช่อง "ฝนตกจริง(กรอกเอง Y/N)" ต้องเป็นคอลัมน์สุดท้ายเสมอ เพราะเป็นช่อง
#  ที่ต้องกรอกมือผ่านหน้าเว็บ GitHub อยู่ท้ายสุดแล้วหาง่ายที่สุด
#
#  บทเรียนจากของจริง: เวอร์ชันแรกมี 7 คอลัมน์ พอเพิ่มเป็น 10 คอลัมน์
#  หัวตารางไม่ถูกเขียนใหม่ (เพราะเขียนเฉพาะตอนไฟล์ยังไม่มี) ทำให้
#  analyze_alerts.py อ่านคอลัมน์เพี้ยนทั้งไฟล์ และมองไม่เห็นผลที่กรอกไว้
#  ทั้ง 26 แถวเลย — ข้อมูลที่นั่งกรอกมาทั้งสัปดาห์สูญเปล่า
#  จึงต้องมีตัวย้ายสคีมาอัตโนมัติ ไม่ใช่แค่เขียนหัวตารางตอนสร้างไฟล์
# ---------------------------------------------------------------------
LOG_COLUMNS = ["เวลา", "ระดับ", "ทริกเกอร์", "ฝนที่ทำนาย(มม./ชม.)",
               "โอกาสฝน(%)", "โมเดลตรงกัน", "จำนวนโมเดล", "TMD_WRF(มม.)",
               "เรดาร์เห็นฝน", "เรดาร์คลุมวงแคบ(%)", "เรดาร์คลุมวงกว้าง(%)",
               "ส่งจริง", "ฝนตกจริง(กรอกเอง Y/N)"]

# สคีมาเก่าที่เคยใช้ อ้างอิงด้วย "จำนวนคอลัมน์" เพราะแถวเก่าไม่มีอะไรระบุเวอร์ชัน
LEGACY_LAYOUTS = {
    7:  ["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)",
         "เรดาร์เห็นฝน", "ส่งจริง", "ฝนตกจริง(กรอกเอง Y/N)"],
    10: ["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)", "โมเดลตรงกัน",
         "จำนวนโมเดล", "TMD_WRF(มม.)", "เรดาร์เห็นฝน", "ส่งจริง",
         "ฝนตกจริง(กรอกเอง Y/N)"],
}


def migrate_log():
    """
    ย้ายไฟล์ log เก่าให้เข้าโครงคอลัมน์ปัจจุบัน โดยรักษาค่าที่กรอกมือไว้ครบ

    เดาสคีมาของแต่ละแถวจาก "จำนวนคอลัมน์" ไม่ใช่จากหัวตาราง เพราะหัวตาราง
    นั่นแหละที่เคยค้างเป็นของเก่า แถวไหนกว้างเท่าไรก็แปลตามสคีมานั้น
    เรียกทุกครั้งก่อนเขียน log — ถ้าโครงตรงอยู่แล้วจะไม่แตะไฟล์
    """
    import csv, os as _os
    if not _os.path.exists(ALERT_LOG):
        return
    with open(ALERT_LOG, encoding="utf-8-sig", newline="") as fp:
        rows = [r for r in csv.reader(fp) if r]
    if not rows:
        return
    if rows[0] == LOG_COLUMNS:
        return                      # ตรงอยู่แล้ว ไม่ต้องทำอะไร

    out = []
    for r in rows[1:]:              # ข้ามหัวตารางเก่า
        layout = LOG_COLUMNS if len(r) == len(LOG_COLUMNS) else LEGACY_LAYOUTS.get(len(r))
        if layout is None:
            # ความกว้างไม่รู้จัก — อย่างน้อยรักษาเวลาและค่าที่กรอกมือ (ช่องสุดท้าย) ไว้
            d = {"เวลา": r[0] if r else "", "ฝนตกจริง(กรอกเอง Y/N)": r[-1] if r else ""}
        else:
            d = dict(zip(layout, r))
        out.append([d.get(c, "") for c in LOG_COLUMNS])

    with open(ALERT_LOG, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(LOG_COLUMNS)
        w.writerows(out)
    print(f"  ย้ายโครงคอลัมน์ alert_log.csv เป็นเวอร์ชันใหม่แล้ว ({len(out)} แถว)")


def log_alert(severity, forecast, radar, sent, triggers=None):
    """
    บันทึกทุกครั้งที่ระบบ "คิดจะเตือน" ลงไฟล์ CSV
    ไว้ย้อนดูภายหลังว่าที่เตือนไปนั้นฝนตกจริงกี่ครั้ง
    ช่องสุดท้าย rain_actual เว้นไว้ให้กรอกเองว่าตกจริงไหม (Y/N)

    บันทึก triggers ทุกตัวที่ทำงาน ไม่ใช่แค่ severity ตัวเดียว เพราะ severity
    เก็บได้แค่ตัวที่รุนแรงที่สุด ทำให้วิเคราะห์ย้อนหลังไม่ได้ว่าตัวไหนกันแน่
    ที่ทำให้เตือนผิด — ซึ่งเป็นคำถามสำคัญที่สุดในการจูนระบบ

    บันทึก % พื้นที่ที่เรดาร์เห็นฝนด้วย (ไม่ใช่แค่ yes/no) เพื่อให้สัปดาห์หน้า
    จูนเกณฑ์ RADAR_OVER_COVERAGE จากข้อมูลจริงได้ แทนที่จะเดาเอา
    """
    try:
        import csv, os as _os
        migrate_log()
        new = not _os.path.exists(ALERT_LOG)
        mx = max((f["rain_mm"] for f in forecast), default=0) if forecast else 0
        mp = max((f["prob"] for f in forecast), default=0) if forecast else 0
        ag = max((f["agree"] for f in forecast), default=0) if forecast else 0
        nm = max((f["n_models"] for f in forecast), default=0) if forecast else 0
        rd = co = cn = ""
        det = (radar or {}).get("rain_detected")
        if det:
            rd = "yes" if det.get("now") else "no"
            co = f"{det.get('cover_over', 0) * 100:.0f}"
            cn = f"{det.get('cover_near', 0) * 100:.0f}"
        with open(ALERT_LOG, "a", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(LOG_COLUMNS)
            tmds = [f.get("tmd_mm") for f in (forecast or [])
                    if f.get("tmd_mm") is not None]
            td = f"{max(tmds):.1f}" if tmds else ""
            w.writerow([f"{now_th():%Y-%m-%d %H:%M}", severity,
                        "|".join(triggers or []),
                        f"{mx:.1f}", f"{mp:.0f}", ag, nm, td, rd, co, cn,
                        "yes" if sent else "no", ""])
    except Exception as e:
        print(f"  บันทึก log ไม่ได้: {e}")


def watch_log(forecast, radar, severity, triggers, sent, slp_delta):
    """
    จดค่าที่วัดได้ลง radar_watch.csv ทุกรอบที่รัน ไม่ว่าจะเตือนหรือไม่

    เรียกก่อนที่ main() จะ return ทุกทางออก เพราะรอบที่ "ไม่เตือน" คือรอบที่
    มีค่าที่สุดในการจูน — ถ้าฝนตกจริงในรอบที่ระบบเงียบ นั่นคือการพลาด
    ซึ่งเป็นสิ่งเดียวที่ alert_log.csv บอกเราไม่ได้เลย
    """
    try:
        import csv, os as _os
        det = (radar or {}).get("rain_detected") or {}
        f = forecast or []
        capes = [x["cape"] for x in f if x.get("cape") is not None]
        tmds = [x.get("tmd_mm") for x in f if x.get("tmd_mm") is not None]
        new = not _os.path.exists(WATCH_LOG)
        with open(WATCH_LOG, "a", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            if new:
                w.writerow(WATCH_COLUMNS)
            w.writerow([
                f"{now_th():%Y-%m-%d %H:%M}",
                f"{det.get('cover_over', 0) * 100:.0f}" if det else "",
                f"{det.get('cover_near', 0) * 100:.0f}" if det else "",
                "yes" if det.get("now") else "no" if det else "",
                "yes" if det.get("in_30min") else "no" if det else "",
                f"{max((x['rain_mm'] for x in f), default=0):.1f}",
                f"{max((x['prob'] for x in f), default=0):.0f}",
                max((x["agree"] for x in f), default=0),
                max((x["n_models"] for x in f), default=0),
                f"{max(tmds):.1f}" if tmds else "",
                f"{max(capes):.0f}" if capes else "",
                f"{slp_delta:.1f}" if slp_delta is not None else "",
                severity or "",
                "|".join(triggers or []),
                "yes" if sent else "no",
            ])
    except Exception as e:
        print(f"  จด radar_watch ไม่ได้: {e}")


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
    อ่านภาพ tile เรดาร์ตรงพิกัดบ้าน แล้ววัดว่ามีฝนคลุมพื้นที่กี่ %
    ต้องมี Pillow (pip install pillow) — ถ้าไม่มีจะข้ามไป คืนค่า None

    คืนค่า dict:
      now         ฝนคลุมวงแคบ (RADAR_OVER_KM) เกินเกณฑ์ = ตกอยู่เหนือจุดนี้จริง
      in_30min    เฟรม nowcast ข้างหน้าคลุมวงแคบเกินเกณฑ์
      near_now    มีฝนที่ไหนก็ได้ในวงกว้าง (RADAR_NEAR_KM)
      cover_over  สัดส่วนพื้นที่วงแคบที่มีฝน 0.0-1.0  (ไว้ใส่ในข้อความและ log)
      cover_near  สัดส่วนพื้นที่วงกว้างที่มีฝน 0.0-1.0

    หมายเหตุสำคัญ 3 ข้อ (แก้จากเวอร์ชันก่อน ๆ ที่ผิด):
      1) RainViewer ชั้นฟรีรองรับ tile ถึงระดับซูม 7 เท่านั้น
         ถ้าขอซูมสูงกว่านี้ เซิร์ฟเวอร์จะส่งภาพที่มีข้อความ
         "Zoom Level Not Supported" กลับมา ซึ่งมีพิกเซลทึบเต็มภาพ
         ทำให้ตรวจว่า "มีฝน" ทั้งที่ไม่มี — เป็น false positive ร้ายแรง
      2) ต้องคำนวณตำแหน่งพิกเซลจริงภายใน tile ไม่ใช่ดูกลาง tile
         เพราะที่ซูม 7 หนึ่ง tile กว้างราว 300 กม.
      3) ขอภาพแบบ smooth=0 ไม่ใช่ smooth=1 เพราะการเกลี่ยสีทำให้ขอบก้อนฝน
         ฟุ้งออกไปกว้างกว่าของจริง แล้วไปพองตัวเลข % พื้นที่ที่วัดได้
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
    rad_over = max(2, int(RADAR_OVER_KM / km_per_px))   # วงแคบ = เหนือจุดนี้
    rad_near = max(3, int(RADAR_NEAR_KM / km_per_px))   # วงกว้าง = แถวนี้

    def tile_coverage(path):
        """คืน (สัดส่วนฝนในวงแคบ, สัดส่วนฝนในวงกว้าง) — วัดทั้งสองวงในรอบเดียว"""
        # color scheme 4 = universal blue, smooth=0, snow=0
        url = f"{host}{path}/{TILE_PX}/{ZOOM}/{x}/{y}/4/0_0.png"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                return 0.0, 0.0
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            w, h = img.size
            cx, cy = int(fx * w), int(fy * h)

            hit_o = tot_o = hit_n = tot_n = 0
            for px in range(cx - rad_near, cx + rad_near + 1):
                for py in range(cy - rad_near, cy + rad_near + 1):
                    if not (0 <= px < w and 0 <= py < h):
                        continue          # จุดที่ล้นออกนอก tile ข้ามไป
                    d2 = (px - cx) ** 2 + (py - cy) ** 2
                    if d2 > rad_near ** 2:
                        continue          # นับเฉพาะในวงกลม ไม่ใช่สี่เหลี่ยม
                    wet = img.getpixel((px, py))[3] > RADAR_ALPHA_MIN
                    tot_n += 1
                    if wet:
                        hit_n += 1
                    if d2 <= rad_over ** 2:   # วงแคบซ้อนอยู่ในวงกว้าง นับซ้ำได้เลย
                        tot_o += 1
                        if wet:
                            hit_o += 1
            return (hit_o / tot_o if tot_o else 0.0,
                    hit_n / tot_n if tot_n else 0.0)
        except Exception:
            return 0.0, 0.0

    res = {"now": False, "in_30min": False, "near_now": False,
           "cover_over": 0.0, "cover_near": 0.0}

    if past:
        co, cn = tile_coverage(past[-1]["path"])
        res["cover_over"], res["cover_near"] = co, cn
        res["now"] = co >= RADAR_OVER_COVERAGE
        res["near_now"] = cn >= RADAR_NEAR_COVERAGE

    if nowcast:
        # เฟรม nowcast แรก ๆ = อีกประมาณ 10-30 นาทีข้างหน้า
        # ใช้เกณฑ์วงแคบเหมือนกัน เพราะคำถามคือ "ฝนจะมาถึงจุดนี้ไหม"
        # ไม่ใช่ "มีฝนอยู่ที่ไหนสักแห่งในภาพไหม"
        for f in nowcast[:3]:
            co, _ = tile_coverage(f["path"])
            if co >= RADAR_OVER_COVERAGE:
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

# =====================================================================
#  สรุปอากาศประจำวัน — คนละเรื่องกับการเตือน
# =====================================================================
#  การเตือนตอบคำถาม "ตอนนี้ต้องรีบทำอะไรไหม" มองล่วงหน้า 3 ชม.
#  สรุปเช้าตอบคำถาม "วันนี้จะวางแผนงานยังไง" ต้องมองทั้งวัน
#  ข้อมูลคนละชุดกัน จึงแยกฟังก์ชันดึงและฟังก์ชันประกอบข้อความออกจากกัน
#  ไม่เอาไปปนกับ build_message() ที่ต้องเงียบให้มากที่สุด
# =====================================================================

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

# รหัสสภาพอากาศ WMO ที่ Open-Meteo ใช้ (เอาเฉพาะที่เจอได้จริงในไทย)
WMO_TEXT = {
    0: "ฟ้าโปร่ง", 1: "ฟ้าโปร่งเป็นส่วนใหญ่", 2: "มีเมฆบางส่วน", 3: "เมฆมาก",
    45: "หมอก", 48: "หมอกน้ำค้างแข็ง",
    51: "ฝนละอองเบา", 53: "ฝนละออง", 55: "ฝนละอองหนัก",
    61: "ฝนเล็กน้อย", 63: "ฝนปานกลาง", 65: "ฝนหนัก",
    80: "ฝนซู่เล็กน้อย", 81: "ฝนซู่", 82: "ฝนซู่หนัก",
    95: "ฝนฟ้าคะนอง", 96: "ฝนฟ้าคะนองมีลูกเห็บ", 99: "ฝนฟ้าคะนองรุนแรง",
}


def thai_date(d):
    """3 ส.ค. 2569 (พ.ศ.) — ปฏิทินไทยใช้ปีพุทธศักราช = ค.ศ. + 543"""
    return f"{THAI_DAYS[d.weekday()]} {d.day} {THAI_MONTHS[d.month-1]} {d.year + 543}"


def fetch_day_outlook():
    """
    ดึงภาพรวมทั้งวันสำหรับสรุปตอนเช้า

    ใช้โมเดลรวมของ Open-Meteo (best_match) ตัวเดียว ไม่ทำ consensus หลายโมเดล
    เพราะสรุปเช้าไม่ได้ตัดสินใจอะไรแทนคน แค่บอกภาพรวมให้วางแผนงาน
    ความเรียบง่ายและไม่พังสำคัญกว่าความละเอียดตรงนี้

    คืน dict หรือ None
    """
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
            "latitude": LAT, "longitude": LON, "timezone": "Asia/Bangkok",
            "forecast_days": 1,
            "daily": ("weather_code,temperature_2m_max,temperature_2m_min,"
                      "apparent_temperature_max,precipitation_sum,"
                      "precipitation_probability_max,wind_speed_10m_max,"
                      "wind_gusts_10m_max,wind_direction_10m_dominant,"
                      "uv_index_max,sunrise,sunset"),
            "hourly": "precipitation,precipitation_probability,cloud_cover",
        })
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ดึงภาพรวมรายวันไม่ได้: {e}")
        return None

    d = data.get("daily") or {}
    if not d.get("time"):
        return None

    def first(key, default=None):
        v = d.get(key) or []
        return v[0] if v and v[0] is not None else default

    h = data.get("hourly") or {}
    hours = []
    for i, t in enumerate(h.get("time") or []):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue

        def at(key):
            arr = h.get(key) or []
            return arr[i] if i < len(arr) and arr[i] is not None else None

        hours.append({"time": dt, "rain": at("precipitation") or 0,
                      "prob": at("precipitation_probability") or 0,
                      "cloud": at("cloud_cover")})

    return {
        "date": datetime.fromisoformat(d["time"][0]),
        "code": first("weather_code"),
        "tmax": first("temperature_2m_max"), "tmin": first("temperature_2m_min"),
        "feels": first("apparent_temperature_max"),
        "rain_sum": first("precipitation_sum", 0) or 0,
        "rain_prob": first("precipitation_probability_max", 0) or 0,
        "wind": first("wind_speed_10m_max", 0) or 0,
        "gust": first("wind_gusts_10m_max", 0) or 0,
        "wind_dir": first("wind_direction_10m_dominant"),
        "uv": first("uv_index_max"),
        "sunrise": first("sunrise"), "sunset": first("sunset"),
        "hours": hours,
    }


def rain_windows(hours, prob_min=50, mm_min=0.2):
    """
    รวมชั่วโมงที่น่าจะมีฝนให้เป็น "ช่วง" แทนที่จะไล่ทีละชั่วโมง

    คนอ่าน "บ่าย 2 ถึง 4 โมง" เข้าใจทันที แต่ "14:00, 15:00, 16:00"
    ต้องแปลในหัวอีกที — ข้อความตอนเช้าควรอ่านจบในครั้งเดียว
    """
    wet = [h for h in hours if h["prob"] >= prob_min or h["rain"] >= mm_min]
    out = []
    for h in sorted(wet, key=lambda x: x["time"]):
        if out and (h["time"] - out[-1][-1]["time"]).total_seconds() <= 3600:
            out[-1].append(h)
        else:
            out.append([h])
    return out


#  ช่วงเวลาทำงานกลางแจ้ง ใช้ตัดสินว่าฝนช่วงนั้นกระทบงานจริงไหม
WORK_START, WORK_END = 7, 17


def build_daily_summary(day, tmd_warning=None):
    """ประกอบข้อความสรุปอากาศประจำวัน — คืน str"""
    # ตัดชั่วโมงที่ผ่านไปแล้วออกก่อนทุกอย่าง
    # ไม่งั้นสรุปตอน 07:00 จะรายงานฝนที่ตกไปแล้วตอนตี 2 ว่ากำลังจะมา
    now = now_th().replace(tzinfo=None)
    day = dict(day)
    day["hours"] = [h for h in day["hours"] if h["time"] >= now - timedelta(hours=1)]

    L = []
    L.append(f"🌤️ <b>สรุปอากาศวันนี้ · {PLACE_NAME}</b>")
    L.append(f"{thai_date(day['date'])}\n")

    if day["code"] is not None:
        desc = WMO_TEXT.get(day["code"], f"รหัสสภาพอากาศ {day['code']}")
        L.append(f"📖 ภาพรวม: {desc}")

    # --- แดดกับเมฆ (ดูเฉพาะช่วงเวลาทำงาน 07-17 น.) ---
    work = [h for h in day["hours"] if 7 <= h["time"].hour <= 17 and h["cloud"] is not None]
    if work:
        avg = sum(h["cloud"] for h in work) / len(work)
        if avg < 30:
            sun = "แดดจัดเกือบทั้งวัน ☀️"
        elif avg < 60:
            sun = "แดดสลับเมฆ ⛅"
        elif avg < 85:
            sun = "เมฆมาก แดดน้อย ☁️"
        else:
            sun = "ครึ้มทั้งวัน แทบไม่มีแดด 🌥️"
        L.append(f"☀️ แดด: {sun} (เมฆเฉลี่ย {avg:.0f}%)")

    # --- อุณหภูมิ ---
    if day["tmin"] is not None and day["tmax"] is not None:
        t = f"🌡️ อุณหภูมิ {day['tmin']:.0f}–{day['tmax']:.0f}°C"
        if day["feels"] is not None and day["feels"] - day["tmax"] >= 2:
            t += f" (รู้สึกเหมือน {day['feels']:.0f}°C)"
        L.append(t)

    # --- ฝน ---
    wins = rain_windows(day["hours"])
    # โอกาสฝนต้องคิดจากชั่วโมงที่ "เหลือของวัน" ไม่ใช่ค่าสูงสุดทั้งวันที่ API ให้มา
    # เพราะค่านั้นรวมชั่วโมงที่ผ่านไปแล้ว ทำให้ได้ข้อความขัดกันเองแบบ
    # "ไม่มีช่วงฝนชัดเจน แต่โอกาสฝน 85%" ทั้งที่ 85% นั้นคือฝนที่ตกไปแล้วตอนตี 2
    prob_left = max((h["prob"] for h in day["hours"]), default=0)
    if wins:
        parts = []
        for w in wins[:3]:
            a, b = w[0]["time"], w[-1]["time"] + timedelta(hours=1)
            mm = sum(x["rain"] for x in w)
            pk = max(x["prob"] for x in w)
            parts.append(f"{a:%H:%M}–{b:%H:%M} ({mm:.1f} มม. · โอกาส {pk:.0f}%)")
        L.append("🌧️ ฝน: " + " และ ".join(parts))
    elif prob_left >= 30:
        L.append(f"🌧️ ฝน: ไม่มีช่วงชัดเจน แต่โอกาสฝนที่เหลือของวัน {prob_left:.0f}%")
    else:
        L.append(f"🌧️ ฝน: ไม่มีสัญญาณฝน (โอกาสสูงสุด {prob_left:.0f}%)")

    # --- ลม ---
    wind = f"💨 ลม {day['wind']:.0f} กม./ชม."
    wc = wind_compass(day["wind_dir"])
    if wc:
        wind += f" จากทิศ{wc['from_th']} ({wc['from_code']}) {wc['arrow']}"
    if day["gust"]:
        wind += f" · กระโชกสูงสุด {day['gust']:.0f}"
    L.append(wind)

    # --- UV กับเวลาพระอาทิตย์ ---
    if day["uv"] is not None:
        uv = day["uv"]
        lvl = ("ต่ำ" if uv < 3 else "ปานกลาง" if uv < 6 else
               "สูง" if uv < 8 else "สูงมาก" if uv < 11 else "อันตราย")
        L.append(f"🕶️ UV สูงสุด {uv:.0f} ({lvl})")
    if day["sunrise"] and day["sunset"]:
        try:
            sr = datetime.fromisoformat(day["sunrise"])
            ss = datetime.fromisoformat(day["sunset"])
            L.append(f"🌅 พระอาทิตย์ขึ้น {sr:%H:%M} · ตก {ss:%H:%M}")
        except Exception:
            pass

    if tmd_warning:
        L.append(f"\n⚠️ <b>ประกาศเตือนภัยกรมอุตุฯ</b>\n{tmd_warning}")

    # --- คำแนะนำสำหรับงาน — ให้เฉพาะที่ตรงกับสภาพวันนี้จริง ๆ ---
    tips = []
    if wins:
        a = wins[0][0]["time"]
        # ฝนหลังเลิกงานไม่ต้องสั่งให้รีบทำงานให้เสร็จก่อน — คำแนะนำต้องตรงบริบท
        # ไม่งั้นคนอ่านจะเริ่มไม่เชื่อถือข้อความทั้งฉบับ
        if a.hour < WORK_END:
            if a.hour <= WORK_START:
                tips.append("ฝนมาตั้งแต่เช้า — เลื่อนงานเทปูน/งานสีไปช่วงบ่ายถ้าทำได้")
            else:
                tips.append(f"วางงานเทปูน/งานสีให้เสร็จก่อน {a:%H:%M} น.")
            tips.append("เตรียมผ้าใบคลุมวัสดุและกองทรายไว้ล่วงหน้า")
        else:
            tips.append(f"ฝนมาช่วง {a:%H:%M} น. หลังเลิกงานแล้ว "
                        f"งานกลางวันไม่กระทบ — คลุมของให้เรียบร้อยก่อนกลับ")
    if day["gust"] and day["gust"] >= GUST_ALERT:
        tips.append(f"ลมกระโชกถึง {day['gust']:.0f} กม./ชม. — ระวังงานนั่งร้าน เครน ผ้าใบ")
    if day["feels"] is not None and day["feels"] >= HEAT_ALERT:
        tips.append(f"อากาศร้อนจัด (รู้สึก {day['feels']:.0f}°C) — เพิ่มรอบพัก เตรียมน้ำดื่ม")
    if day["uv"] is not None and day["uv"] >= 8:
        tips.append("UV สูง — ใส่แขนยาว หมวก และครีมกันแดดสำหรับคนงานกลางแจ้ง")
    if not tips:
        tips.append("สภาพอากาศเอื้อต่อการทำงานกลางแจ้ง ไม่มีข้อควรระวังพิเศษ")
    L.append("\n📋 <b>สำหรับงานวันนี้</b>\n" + "\n".join(f"• {t}" for t in tips))

    L.append("\n<i>ที่มา: Open-Meteo / กรมอุตุนิยมวิทยา</i>")
    return "\n".join(L)


def build_message(forecast, radar, warning, always_send=False, tide_clash=None,
                  persistence_ok=True, slp_delta=None, slp_span=0):
    """
    สร้างข้อความแจ้งเตือน คืนค่า (text, severity_key, triggers)
    หรือ (None, None, []) ถ้าไม่ต้องเตือน

    always_send=True  → ส่งข้อความเสมอแม้ไม่มีฝน (ใช้กับสรุปประจำวันตอนเช้า)
    slp_delta/slp_span → แนวโน้มความกดอากาศจาก TMD (ดู tmd_pressure_trend())

    โครงข้อความแบ่งเป็นสองส่วนชัดเจน:
      lines = เหตุผลที่ "เตือน" จริง ๆ
      info  = ข้อมูลประกอบที่ไม่ได้ทำให้เตือน (เช่น ความกดอากาศ, CAPE)
              แยกไว้ท้ายข้อความ เพื่อไม่ให้ปนกับเหตุผลที่ต้องลงมือทำอะไร
    triggers = รายชื่อทริกเกอร์ทั้งหมดที่ทำงาน ไว้เขียนลง alert_log.csv
               เพื่อให้วิเคราะห์ย้อนหลังได้ว่าตัวไหนแม่นตัวไหนมั่ว
    """

    def _bump(sev, candidate):
        """ยกระดับ severity เฉพาะเมื่อ candidate รุนแรงกว่าที่มีอยู่แล้วเท่านั้น
        (กันไม่ให้สัญญาณที่มาทีหลังในโค้ดไปเบียดสัญญาณที่รุนแรงกว่าซึ่งเจอไปก่อนหน้า)"""
        return candidate if SEVERITY_RANK.get(sev, 0) < SEVERITY_RANK.get(candidate, 0) else sev
    lines = []
    info = []
    triggers = []
    severity = None
    t_now = now_th().strftime("%H:%M")

    # --- ฝนหนักตรงกับน้ำขึ้นสูง (เฉพาะพื้นที่ปากแม่น้ำ) ---
    if tide_clash:
        lines.append(f"🌊 <b>ฝนหนักตรงกับน้ำขึ้นสูง</b>\n{tide_clash}")
        severity = "tide"
        triggers.append("tide")

    # --- ประกาศเตือนภัย ---
    if warning:
        lines.append(f"⚠️ <b>ประกาศเตือนภัย</b>\n{warning}")
        severity = "warning"
        triggers.append("warning")

    # ---------------------------------------------------------------
    #  เรดาร์ nowcast
    # ---------------------------------------------------------------
    #  บอกตัวเลขที่วัดได้จริงไปเลย ไม่ใช่แค่ "มีฝน/ไม่มีฝน"
    #  เพราะ "ฝนคลุม 80% ของรัศมี 6 กม." กับ "คลุม 26%" ต่างกันมาก
    #  ในแง่ว่าควรหยุดงานเลยหรือแค่เตรียมตัว แต่เดิมสองกรณีนี้ขึ้นข้อความเดียวกัน
    # ---------------------------------------------------------------
    if radar and radar.get("rain_detected"):
        rd = radar["rain_detected"]
        over = rd.get("cover_over", 0.0) * 100
        near = rd.get("cover_near", 0.0) * 100
        if rd.get("now"):
            lines.append(f"📡 <b>เรดาร์: ฝนตกอยู่เหนือ{PLACE_NAME}แล้ว</b>\n"
                         f"ฝนคลุม {over:.0f}% ของรัศมี {RADAR_OVER_KM} กม.รอบจุดนี้")
            severity = severity or "radar_now"
            triggers.append("radar_now")
        elif rd.get("in_30min"):
            lines.append(f"📡 <b>เรดาร์: กลุ่มฝนกำลังเข้า{PLACE_NAME}</b> ใน ~30 นาที")
            severity = severity or "radar_soon"
            triggers.append("radar_soon")
        elif rd.get("near_now"):
            # มีฝนในวงกว้างแต่ยังไม่ถึงจุดเรา — เป็นข้อมูลประกอบ ไม่ใช่เหตุผลเตือน
            # (เกณฑ์เดิมนับกรณีนี้เป็น "ฝนอยู่เหนือหัวแล้ว" = ที่มาของ false alarm)
            info.append(f"📡 มีกลุ่มฝนในรัศมี {RADAR_NEAR_KM} กม. "
                        f"(คลุม {near:.0f}%) แต่ยังไม่เข้า{PLACE_NAME}")

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
        #  กฎ: ถ้าเรดาร์ไม่เห็นฝนเลยแม้แต่ในวงกว้าง RADAR_NEAR_KM และฝนที่
        #      ทำนายยังไม่ถึงระดับหนัก → งดเตือน เพราะโอกาสเตือนผิดสูงกว่าถูก
        #      แต่ถ้าเป็นฝนหนัก (>= 7.5 มม./ชม.) เตือนเสมอ
        #      เพราะราคาของการพลาดสูงกว่าราคาของการเตือนเกิน
        #
        #  ใช้วงกว้าง (near) ไม่ใช่วงแคบ (over) ตรงนี้โดยตั้งใจ — คำถามคือ
        #  "มีฝนอยู่ในระบบอากาศแถบนี้ไหม" ถ้าไม่มีเลยแปลว่าโมเดลจินตนาการเอง
        #  ถ้าใช้วงแคบจะยับยั้งฝนที่กำลังเคลื่อนเข้ามาทิ้งไปด้วย
        # ---------------------------------------------------------------
        vetoed = False
        if RADAR_VETO and rain_hours and radar is not None:
            rd = radar.get("rain_detected")
            radar_clear = (rd is not None and not rd.get("near_now")
                           and not rd.get("in_30min"))
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
            triggers.append(sev)

            slots = ", ".join(
                f"{f['time'].strftime('%H:%M')} ({f['rain_mm']:.1f} มม.)"
                for f in rain_hours
            )
            conf = "—"
            if radar and radar.get("rain_detected") is not None:
                _rd = radar["rain_detected"]
                if _rd.get("now"):
                    conf = "เรดาร์ยืนยันแล้ว ✓"
                elif _rd.get("in_30min") or _rd.get("near_now"):
                    conf = "เรดาร์เห็นฝนใกล้ ๆ"
                else:
                    conf = "เรดาร์ยังไม่เห็นฝนเลย"
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
            triggers.append(f"tmd_cond{worst}")
            when = ", ".join(f["time"].strftime("%H:%M") for f in cond_hours[:3])
            label = TMD_COND_TEXT.get(worst, str(worst))
            icon = "⛈️" if worst == 8 else "🌧️"
            lines.append(f"{icon} <b>TMD ระบุสภาพอากาศ: {label}</b> (cond={worst})\n"
                         f"ช่วงเวลา: {when}")

        # ---------------------------------------------------------------
        #  ความเสี่ยงพายุฟ้าคะนอง (CAPE)
        # ---------------------------------------------------------------
        #  CAPE บอกว่า "บรรยากาศพร้อมจะเกิดพายุ" ไม่ได้บอกว่า "จะเกิด"
        #  ในเขตร้อนช่วงฤดูฝน CAPE เกิน 2500 เป็นเรื่องปกติแทบทุกบ่าย
        #  จาก alert_log.csv: ยิงไป 7 ครั้ง กรอกผลแล้ว 5 ครั้ง ตกจริง 0 ครั้ง
        #  จึงต้องมีหลักฐานว่ามีฝนจริงมายืนยันก่อน ถึงจะยกเป็นการเตือน
        # ---------------------------------------------------------------
        capes = [f["cape"] for f in forecast if f["cape"] is not None]
        if capes and max(capes) >= CAPE_ALERT:
            # หลักฐานต้องเป็นฝนที่ "ถึงตัวเราหรือกำลังจะถึง" เท่านั้น
            # จงใจไม่นับ near_now (ฝนที่ไหนก็ได้ในรัศมี 25 กม.) เพราะจาก log จริง
            # เงื่อนไขนั้นเป็นจริง 39/58 ครั้ง = แทบไม่ได้กรองอะไรเลย
            rd = (radar or {}).get("rain_detected") or {}
            has_evidence = (rd.get("now") or rd.get("in_30min")
                            or max_rain >= RAIN_MM_ALERT)
            if has_evidence or not REQUIRE_RAIN_EVIDENCE:
                severity = _bump(severity, "storm")
                triggers.append("cape")
                lines.append(f"⚡ <b>บรรยากาศไม่เสถียรมาก (CAPE {max(capes):.0f} J/kg)</b>\n"
                             f"เสี่ยงพายุฝนฟ้าคะนองรุนแรง ลมกระโชก และฟ้าผ่า\n"
                             f"→ เตรียมหยุดงานที่สูงและงานเครน ถอดปลั๊กเครื่องมือไฟฟ้า")
            else:
                info.append(f"⚡ CAPE {max(capes):.0f} J/kg — บรรยากาศพร้อมเกิดพายุ "
                            f"แต่ยังไม่มีฝนจริงทั้งในเรดาร์และโมเดล (เฝ้าระวังเฉย ๆ)")

        # --- ความร้อน (ความปลอดภัยคนงาน) ---
        heats = [f["heat"] for f in forecast if f["heat"] is not None]
        if heats and max(heats) >= HEAT_ALERT:
            severity = severity or "heat"
            triggers.append("heat")
            lines.append(f"🥵 <b>อุณหภูมิที่รู้สึกได้ {max(heats):.0f}°C</b>\n"
                         f"เสี่ยงตะคริวและเพลียแดด — เพิ่มรอบพัก จัดน้ำดื่มและจุดพักในร่ม")

        # --- ลมกระโชก (สำคัญกับงานก่อสร้าง) ---
        wind_hours = [f for f in forecast if f.get("tmd", {}).get("wd10m") is not None]
        if max_gust >= GUST_DANGER:
            severity = severity or "gust"
            triggers.append("gust")
            lines.append(f"💨 <b>ลมกระโชกแรงมาก {max_gust:.0f} กม./ชม.</b>\n"
                         f"→ ควรหยุดงานนั่งร้าน/เครน/ยกของสูง และรัดผ้าใบคลุมให้แน่น")
        elif max_gust >= GUST_ALERT:
            severity = severity or "gust"
            triggers.append("gust")
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

        # ---------------------------------------------------------------
        #  ความกดอากาศจาก TMD
        # ---------------------------------------------------------------
        #  เดิมเป็นทริกเกอร์เตือนเดี่ยว ๆ ผลจริงจาก alert_log.csv:
        #  ยิงไป 11 ครั้ง กรอกผลแล้ว 6 ครั้ง ตกจริง 0 ครั้ง
        #  ความกดอากาศลด 1.5 hPa ในเขตร้อนเกิดจากรอบวันปกติ (diurnal cycle)
        #  ได้เองอยู่แล้ว จึงไม่ใช่สัญญาณฝนที่เชื่อถือได้ในตัวมันเอง
        #  ย้ายไปเป็นข้อมูลประกอบ และยกเป็นการเตือนเมื่อมีฝนจริงยืนยันเท่านั้น
        # ---------------------------------------------------------------
        if slp_delta is not None and slp_delta <= -TMD_PRESSURE_DROP_ALERT:
            txt = f"ความกดอากาศลดลง {abs(slp_delta):.1f} hPa ใน {slp_span} ชม."
            if severity is not None or not REQUIRE_RAIN_EVIDENCE:
                # มีเหตุอื่นที่ต้องเตือนอยู่แล้ว — ตรงนี้ช่วยเสริมว่าระบบกำลังก่อตัว
                triggers.append("pressure")
                lines.append(
                    f"🇹🇭 <b>{txt}</b>\n"
                    f"สัญญาณระบบความกดอากาศต่ำ/พายุเข้าใกล้ — เสริมว่าสถานการณ์"
                    f"มีแนวโน้มแย่ลงต่อเนื่อง"
                )
            else:
                info.append(f"🇹🇭 {txt} (ยังไม่มีฝนจริงยืนยัน)")

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
            # ข้อมูลประกอบ (ความกดอากาศ/CAPE/ฝนรอบนอก) ยังมีค่าในสรุปเช้า
            # เพราะเป็นภาพรวมว่าวันนี้ต้องเฝ้าอะไรบ้าง แม้ยังไม่ถึงขั้นเตือน
            side = ("\n\n<b>ข้อมูลประกอบ</b>\n" + "\n".join(info)) if info else ""
            return (f"✅ <b>{PLACE_NAME}</b> {t_now} — ไม่มีฝนใน {LOOKAHEAD_HOURS} ชม.ข้างหน้า "
                    f"ไม่มีประกาศเตือนภัย{extra}{side}"
                    f"\n<i>ที่มา: กรมอุตุนิยมวิทยา / Open-Meteo</i>"), "clear", triggers
        return None, None, []

    header = f"🌏 <b>เตือนสภาพอากาศ {PLACE_NAME}</b>  ({t_now})"

    body = "\n\n".join(lines)

    # ข้อมูลประกอบต่อท้าย — คั่นให้ชัดว่าไม่ใช่เหตุผลที่เตือน
    # เพื่อไม่ให้คนอ่านเข้าใจผิดว่าต้องลงมือทำอะไรกับบรรทัดพวกนี้
    if info:
        body += "\n\n— — —\n<i>ข้อมูลประกอบ (ยังไม่ถึงขั้นต้องเตือน)</i>\n" + "\n".join(info)

    footer = "\n<i>ที่มา: กรมอุตุนิยมวิทยา / Open-Meteo / RainViewer</i>"
    if radar and radar.get("map_url"):
        footer = f"\n<a href=\"{radar['map_url']}\">ดูเรดาร์สด</a>" + footer

    return header + "\n\n" + body + footer, severity, triggers


# =====================================================================
#  MAIN
# =====================================================================

def main():
    ap = argparse.ArgumentParser(description="เตือนฝนบางปะกง เข้า Telegram")
    ap.add_argument("--test", action="store_true",
                    help="ส่งข้อความทดสอบเข้า Telegram แล้วจบ")
    ap.add_argument("--force", action="store_true",
                    help="ส่งข้อความเสมอ แม้ไม่มีฝน และข้าม cooldown")
    ap.add_argument("--daily", action="store_true",
                    help="ส่งสรุปอากาศทั้งวัน (ใช้กับงานตอนเช้า 07:00 น.)")
    args = ap.parse_args()

    if args.test:
        ok = send_telegram("✅ ทดสอบระบบเตือนฝนบางปะกง — เชื่อมต่อ Telegram สำเร็จแล้ว")
        sys.exit(0 if ok else 1)

    # -----------------------------------------------------------------
    #  โหมดสรุปประจำวัน — จบในตัว ไม่แตะ cooldown/state ของฝั่งเตือน
    #  เพราะสรุปเช้าไม่ใช่การเตือน ไม่ควรไปกิน cooldown จนการเตือนจริง
    #  ในชั่วโมงถัดมาถูกกดทิ้ง
    # -----------------------------------------------------------------
    if args.daily:
        print(f"[{now_th():%Y-%m-%d %H:%M:%S}] สรุปอากาศประจำวัน {PLACE_NAME}")
        day = fetch_day_outlook()
        if not day:
            print("  ดึงข้อมูลไม่ได้ ไม่ส่ง")
            sys.exit(1)
        text = build_daily_summary(day, fetch_tmd_warning())
        print("--- ข้อความ ---")
        print(text)
        sys.exit(0 if send_telegram(text) else 1)

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
            print(f"  เรดาร์: เหนือจุดนี้={rd['now']} (คลุม {rd['cover_over']*100:.0f}% "
                  f"ของรัศมี {RADAR_OVER_KM} กม.)  ใน 30 นาที={rd['in_30min']}  "
                  f"แถวนี้={rd['near_now']} (คลุม {rd['cover_near']*100:.0f}% "
                  f"ของรัศมี {RADAR_NEAR_KM} กม.)")
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

    text, severity, triggers = build_message(
        forecast, radar, warning,
        always_send=args.force, tide_clash=tide_clash,
        persistence_ok=persist_ok,
        slp_delta=slp_delta, slp_span=slp_span)
    if triggers:
        print(f"  ทริกเกอร์ที่ทำงาน: {', '.join(triggers)}")

    # บันทึกชั่วโมงที่เข้าเกณฑ์ไว้เทียบรอบหน้าเสมอ แม้จะไม่ได้ส่งข้อความ
    state["last_rain_hours"] = cur_hours
    save_state(state)

    if text is None:
        print("  → ไม่มีอะไรต้องเตือน ไม่ส่งข้อความ")
        # จดไว้ด้วยเสมอ — รอบที่เงียบคือรอบที่บอกเราได้ว่าเกณฑ์เข้มเกินไปหรือเปล่า
        watch_log(forecast, radar, severity, triggers, False, slp_delta)
        return

    rank = SEVERITY_RANK.get(severity, 0)

    # ช่วงเวลาห้ามปลุก — ผ่านได้เฉพาะเรื่องรุนแรงจริง
    if not args.force and in_quiet_hours() and rank < QUIET_MIN_RANK:
        print(f"  → อยู่ในช่วงงดรบกวน ({QUIET_START}:00-{QUIET_END}:00) "
              f"และความรุนแรงระดับ {rank} ยังไม่ถึงเกณฑ์ปลุก ({QUIET_MIN_RANK}) ไม่ส่ง")
        log_alert(severity, forecast, radar, sent=False, triggers=triggers)
        watch_log(forecast, radar, severity, triggers, False, slp_delta)
        return

    if not args.force and in_cooldown(state, severity):
        print(f"  → เพิ่งเตือนไปภายใน {COOLDOWN_MINUTES} นาที "
              f"และความรุนแรงไม่ได้เพิ่มขึ้น ไม่ส่งซ้ำ")
        log_alert(severity, forecast, radar, sent=False, triggers=triggers)
        watch_log(forecast, radar, severity, triggers, False, slp_delta)
        return

    print("--- ข้อความ ---")
    print(text)
    ok = send_telegram(text)
    log_alert(severity, forecast, radar, sent=ok, triggers=triggers)
    watch_log(forecast, radar, severity, triggers, ok, slp_delta)
    if ok:
        state["last_alert_at"] = now_th().isoformat()
        state["last_rank"] = rank
        state["last_severity"] = severity
        save_state(state)


if __name__ == "__main__":
    main()
