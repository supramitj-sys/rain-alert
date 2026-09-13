#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 test_tmd_api.py — ทดสอบว่าโทเคนกรมอุตุฯ ใช้งานได้จริงไหม
=====================================================================
 รันอันนี้ก่อนเสมอ ก่อนเอาโทเคนไปใส่ GitHub Secrets

 วิธีใช้ (เลือกอย่างใดอย่างหนึ่ง):

   วิธีที่ 1 (แนะนำ) — สร้างไฟล์ tmd_token.txt ในโฟลเดอร์นี้
     วางโทเคนลงไปบรรทัดเดียว แล้วสั่ง
     python test_tmd_api.py
     (ไฟล์นี้อยู่ใน .gitignore แล้ว จะไม่หลุดขึ้น GitHub
      และเป็นไฟล์เดียวกับที่ระบบจริงใช้ จึงทดสอบได้ตรงกับของจริง)

   วิธีที่ 2 — วางโทเคนต่อท้ายคำสั่ง
     python test_tmd_api.py <โทเคนของคุณ>
     (ระวัง: โทเคนจะไปโผล่ในประวัติคำสั่งของ Command Prompt)

 หมายเหตุ: โทเคนต้องส่งใน header ไม่ใช่ใน URL
 เอา URL ไปวางในเบราว์เซอร์เฉย ๆ จะไม่ได้ผล — นี่คือจุดที่คนพลาดบ่อยที่สุด
=====================================================================
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("ยังไม่ได้ติดตั้ง requests — รันคำสั่ง:  pip install requests")
    sys.exit(1)

def _find_token():
    """หาโทเคนจาก 3 ที่ ตามลำดับ: ต่อท้ายคำสั่ง > env var > ไฟล์ tmd_token.txt"""
    if len(sys.argv) > 1:
        return sys.argv[1].strip(), "จากคำสั่งที่พิมพ์"
    env = os.environ.get("TMD_TOKEN", "").strip()
    if env:
        return env, "จาก environment variable"
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmd_token.txt")
        with open(path, encoding="utf-8-sig") as f:
            return f.read().strip().strip("<>").strip(), "จากไฟล์ tmd_token.txt"
    except Exception:
        return "", "ไม่พบ"


TOKEN, TOKEN_SRC = _find_token()

# พิกัดไซต์งาน
LAT, LON, PLACE = 13.53, 100.99, "บางปะกง"


def now_th():
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=7))).replace(tzinfo=None)


