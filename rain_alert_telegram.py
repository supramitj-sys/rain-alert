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
RAIN_MM_ALERT = 0.5        # ฝน มม./ชม. ที่ถือว่าเริ่มต้องเตือน
RAIN_MM_HEAVY = 7.5        # ฝน มม./ชม. ที่ถือว่าฝนหนัก
RAIN_MM_VERY_HEAVY = 15.0  # ฝน มม./ชม. ที่ถือว่าฝนหนักมาก
PROB_ALERT = 60            # โอกาสฝน % ที่ถือว่าต้องเตือน
GUST_ALERT = 40            # ลมกระโชก กม./ชม. ที่ต้องเตือน (งานนั่งร้าน/เครน)
GUST_DANGER = 60           # ลมกระโชก กม./ชม. ที่อันตรายชัดเจน
LOOKAHEAD_HOURS = 3        # มองล่วงหน้ากี่ชั่วโมง

# เรดาร์ nowcast: รัศมีที่ถือว่า "ฝนใกล้ตัว" (กม.)
RADAR_RADIUS_KM = 25

# ส่งข้อความ "ปกติดี" ด้วยไหม (False = ส่งเฉพาะตอนมีฝน/ลม/ประกาศเตือนภัย)
SEND_WHEN_CLEAR = False

# กันสแปม: ถ้าเพิ่งเตือนไปแล้วภายในกี่นาที ไม่ต้องเตือนซ้ำ
COOLDOWN_MINUTES = 90
STATE_FILE = "rain_alert_state.json"


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


def in_cooldown(state: dict, key: str) -> bool:
    """เช็คว่าเพิ่งเตือนเรื่องนี้ไปหรือยัง"""
    ts = state.get(key)
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return False
    return (now_th() - last) < timedelta(minutes=COOLDOWN_MINUTES)


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
        "hourly": "precipitation,precipitation_probability,temperature_2m,wind_gusts_10m",
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


def check_radar_pixel(radar_info, nowcast, past):
    """
    อ่านภาพ tile เรดาร์ตรงพิกัดบ้าน แล้วดูว่ามีสีฝนหรือไม่
    ต้องมี Pillow (pip install pillow) — ถ้าไม่มีจะข้ามไป คืนค่า None
    คืนค่า: {"now": bool, "in_30min": bool} หรือ None
    """
    try:
        from PIL import Image
        from io import BytesIO
    except ImportError:
        return None

    zoom = 8
    x, y = latlon_to_tile(LAT, LON, zoom)
    host = radar_info["host"]

    def tile_has_rain(path):
        # color scheme 4 = universal blue, smooth=1, snow=0
        url = f"{host}{path}/256/{zoom}/{x}/{y}/4/1_0.png"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                return False
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            w, hgt = img.size
            # ดูบริเวณกลาง tile (ประมาณตำแหน่งพิกัดเรา) รัศมี ~1/8 ของ tile
            cx, cy = w // 2, hgt // 2
            rad = max(8, w // 8)
            hits = 0
            total = 0
            for px in range(cx - rad, cx + rad, 2):
                for py in range(cy - rad, cy + rad, 2):
                    if 0 <= px < w and 0 <= py < hgt:
                        rr, gg, bb, aa = img.getpixel((px, py))
                        total += 1
                        if aa > 40:  # มีสี = มีฝน
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
#  ประกอบข้อความแจ้งเตือน
# =====================================================================

def build_message(forecast, radar, warning, always_send=False):
    """
    สร้างข้อความแจ้งเตือน คืนค่า (text, severity_key) หรือ (None, None) ถ้าไม่ต้องเตือน

    always_send=True  → ส่งข้อความเสมอแม้ไม่มีฝน (ใช้กับสรุปประจำวันตอนเช้า)
    """
    lines = []
    severity = None
    t_now = now_th().strftime("%H:%M")

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

        rain_hours = [f for f in forecast if f["rain_mm"] >= RAIN_MM_ALERT]

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
            lines.append(f"{head} ที่{PLACE_NAME}\nช่วงเวลา: {slots}\nโอกาสฝนสูงสุด {max_prob:.0f}%")

        elif max_prob >= PROB_ALERT:
            severity = severity or "prob"
            lines.append(f"🌦️ โอกาสฝนที่{PLACE_NAME} {max_prob:.0f}% ใน {LOOKAHEAD_HOURS} ชม.ข้างหน้า")

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
                  f"โอกาส {f['prob']}%  ลมกระโชก {f['gust']:.0f} กม./ชม.")
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

    text, severity = build_message(forecast, radar, warning, always_send=args.force)

    if text is None:
        print("  → ไม่มีอะไรต้องเตือน ไม่ส่งข้อความ")
        return

    state = load_state()
    key = f"last_{severity}"
    if not args.force and in_cooldown(state, key):
        print(f"  → อยู่ในช่วง cooldown ({COOLDOWN_MINUTES} นาที) ไม่ส่งซ้ำ")
        return

    print("--- ข้อความ ---")
    print(text)
    if send_telegram(text):
        state[key] = now_th().isoformat()
        save_state(state)


if __name__ == "__main__":
    main()
