#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 rain_bot_interactive.py — บอทตอบคำถามอากาศแบบทันที
=====================================================================
 ต่างจาก rain_alert_telegram.py ตรงที่ตัวนั้น "ส่งออกอย่างเดียว"
 ส่วนตัวนี้ "ฟังแล้วตอบ" — พิมพ์ถามเมื่อไหร่ก็ตอบทันที ไม่ต้องรอรอบ

 วิธีใช้:
   1) ใส่ TOKEN กับ CHAT_ID ในไฟล์ rain_alert_telegram.py ให้เรียบร้อยก่อน
      (ไฟล์นี้อ่านค่าจากไฟล์นั้น ไม่ต้องใส่ซ้ำ)
   2) pip install requests
   3) python rain_bot_interactive.py
   4) เปิดหน้าต่าง Command Prompt ค้างไว้ แล้วพิมพ์คุยกับบอทใน Telegram ได้เลย

 คำสั่งที่รองรับ (พิมพ์ไทยหรืออังกฤษก็ได้ ไม่ต้องมี /):
   ตอนนี้ / now      → อากาศตอนนี้ + 3 ชม.ข้างหน้า
   วันนี้  / today    → สรุปทั้งวัน + พรุ่งนี้
   ฝน    / rain      → ฝนจะตกกี่โมง อีกนานไหม
   เท    / concrete  → ช่วงเวลาเทคอนกรีตได้
   ลม    / wind      → ลมกระโชกวันนี้
   ร้อน  / heat      → ความร้อน UV ฟ้าคะนอง (ความปลอดภัยคนงาน)
   น้ำ   / tide      → น้ำขึ้น-น้ำลง + เตือนฝนหนักตรงน้ำขึ้น
   เรดาร์ / radar     → ลิงก์ดูเรดาร์สด
   ช่วย  / help      → รายการคำสั่ง

 กด Ctrl+C เพื่อหยุด