def main():
    print("=" * 62)
    print("  ทดสอบ TMD NWP API (โมเดล WRF กรมอุตุนิยมวิทยา)")
    print("=" * 62)

    if not TOKEN:
        print("\n❌ ยังไม่ได้ใส่โทเคน")
        print("   วิธีที่ 1:  python test_tmd_api.py <โทเคนของคุณ>")
        print("   วิธีที่ 2:  สร้างไฟล์ tmd_token.txt ในโฟลเดอร์นี้ วางโทเคนลงไปบรรทัดเดียว")
        sys.exit(1)

    print(f"\nแหล่งโทเคน: {TOKEN_SRC}")

    # ตรวจรูปแบบเบื้องต้น
    if TOKEN.startswith("<") or TOKEN.endswith(">"):
        print("\n❌ โทเคนมีเครื่องหมาย < > ติดมาด้วย — ต้องลบออก")
        print("   วงเล็บพวกนั้นเป็นแค่ตัวยึดในตัวอย่าง ไม่ใช่ส่วนหนึ่งของโทเคน")
        sys.exit(1)
    if TOKEN.count(".") != 2:
        print("\n⚠️ รูปแบบดูไม่เหมือน JWT ปกติ (ควรมีจุดคั่น 2 จุด)")
        print("   ลองคัดลอกใหม่ให้ครบทั้งบรรทัด ระวังช่องว่างหรือขึ้นบรรทัดใหม่")

    print(f"\nโทเคน: {TOKEN[:25]}...{TOKEN[-15:]}  (ยาว {len(TOKEN)} ตัวอักษร)")

    # อ่านวันหมดอายุจากตัวโทเคนเอง
    try:
        import base64
        pad = lambda x: x + "=" * (-len(x) % 4)
        payload = json.loads(base64.urlsafe_b64decode(pad(TOKEN.split(".")[1])))
        exp = datetime.fromtimestamp(payload["exp"], timezone(timedelta(hours=7)))
        left = (exp.replace(tzinfo=None) - now_th()).days
        print(f"หมดอายุ: {exp:%Y-%m-%d}  (เหลืออีก {left} วัน)")
        if left < 0:
            print("❌ โทเคนหมดอายุแล้ว ต้องสร้างใหม่")
            sys.exit(1)
    except Exception:
        print("(อ่านวันหมดอายุจากโทเคนไม่ได้ ไม่เป็นไร)")

    t = now_th()
    url = "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/at"
    headers = {"accept": "application/json", "authorization": "Bearer " + TOKEN}

    # ชุดเดียวกับที่ rain_alert_telegram.py ใช้จริง จะได้ทดสอบตรงกับของจริง
    for fields in ("tc,rh,rain,ws10m,wd10m,slp,cond,cloudlow",
                   "tc,rh,rain,ws10m,wd10m,cond",
                   "tc,rh,rain"):
        print(f"\n{'-'*62}")
        print(f"ลองดึงข้อมูล fields = {fields}")
        params = {
            "lat": LAT, "lon": LON, "fields": fields,
            "date": f"{t:%Y-%m-%d}", "hour": t.hour, "duration": 6,
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
        except Exception as e:
            print(f"❌ เชื่อมต่อไม่ได้: {e}")
            continue

        print(f"HTTP {r.status_code}")
        if r.status_code == 401:
            print("❌ โทเคนไม่ถูกต้องหรือหมดอายุ — ลองสร้างใหม่ที่ data.tmd.go.th")
            sys.exit(1)
        if r.status_code == 403:
            print("❌ โทเคนใช้ได้แต่ไม่มีสิทธิ์เข้าถึง endpoint นี้")
            continue
        if r.status_code != 200:
            print(f"   ตอบกลับ: {r.text[:300]}")
            continue

        try:
            d = r.json()
        except Exception:
            print(f"❌ ผลลัพธ์ไม่ใช่ JSON: {r.text[:300]}")
            continue

        try:
            wf = d["WeatherForecasts"][0]
            loc, fc = wf["location"], wf["forecasts"]
        except (KeyError, IndexError, TypeError):
            print("❌ โครงสร้างผลลัพธ์ไม่ตรงที่คาด:")
            print(json.dumps(d, ensure_ascii=False, indent=2)[:800])
            continue

        print(f"\n✅ ใช้งานได้")
        print(f"   จุดที่โมเดลใช้: {loc.get('lat')}, {loc.get('lon')}")
        print(f"   ได้ข้อมูล {len(fc)} ชั่วโมง\n")
        print(f"   {'เวลา':<20} {'ฝน(มม.)':>9} {'อุณหภูมิ':>9} {'ความชื้น':>9}")
        print("   " + "-" * 52)
        for f in fc:
            dat = f.get("data") or {}
            print(f"   {str(f.get('time'))[:19]:<20}"
                  f" {str(dat.get('rain','-')):>9}"
                  f" {str(dat.get('tc','-')):>9}"
                  f" {str(dat.get('rh','-')):>9}")

        print(f"\n   ตัวแปรที่มีจริงในผลลัพธ์: {', '.join((fc[0].get('data') or {}).keys())}")
        print(f"\n{'='*62}")
        print("  พร้อมใช้งานแล้ว — ขั้นตอนถัดไป:")
        print("  1. สร้างโทเคนใหม่ (ตัวนี้เคยแชร์ในแชทแล้ว)")
        print("  2. GitHub repo -> Settings -> Secrets and variables -> Actions")
        print("  3. New repository secret ชื่อ  TMD_TOKEN  วางโทเคนใหม่")
        print("  4. อัปโหลด rain_alert_telegram.py และ workflow ตัวใหม่")
        print("=" * 62)
        return

    print("\n❌ ลองครบทุกชุดแล้วยังไม่สำเร็จ")
    print("   ตรวจสอบว่าลงทะเบียนและสร้างโทเคนถูกต้องที่ data.tmd.go.th")


if __name__ == "__main__":
    main()