=====================================================================
"""

import sys
import time
import html
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("ยังไม่ได้ติดตั้ง requests — รันคำสั่ง:  pip install requests")
    sys.exit(1)

# อ่านค่า TOKEN / CHAT_ID / พิกัด จากไฟล์เดิม จะได้ไม่ต้องตั้งค่าซ้ำสองที่
try:
    import rain_alert_telegram as cfg
except Exception as e:
    print(f"เปิดไฟล์ rain_alert_telegram.py ไม่ได้: {e}")
    print("ไฟล์นี้ต้องอยู่ในโฟลเดอร์เดียวกับ rain_alert_telegram.py")
    sys.exit(1)

TOKEN = cfg.TELEGRAM_TOKEN
CHAT_ID = str(cfg.TELEGRAM_CHAT_ID)
LAT, LON, PLACE = cfg.LAT, cfg.LON, cfg.PLACE_NAME
API = f"https://api.telegram.org/bot{TOKEN}"


# =====================================================================
#  เวลา
# =====================================================================
def now_th():
    """เวลาไทย (UTC+7) ไม่พึ่งนาฬิกาเครื่อง"""
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=7))).replace(tzinfo=None)


# =====================================================================
#  ดึงพยากรณ์
# =====================================================================
def fetch(days=2):
    """ดึงพยากรณ์จาก Open-Meteo คืน dict หรือ None"""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LAT, "longitude": LON,
                "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
                "hourly": ("precipitation,precipitation_probability,temperature_2m,"
                           "wind_gusts_10m,cape,uv_index,apparent_temperature"),
                "daily": ("precipitation_sum,precipitation_probability_max,"
                          "temperature_2m_max,temperature_2m_min,wind_gusts_10m_max,"
                          "uv_index_max,apparent_temperature_max"),
                "timezone": "Asia/Bangkok", "forecast_days": days,
            }, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ดึงพยากรณ์ไม่ได้: {e}")
        return None


def hour_index(d):
    """หา index ของชั่วโมงปัจจุบันในอาร์เรย์ hourly"""
    times = d["hourly"]["time"]
    now = now_th()
    for i, t in enumerate(times):
        if datetime.fromisoformat(t) >= now:
            return max(0, i - 1)
    return 0


def rain_level(mm):
    if mm < 0.1:  return "ไม่มีฝน", "☀️"
    if mm < 0.5:  return "ฝนปรอย", "🌦️"
    if mm < 2:    return "ฝนเบา", "🌦️"
    if mm < 7.5:  return "ฝนปานกลาง", "🌧️"
    if mm < 15:   return "ฝนหนัก", "⛈️"
    return "ฝนหนักมาก", "⛈️"


# =====================================================================
#  เช็คเรดาร์จริง — ตอบช่วง 0-30 นาที ที่โมเดลตอบไม่ได้
#  (ยืมสมองจากตัวเตือน ไม่มีโค้ดอ่านภาพเรดาร์ของตัวเองอีกแล้ว)
# =====================================================================

def radar_check():
    """
    เช็คเรดาร์จริง โดย "ยืมสมอง" จากตัวเตือน (rain_alert_telegram) มาใช้ทั้งดุ้น

    เดิมบอทมีโค้ดอ่านภาพเรดาร์ของตัวเอง เป็นเวอร์ชันเก่า (วงเดียว 25 กม.,
    นับฝนแค่ 2% ของพื้นที่, เก็บสีจาง alpha>40) ซึ่งเป็นตรรกะเดียวกับที่
    ตัวเตือนเคยใช้แล้วพบว่าแม่นแค่ 13% — บอทจึงตอบไม่ตรงตามไปด้วย
    ตอนนี้เรียก cfg.fetch_radar_nowcast() ตัวเดียวกับที่ตัวเตือนใช้ (สองวง:
    วงแคบ 6 กม. = ตกตรงจุดจริง, วงกว้าง 25 กม. = มีฝนแถวนี้) จะได้แม่นเท่ากัน
    และแก้ที่เดียวมีผลทั้งคู่ ไม่ต้องไล่แก้สองที่อีก

    คืนค่า dict คีย์เดิมที่ผู้เรียกคาดหวัง (ok/now/cover/time/radius)
    พร้อมของใหม่ (near/near_cover/eta) ไว้ทำข้อความให้ละเอียดขึ้น
    """
    rad = cfg.fetch_radar_nowcast()
    if not rad:
        return {"ok": False, "why": "ดึงข้อมูลเรดาร์ไม่ได้"}
    rd = rad.get("rain_detected")
    if rd is None:
        return {"ok": False, "why": "ยังไม่ได้ติดตั้ง Pillow — รัน  pip install pillow"}

    ft = rad.get("frame_time")
    when = (datetime.fromtimestamp(ft, timezone.utc)
                    .astimezone(timezone(timedelta(hours=7)))
                    .replace(tzinfo=None)) if ft else now_th()
    return {
        "ok": True,
        "now": rd.get("now", False),              # ฝนคลุมวงแคบ 6 กม. เกินเกณฑ์
        "cover": rd.get("cover_over", 0.0),
        "radius": cfg.RADAR_OVER_KM,              # 6 กม. = "ตรงจุด"
        "near": rd.get("near_now", False),        # มีฝนในวงกว้าง 25 กม.
        "near_cover": rd.get("cover_near", 0.0),
        "near_radius": cfg.RADAR_NEAR_KM,
        "eta": rd.get("eta_min"),
        "time": when,
    }


def radar_line():
    """สร้างข้อความสรุปผลเรดาร์ 1-2 บรรทัด สำหรับแปะต่อท้ายคำสั่งอื่น"""
    r = radar_check()
    if not r["ok"]:
        return f"📡 เรดาร์: เช็คไม่ได้ ({r['why']})"
    age = (now_th() - r["time"]).total_seconds() / 60
    when = f"ภาพเมื่อ {r['time']:%H:%M}" + (f" ({age:.0f} นาทีที่แล้ว)" if age >= 1 else "")
    if r["now"]:
        return (f"📡 <b>เรดาร์: ฝนตกอยู่เหนือ{PLACE}แล้ว</b>\n"
                f"    ฝนคลุม {r['cover']*100:.0f}% ของรัศมี {r['radius']} กม.รอบจุดนี้ · {when}")
    if r["near"]:
        eta = f" · คาดถึงตัวใน ~{r['eta']} นาที" if r.get("eta") else ""
        return (f"📡 เรดาร์: ยังไม่ตกตรงจุด แต่มีฝนในรัศมี {r['near_radius']} กม. "
                f"(คลุม {r['near_cover']*100:.0f}%){eta} · {when}")
    return f"📡 เรดาร์: ไม่มีฝนในรัศมี {r['near_radius']} กม. · {when}"


# =====================================================================
#  คำสั่งต่าง ๆ
# =====================================================================
def cmd_now():
    d = fetch(1)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้ ลองใหม่อีกครั้ง"

    c, H = d["current"], d["hourly"]
    i = hour_index(d)
    nxt = H["precipitation"][i:i + 3]
    prob = H["precipitation_probability"][i:i + 3]
    gust = H["wind_gusts_10m"][i:i + 3]

    rain3 = sum(x or 0 for x in nxt)
    lvl, icon = rain_level(rain3)

    lines = [
        f"{icon} <b>{PLACE}</b> — {now_th():%H:%M}",
        "",
        f"🌡️ อุณหภูมิ {c['temperature_2m']:.0f}°C · ความชื้น {c['relative_humidity_2m']:.0f}%",
        f"💨 ลม {c['wind_speed_10m']:.0f} กม./ชม.",
        "",
        f"<b>3 ชม.ข้างหน้า: {lvl}</b>",
    ]
    for k in range(min(3, len(nxt))):
        t = datetime.fromisoformat(H["time"][i + k])
        mm = nxt[k] or 0
        bar = "█" * min(10, int(mm * 2)) if mm >= 0.1 else "—"
        lines.append(f"  {t:%H:%M}  {mm:4.1f} มม.  {prob[k] or 0:3.0f}%  {bar}")

    mg = max((g or 0) for g in gust) if gust else 0
    if mg >= 40:
        lines.append("")
        lines.append(f"⚠️ ลมกระโชกถึง {mg:.0f} กม./ชม. — ระวังนั่งร้าน ผ้าใบคลุม")

    # เรดาร์จริง — ตอบสิ่งที่โมเดลตอบไม่ได้ คือ "ตอนนี้ฝนอยู่ตรงไหน"
    lines.append("")
    lines.append(radar_line())

    return "\n".join(lines)


def cmd_today():
    d = fetch(3)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้"

    D = d["daily"]
    out = [f"📅 <b>{PLACE}</b> — สรุปพยากรณ์", ""]
    names = ["วันนี้", "พรุ่งนี้", "มะรืน"]
    for k in range(min(3, len(D["time"]))):
        mm = D["precipitation_sum"][k] or 0
        lvl, icon = rain_level(mm / 8)   # เฉลี่ยเป็นต่อชั่วโมงคร่าว ๆ
        out.append(
            f"{icon} <b>{names[k]}</b>  ฝนรวม {mm:.1f} มม. · โอกาส {D['precipitation_probability_max'][k] or 0:.0f}%\n"
            f"    {D['temperature_2m_min'][k]:.0f}–{D['temperature_2m_max'][k]:.0f}°C"
            f" · ลมสูงสุด {D['wind_gusts_10m_max'][k] or 0:.0f} กม./ชม.")

    # ความเสี่ยงฟ้าคะนองและความร้อนของวันนี้
    H, i = d["hourly"], hour_index(d)
    end = min(i + 12, len(H["time"]))
    def mx(k):
        a = [x for x in (H.get(k) or [])[i:end] if x is not None]
        return max(a) if a else None
    cape, uvm, ht = mx("cape"), mx("uv_index"), mx("apparent_temperature")
    cl, clab, _ = cape_level(cape)
    ul, ulab, _ = uv_level(uvm)
    hl, hlab, _ = heat_level(ht)
    out += ["", "<b>ความเสี่ยงอื่นวันนี้</b>",
            f"{ICON_LV[cl]} ฟ้าคะนอง: {clab}"
            + ("" if cape is None else f" ({cape:.0f} J/kg)"),
            f"{ICON_LV[ul]} UV: {ulab}" + ("" if uvm is None else f" ({uvm:.0f})"),
            f"{ICON_LV[hl]} ความร้อน: {hlab}" + ("" if ht is None else f" ({ht:.0f}°C)")]
    return "\n".join(out)


def cmd_rain():
    d = fetch(2)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้"

    # เช็คเรดาร์ก่อน — ถ้าฝนอยู่ตรงหัวแล้ว โมเดลรายชั่วโมงบอกไม่ทัน
    rad = radar_check()
    head = []
    if rad["ok"] and rad["now"]:
        head = [f"📡 <b>เรดาร์: ฝนตกอยู่เหนือ{PLACE}แล้ว</b>",
                f"    ฝนคลุม {rad['cover']*100:.0f}% ของรัศมี {rad['radius']} กม. "
                f"(ภาพเมื่อ {rad['time']:%H:%M})", ""]
    elif rad["ok"] and rad.get("near"):
        eta = f" คาดถึงตัวใน ~{rad['eta']} นาที" if rad.get("eta") else ""
        head = [f"📡 <b>เรดาร์: มีฝนใกล้ ๆ ในรัศมี {rad['near_radius']} กม.</b>"
                f"{eta} (ภาพเมื่อ {rad['time']:%H:%M})", ""]

    H = d["hourly"]
    i = hour_index(d)
    for k in range(i, min(i + 24, len(H["time"]))):
        mm = H["precipitation"][k] or 0
        if mm >= 0.5:
            t = datetime.fromisoformat(H["time"][k])
            gap = (t - now_th()).total_seconds() / 3600
            lvl, icon = rain_level(mm)
            when = "กำลังตกอยู่" if gap < 0.5 else f"อีกประมาณ {gap:.0f} ชม. ({t:%H:%M})"
            body = (f"{icon} <b>{lvl}</b> ที่{PLACE}\n{when}\n"
                    f"ปริมาณ {mm:.1f} มม./ชม. · โอกาส {H['precipitation_probability'][k] or 0:.0f}%\n\n"
                    f"<i>โมเดลให้ข้อมูลรายชั่วโมง เวลาจึงเป็นค่าประมาณ</i>")
            return "\n".join(head) + body

    tail = f"☀️ โมเดลบอกว่าไม่มีฝนที่{PLACE}ใน 24 ชม.ข้างหน้า"
    if head:
        tail += ("\n\n<i>แต่เรดาร์เห็นฝนแล้ว — เชื่อเรดาร์ เพราะเป็นของจริงที่วัดได้ "
                 "ส่วนโมเดลความละเอียด 9-13 กม. มักพลาดฝนก้อนเล็ก</i>")
    return "\n".join(head) + tail


def cmd_concrete():
    """หาช่วงแห้งต่อเนื่อง 6 ชม.ขึ้นไป สำหรับงานเทคอนกรีต"""
    d = fetch(2)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้"

    H = d["hourly"]
    i = hour_index(d)
    rows = [(datetime.fromisoformat(H["time"][k]), H["precipitation"][k] or 0)
            for k in range(i, min(i + 36, len(H["time"])))]

    windows, run = [], []
    for t, mm in rows:
        if mm < 0.2:
            run.append(t)
        else:
            if len(run) >= 6:
                windows.append((run[0], run[-1]))
            run = []
    if len(run) >= 6:
        windows.append((run[0], run[-1]))

    if not windows:
        return (f"⛔ <b>ไม่มีช่วงแห้งต่อเนื่อง 6 ชม.</b> ที่{PLACE}ใน 36 ชม.ข้างหน้า\n"
                f"ไม่แนะนำให้ล็อกคิวรถโม่")

    out = [f"🧱 <b>ช่วงเทคอนกรีตได้ — {PLACE}</b>", ""]
    for a, b in windows[:4]:
        hrs = int((b - a).total_seconds() / 3600) + 1
        day = "" if a.date() == now_th().date() else f" ({a:%d/%m})"
        out.append(f"✅ {a:%H:%M} – {b:%H:%M}{day}  ({hrs} ชม.)")
    out += ["", "<i>เกณฑ์: ฝนต่ำกว่า 0.2 มม./ชม. ติดต่อกัน 6 ชม.ขึ้นไป",
            "คอนกรีตสดต้องการเวลาแห้ง 4-6 ชม. ฝนใน 2 ชม.แรกทำผิวหน้าเสีย</i>"]
    return "\n".join(out)


def cmd_wind():
    d = fetch(1)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้"

    H = d["hourly"]
    i = hour_index(d)
    g = [(datetime.fromisoformat(H["time"][k]), H["wind_gusts_10m"][k] or 0)
         for k in range(i, min(i + 12, len(H["time"])))]
    mx = max(x[1] for x in g)

    if mx >= 60:
        head = "🛑 <b>ลมแรงมาก</b> — หยุดงานที่สูงทั้งหมด ตรวจยึดโยงนั่งร้าน"
    elif mx >= 50:
        head = "⚠️ <b>ลมแรง</b> — ควรหยุดงานยกของด้วยเครน/รถเฮี๊ยบ"
    elif mx >= 40:
        head = "💨 <b>ลมค่อนข้างแรง</b> — ระวังผ้าใบคลุม แผ่นเมทัลชีท"
    else:
        head = "✅ ลมปกติ ทำงานได้ตามแผน"

    out = [head, "", f"สูงสุด {mx:.0f} กม./ชม. ใน 12 ชม.ข้างหน้า"]

    # ---------------------------------------------------------------
    #  ทิศทางลม — Open-Meteo world model ที่ใช้คำนวณลมกระโชกด้านบน
    #  ไม่มีทิศทางลมให้ ต้องขอจาก TMD (wd10m) ต่างหาก
    # ---------------------------------------------------------------
    if cfg.USE_TMD:
        tmd = cfg.fetch_tmd_forecast(hours=6)
        if tmd:
            best = max(tmd.items(), key=lambda kv: kv[1].get("ws10m") or 0)
            wc = cfg.wind_compass(best[1].get("wd10m"))
            out.append(f"🧭 ทิศทางล่าสุด: มาจากทิศ{wc['from_th']} ({wc['from_code']}) {wc['arrow']}"
                       if wc else "🧭 ทิศทางลม: TMD ไม่ส่งค่าทิศทางมาในรอบนี้")
        else:
            out.append("🧭 ทิศทางลม: ดึงจาก TMD ไม่ได้ตอนนี้ (โทเคนอาจหมดอายุ)")
    else:
        out.append("🧭 ทิศทางลม: ยังไม่ได้ตั้งค่า TMD_TOKEN — มีแต่ความแรงลม ไม่มีทิศทาง")

    out.append("")
    for t, v in g[::3]:
        out.append(f"  {t:%H:%M}  {v:3.0f} กม./ชม.")
    return "\n".join(out)


# =====================================================================
#  เกณฑ์ความเสี่ยงเพิ่มเติม
# =====================================================================
def cape_level(v):
    if v is None:  return 0, "ไม่มีข้อมูล", ""
    if v < 500:    return 1, "บรรยากาศเสถียร", "โอกาสฟ้าคะนองต่ำ"
    if v < 1000:   return 1, "เสถียรปานกลาง", "อาจมีฝนฟ้าคะนองเล็กน้อย"
    if v < 2500:   return 2, "เสี่ยงฟ้าคะนอง", "ระวังฝนฟ้าคะนองก่อตัวเร็วช่วงบ่าย"
    return 3, "เสี่ยงพายุรุนแรง", "อาจมีลมกระโชกแรง ฟ้าผ่า — เตรียมหยุดงานที่สูง"


def uv_level(v):
    if v is None: return 0, "ไม่มีข้อมูล", ""
    if v < 3:     return 1, "ต่ำ", "ไม่ต้องป้องกันเป็นพิเศษ"
    if v < 6:     return 1, "ปานกลาง", "ควรใส่หมวกและเสื้อแขนยาว"
    if v < 8:     return 2, "สูง", "เลี่ยงแดดจัด 11:00-15:00 ทาครีมกันแดด"
    if v < 11:    return 3, "สูงมาก", "จำกัดเวลากลางแจ้ง จัดจุดพักในร่ม"
    return 3, "อันตรายมาก", "หลีกเลี่ยงกลางแจ้งช่วงเที่ยง"


def heat_level(v):
    if v is None: return 0, "ไม่มีข้อมูล", ""
    if v < 32:    return 1, "ปกติ", "ทำงานได้ตามปกติ"
    if v < 41:    return 2, "ร้อนจัด", "เพิ่มรอบพัก จัดน้ำดื่มให้เพียงพอ"
    if v < 54:    return 3, "อันตราย", "เสี่ยงตะคริวและเพลียแดด พัก 15 นาทีทุกชั่วโมง"
    return 3, "อันตรายมาก", "เสี่ยงโรคลมแดด ควรเลื่อนงานกลางแจ้ง"


ICON_LV = {0: "⬜", 1: "🟢", 2: "🟡", 3: "🔴"}


def cmd_heat():
    """ความร้อน + UV + ความเสี่ยงฟ้าคะนอง — เรื่องความปลอดภัยคนงาน"""
    d = fetch(1)
    if not d:
        return "❌ ดึงข้อมูลไม่ได้"

    H, i = d["hourly"], hour_index(d)
    end = min(i + 12, len(H["time"]))

    def mx(k):
        a = [x for x in (H.get(k) or [])[i:end] if x is not None]
        return max(a) if a else None

    heat, uv, cape = mx("apparent_temperature"), mx("uv_index"), mx("cape")
    hl, hlab, hmsg = heat_level(heat)
    ul, ulab, umsg = uv_level(uv)
    cl, clab, cmsg = cape_level(cape)

    out = [f"🥵 <b>ความเสี่ยงต่อคนงาน — {PLACE}</b>",
           "<i>ค่าสูงสุดใน 12 ชม.ข้างหน้า</i>", ""]
    out.append(f"{ICON_LV[hl]} <b>อุณหภูมิที่รู้สึกได้ "
               f"{'—' if heat is None else f'{heat:.0f}°C'}</b> · {hlab}")
    if hmsg: out.append(f"    {hmsg}")
    out.append("")
    out.append(f"{ICON_LV[ul]} <b>ดัชนี UV {'—' if uv is None else f'{uv:.0f}'}</b> · {ulab}")
    if umsg: out.append(f"    {umsg}")
    out.append("")
    out.append(f"{ICON_LV[cl]} <b>ฟ้าคะนอง (CAPE) "
               f"{'—' if cape is None else f'{cape:.0f} J/kg'}</b> · {clab}")
    if cmsg: out.append(f"    {cmsg}")

    out += ["", "<i>อุณหภูมิที่รู้สึกได้คำนวณจากอุณหภูมิ ความชื้น ลม และแดด",
            "ไม่ใช่ค่า WBGT ตามมาตรฐานความปลอดภัยในการทำงาน ใช้เป็นแนวทางเท่านั้น</i>"]
    return "\n".join(out)


def cmd_tide():
    """น้ำขึ้น-น้ำลง — สำคัญเพราะบางปะกงอยู่ปากแม่น้ำ"""
    url = "https://marine-api.open-meteo.com/v1/marine"
    try:
        r = requests.get(url, params={
            "latitude": LAT, "longitude": LON,
            "hourly": "sea_level_height_msl",
            "timezone": "Asia/Bangkok", "forecast_days": 2,
            "cell_selection": "sea",
        }, timeout=25)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return f"❌ ดึงข้อมูลน้ำไม่ได้ ({e})"

    t = d["hourly"]["time"]
    v = d["hourly"]["sea_level_height_msl"]
    if not v or all(x is None for x in v):
        return (f"❌ ไม่มีข้อมูลน้ำสำหรับพิกัด {PLACE}\n"
                f"พิกัดอาจอยู่ลึกเข้าไปในแผ่นดินเกินกว่าที่โมเดลน้ำทะเลครอบคลุม")

    now = now_th()
    ex = []
    for i in range(1, len(v) - 1):
        if v[i] is None or v[i-1] is None or v[i+1] is None:
            continue
        hi = v[i] >= v[i-1] and v[i] >= v[i+1]
        lo = v[i] <= v[i-1] and v[i] <= v[i+1]
        if hi or lo:
            tm = datetime.fromisoformat(t[i])
            if tm >= now:
                ex.append({"t": tm, "v": v[i], "hi": hi})

    # กรองจุดซ้ำจาก plateau — จุดชนิดเดียวกันต้องห่างกันอย่างน้อย 4 ชม.
    ded = []
    for e in ex:
        if ded and ded[-1]["hi"] == e["hi"] and (e["t"] - ded[-1]["t"]).total_seconds() < 4*3600:
            if (e["v"] > ded[-1]["v"]) if e["hi"] else (e["v"] < ded[-1]["v"]):
                ded[-1] = e
            continue
        ded.append(e)

    if not ded:
        return "ไม่พบจุดน้ำขึ้น-น้ำลงในช่วง 48 ชม.ข้างหน้า"

    out = [f"🌊 <b>น้ำขึ้น-น้ำลง — {PLACE}</b>", ""]
    for e in ded[:6]:
        gap = (e["t"] - now).total_seconds() / 3600
        out.append(f"{'▲ น้ำขึ้น' if e['hi'] else '▼ น้ำลง'}  {e['t']:%H:%M}  "
                   f"({e['v']:+.2f} ม.)  อีก {gap:.0f} ชม.")

    # เช็คว่าฝนหนักตรงกับน้ำขึ้นสูงหรือไม่
    w = fetch(2)
    if w:
        Hh, ii = w["hourly"], hour_index(w)
        clash = []
        for e in ded:
            if not e["hi"]:
                continue
            for k in range(ii, min(ii + 36, len(Hh["time"]))):
                mm = Hh["precipitation"][k] or 0
                tk = datetime.fromisoformat(Hh["time"][k])
                if mm >= 7.5 and abs((tk - e["t"]).total_seconds()) <= 90 * 60:
                    clash.append((e, mm))
                    break
        if clash:
            out += ["", "🚨 <b>ฝนหนักตรงกับช่วงน้ำขึ้นสูง</b>"]
            for e, mm in clash[:3]:
                out.append(f"    {e['t']:%H:%M} — ฝน {mm:.1f} มม./ชม. + น้ำ {e['v']:+.2f} ม.")
            out.append("    น้ำระบายลงแม่น้ำช้ากว่าปกติ เสี่ยงท่วมขังในไซต์")
            out.append("    ตรวจปั๊มสูบน้ำ ทางระบายน้ำ และความลาดชันบ่อขุดล่วงหน้า")

    out += ["", "<i>⚠️ ค่าจากแบบจำลอง ความละเอียด ~8 กม. ไม่ใช่ตารางน้ำอย่างเป็นทางการ",
            "ผู้ให้บริการระบุว่าความแม่นยำในเขตชายฝั่งและปากแม่น้ำมีข้อจำกัด",
            "ถ้าต้องใช้ตัวเลขจริง อ้างอิงกรมอุทกศาสตร์ hydro.navy.mi.th",
            "ระดับอ้างอิงเป็นระดับน้ำทะเลปานกลางโลก ไม่ใช่ระดับน้ำลงต่ำสุด</i>"]
    return "\n".join(out)


def cmd_radar():
    return (radar_line() + "\n\n"
            f"📡 <b>เรดาร์สด — {PLACE}</b>\n\n"
            f'<a href="https://www.rainviewer.com/map.html?loc={LAT},{LON},9">'
            f"RainViewer (ซูมตรงพิกัดให้แล้ว)</a>\n"
            f'<a href="https://weather.tmd.go.th/svp120Loop.php">เรดาร์สุวรรณภูมิ (Loop)</a>\n'
            f'<a href="http://www.sattmet.tmd.go.th/satmet/thai/loop/ir/gifir_se.html">'
            f"ภาพดาวเทียม IR (Loop)</a>\n\n"
            f"<i>ดาวเทียม IR เห็นเมฆฝนก่อตัวก่อนเรดาร์จับฝนได้ 1-3 ชม.</i>")


def cmd_help():
    return ("🤖 <b>คำสั่งที่ใช้ได้</b>\nพิมพ์ไทยหรืออังกฤษก็ได้ ไม่ต้องมี /\n\n"
            "<b>ตอนนี้</b>  — อากาศตอนนี้ + 3 ชม.ข้างหน้า\n"
            "<b>ฝน</b>      — ฝนจะตกกี่โมง อีกนานไหม\n"
            "<b>วันนี้</b>   — สรุปวันนี้ พรุ่งนี้ มะรืน\n"
            "<b>เท</b>      — ช่วงเวลาเทคอนกรีตได้\n"
            "<b>ลม</b>      — ลมกระโชก + ทิศทางลม (ถ้าตั้ง TMD_TOKEN) 12 ชม.ข้างหน้า\n"
            "<b>ร้อน</b>     — ความร้อน UV และความเสี่ยงฟ้าคะนอง\n"
            "<b>น้ำ</b>      — น้ำขึ้น-น้ำลง + เตือนฝนหนักตรงน้ำขึ้น\n"
            "<b>เรดาร์</b>   — ลิงก์ดูเรดาร์และดาวเทียมสด\n"
            "<b>ช่วย</b>     — ข้อความนี้\n\n"
            "<i>ที่มา: Open-Meteo / กรมอุตุนิยมวิทยา</i>")


# =====================================================================
#  แยกคำสั่ง
# =====================================================================
ROUTES = [
    (("ตอนนี้", "now", "/now", "เดี๋ยวนี้", "ปัจจุบัน"), cmd_now),
    (("ฝน", "rain", "/rain", "ฝนตก", "จะตกไหม"), cmd_rain),
    (("วันนี้", "today", "/today", "สรุป", "พรุ่งนี้"), cmd_today),
    (("เท", "concrete", "/concrete", "คอนกรีต", "เทปูน", "เทคอนกรีต"), cmd_concrete),
    (("ลม", "wind", "/wind", "ลมแรง"), cmd_wind),
    (("เรดาร์", "radar", "/radar", "ดาวเทียม"), cmd_radar),
    (("น้ำขึ้น", "น้ำลง", "น้ำ", "tide", "/tide"), cmd_tide),
    (("ร้อน", "แดด", "uv", "heat", "/heat", "ความร้อน"), cmd_heat),
    (("ช่วย", "help", "/help", "/start", "คําสั่ง", "คำสั่ง"), cmd_help),
]


def route(text):
    t = text.strip().lower()
    for keys, fn in ROUTES:
        if any(t == k or t.startswith(k) for k in keys):
            return fn
    return None


# =====================================================================
#  Telegram
# =====================================================================
def send(chat_id, text):
    try:
        r = requests.post(f"{API}/sendMessage", data={
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=20)
        if r.status_code != 200:
            print(f"  ส่งไม่สำเร็จ {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"  ส่งไม่สำเร็จ: {e}")


def main():
    if not TOKEN or "ใส่_" in TOKEN:
        print("!! ยังไม่พบ TELEGRAM_TOKEN")
        print("   สร้างไฟล์ชื่อ  telegram_token.txt  ในโฟลเดอร์เดียวกับไฟล์นี้")
        print("   แล้ววาง TOKEN ของบอทลงไปบรรทัดเดียว จากนั้นรันใหม่")
        sys.exit(1)
    if not CHAT_ID:
        print("!! ยังไม่พบ TELEGRAM_CHAT_ID")
        print("   สร้างไฟล์ชื่อ  telegram_chat_id.txt  แล้ววางเลข CHAT_ID ลงไป")
        sys.exit(1)

    # เช็คว่าบอทใช้งานได้
    try:
        me = requests.get(f"{API}/getMe", timeout=15).json()
        if not me.get("ok"):
            print(f"!! TOKEN ไม่ถูกต้อง: {me}")
            sys.exit(1)
        print(f"✅ เชื่อมต่อบอท @{me['result']['username']} สำเร็จ")
    except Exception as e:
        print(f"!! เชื่อมต่อ Telegram ไม่ได้: {e}")
        sys.exit(1)

    print(f"📍 พิกัด {PLACE} ({LAT}, {LON})")

    # บอกให้ชัดตั้งแต่ตอนเปิดว่าเชื่อมกรมอุตุฯ ได้หรือไม่
    # (ไม่งั้นจะรู้ตัวอีกทีตอนพิมพ์ "ลม" แล้วไม่มีทิศทางขึ้นมา)
    if cfg.USE_TMD:
        print(f"🇹🇭 TMD: เจอโทเคนแล้ว ({cfg.TMD_TOKEN[:12]}... ยาว {len(cfg.TMD_TOKEN)} ตัว)"
              " — คำสั่ง 'ลม' จะมีทิศทางลมด้วย")
    else:
        print("⚠️ TMD: ยังไม่เจอโทเคน — คำสั่ง 'ลม' จะมีแต่ความแรง ไม่มีทิศทาง")
        print("   วิธีแก้: สร้างไฟล์ tmd_token.txt ในโฟลเดอร์นี้ แล้ววางโทเคนลงไปบรรทัดเดียว")
        print("   (ค่าที่ตั้งไว้ใน GitHub Secrets ใช้ได้เฉพาะตอน GitHub รันเอง"
              " ไม่มีผลกับการรันบนเครื่องนี้)")

    print("🟢 บอทพร้อมแล้ว — พิมพ์คุยใน Telegram ได้เลย (กด Ctrl+C เพื่อหยุด)\n")

    offset = None
    # ข้ามข้อความเก่าที่ค้างในคิว จะได้ไม่ตอบย้อนหลังรัวตอนเปิด
    try:
        r = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=20).json()
        if r.get("ok") and r["result"]:
            offset = r["result"][-1]["update_id"] + 1
    except Exception:
        pass

    while True:
        try:
            # long polling — ค้างรอสูงสุด 50 วิ ไม่เปลือง CPU และไม่ยิงถี่
            r = requests.get(f"{API}/getUpdates",
                             params={"timeout": 50, "offset": offset},
                             timeout=60).json()
            if not r.get("ok"):
                time.sleep(5)
                continue

            for up in r["result"]:
                offset = up["update_id"] + 1
                msg = up.get("message") or up.get("edited_message")
                if not msg or "text" not in msg:
                    continue

                chat = str(msg["chat"]["id"])
                text = msg["text"]

                # ตอบเฉพาะเจ้าของบอท กันคนอื่นมาใช้
                if chat != CHAT_ID:
                    print(f"  ข้ามข้อความจาก chat_id อื่น: {chat}")
                    continue

                print(f"[{now_th():%H:%M:%S}] ได้รับ: {text}")
                fn = route(text)
                if fn:
                    send(chat, fn())
                else:
                    send(chat, "ไม่เข้าใจคำสั่งนี้\n\n" + cmd_help())

        except KeyboardInterrupt:
            print("\n👋 หยุดบอทแล้ว")
            break
        except requests.exceptions.ReadTimeout:
            continue                      # ปกติของ long polling
        except Exception as e:
            print(f"  ผิดพลาด: {e} — รอ 10 วินาทีแล้วลองใหม่")
            time.sleep(10)


if __name__ == "__main__":
    main()
