#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 score_auto.py — ให้คะแนนระบบเตือนอัตโนมัติ โดยไม่ต้องกรอกอะไรเลย
=====================================================================
 ใช้ radar_watch.csv ที่ระบบจดเองทุกรอบ เป็นทั้ง "คำทำนาย" และ "เฉลย"

   คำทำนาย = ทริกเกอร์ที่ทำงานในแถวนั้น
   เฉลย    = ในอีก N ชั่วโมงถัดมา เรดาร์เห็นฝนคลุมจุดนี้เกินเกณฑ์หรือไม่

 ทำไมถึงเชื่อเรดาร์เป็นเฉลยได้: เรดาร์วัดเม็ดฝนจริงในอากาศ ไม่ใช่การคำนวณ
 ทำนายแบบโมเดล จึงใช้ตรวจสอบคำทำนายของโมเดลได้อย่างเป็นอิสระ

 วิธีใช้:
   python score_auto.py
   python score_auto.py --lead 2 --truth 25

---------------------------------------------------------------------
 ข้อจำกัดที่ต้องรู้ก่อนเชื่อตัวเลข — อ่านก่อนตัดสินใจ:

 1) ทริกเกอร์ radar_now จะได้คะแนนสูงเสมอโดยอัตโนมัติ เพราะมันยิงตอนที่
    เรดาร์เห็นฝนพอดี แล้วเฉลยก็มาจากเรดาร์ตัวเดียวกัน = วัดตัวเองด้วยตัวเอง
    ตัวเลขของมันจึงดูที่ "ฝนอยู่ต่ออีกนานไหม" แทน ว่าคุ้มที่จะรบกวนหรือเปล่า
    ส่วนทริกเกอร์อื่น (gust/cape/pressure/rain) เรดาร์เป็นเฉลยอิสระจริง

 2) เรดาร์ที่ซูม 7 มีความละเอียด 1.19 กม./พิกเซล จึงบอกได้แค่ระดับ
    "ฝนตกแถวนี้" ไม่ใช่ "ฝนตกที่หลังคาบ้าน"

 3) ถ้าช่วงเวลาข้างหน้าไม่มีข้อมูลเลย (ระบบไม่ได้รัน) แถวนั้นจะถูกข้าม
    ไม่นับเป็นทั้งถูกและผิด เพราะเราไม่รู้จริง ๆ ว่าเกิดอะไรขึ้น
=====================================================================
"""

import csv
import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import Counter, defaultdict

WATCH = "radar_watch.csv"

# โครงคอลัมน์ทุกเวอร์ชันของ radar_watch.csv — คีย์คือจำนวนคอลัมน์
LAYOUTS = {
    15: ["เวลา", "เรดาร์คลุมวงแคบ(%)", "เรดาร์คลุมวงกว้าง(%)",
         "ตัดสินว่าฝนตกเหนือจุดนี้", "ฝนเข้าใน30นาที",
         "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)", "โมเดลตรงกัน",
         "จำนวนโมเดล", "TMD_WRF(มม.)", "CAPE",
         "ความกดอากาศเปลี่ยน(hPa)", "ระดับที่จะเตือน", "ทริกเกอร์", "ส่งจริง"],
    18: ["เวลา", "เรดาร์คลุมวงแคบ(%)", "เรดาร์คลุมวงกว้าง(%)",
         "ตัดสินว่าฝนตกเหนือจุดนี้", "ฝนเข้าใน30นาที", "อีกกี่นาทีฝนถึง",
         "ฝนที่ทำนาย(มม./ชม.)", "ฝนสูงสุดที่โมเดลใดเห็น(มม./ชม.)",
         "โอกาสฝน(%)", "โมเดลตรงกัน", "จำนวนโมเดล", "TMD_WRF(มม.)",
         "ลมกระโชก(กม./ชม.)", "CAPE", "ความกดอากาศเปลี่ยน(hPa)",
         "ระดับที่จะเตือน", "ทริกเกอร์", "ส่งจริง"],
}


def _f(v, default=0.0):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def load(path):
    if not os.path.exists(path):
        print(f"ไม่พบไฟล์ {path}")
        print("ไฟล์นี้ระบบสร้างเองเมื่อรันบน GitHub Actions — ดึงมาด้วย git pull ก่อน")
        sys.exit(1)

    with open(path, encoding="utf-8-sig", newline="") as f:
        raw = [r for r in csv.reader(f) if r]

    rows, skipped = [], Counter()
    for r in raw[1:]:
        layout = LAYOUTS.get(len(r))
        if layout is None:
            skipped[len(r)] += 1
            continue
        d = dict(zip(layout, r))
        try:
            t = datetime.strptime(d["เวลา"].strip(), "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            continue
        rows.append({
            "t": t,
            "over": _f(d.get("เรดาร์คลุมวงแคบ(%)")),
            "near": _f(d.get("เรดาร์คลุมวงกว้าง(%)")),
            "mm": _f(d.get("ฝนที่ทำนาย(มม./ชม.)")),
            "mm_max": _f(d.get("ฝนสูงสุดที่โมเดลใดเห็น(มม./ชม.)"), -1),
            "prob": _f(d.get("โอกาสฝน(%)")),
            "gust": _f(d.get("ลมกระโชก(กม./ชม.)"), -1),
            "cape": _f(d.get("CAPE"), -1),
            "trig": [x for x in (d.get("ทริกเกอร์") or "").split("|") if x],
            "sent": (d.get("ส่งจริง") or "").strip() == "yes",
        })
    if skipped:
        print(f"  ⚠️ ข้ามแถวที่จำนวนคอลัมน์ไม่รู้จัก: {dict(skipped)}")
    rows.sort(key=lambda r: r["t"])
    return rows


def make_truth(rows, lead_h, truth_cov):
    """
    ติดป้ายเฉลยให้ทุกแถว: ใน lead_h ชั่วโมงข้างหน้า เรดาร์เห็นฝนคลุมเกิน
    truth_cov % หรือไม่  -> True / False / None (ไม่มีข้อมูล ตัดสินไม่ได้)

    เงื่อนไข None สำคัญมาก: ระบบรันไม่สม่ำเสมอ บางช่วงห่างหลายชั่วโมง
    ถ้านับช่วงที่ไม่มีข้อมูลเป็น "ไม่มีฝน" สถิติจะสวยเกินจริงแบบเงียบ ๆ
    """
    out = []
    for i, r in enumerate(rows):
        lo, hi = r["t"], r["t"] + timedelta(hours=lead_h)
        win = [q for q in rows[i + 1:] if lo < q["t"] <= hi]
        if not win:
            out.append(None)
            continue
        # ต้องมีข้อมูลใกล้ ๆ ด้วย ไม่ใช่มีแค่จุดปลายช่วง
        if (win[0]["t"] - r["t"]).total_seconds() > 3600:
            out.append(None)
            continue
        out.append(any(q["over"] >= truth_cov for q in win))
    return out


def pct(a, b):
    return f"{a}/{b} = {a / b * 100:.0f}%" if b else "  -"


def main():
    ap = argparse.ArgumentParser(description="ให้คะแนนระบบเตือนอัตโนมัติจากเรดาร์")
    ap.add_argument("path", nargs="?", default=WATCH)
    ap.add_argument("--lead", type=float, default=2.0,
                    help="มองไปข้างหน้ากี่ชั่วโมงถือว่าคำเตือนนั้นถูก (ค่าตั้งต้น 2)")
    ap.add_argument("--truth", type=float, default=25.0,
                    help="ฝนต้องคลุมวงแคบกี่ %% จึงนับว่า 'ตกจริง' (ค่าตั้งต้น 25)")
    a = ap.parse_args()

    rows = load(a.path)
    if len(rows) < 10:
        print(f"ข้อมูลน้อยเกินไป ({len(rows)} แถว) รอเก็บอีกสักพัก")
        sys.exit(0)

    truth = make_truth(rows, a.lead, a.truth)
    usable = [(r, v) for r, v in zip(rows, truth) if v is not None]

    span = (rows[-1]["t"] - rows[0]["t"]).total_seconds() / 86400
    print("=" * 70)
    print(f"  {a.path} — {len(rows)} แถว  {rows[0]['t']:%d/%m %H:%M} ถึง {rows[-1]['t']:%d/%m %H:%M}")
    print(f"  เฉลย: ใน {a.lead:g} ชม.ข้างหน้า เรดาร์เห็นฝนคลุมเกิน {a.truth:g}% ของวงแคบ")
    print("=" * 70)

    print(f"\n[ ความถี่ที่ระบบได้มอง ]")
    print(f"  {len(rows) / span:.0f} รอบ/วัน  (ตั้งใจให้เช็คทุก 5 นาที = 288 รอบ/วัน)")
    gaps = [(rows[i + 1]["t"] - rows[i]["t"]).total_seconds() / 60
            for i in range(len(rows) - 1)]
    if gaps:
        srt = sorted(gaps)
        blind = sum(g for g in gaps if g > 30) / 60
        print(f"  ช่องว่างกลาง {srt[len(srt) // 2]:.0f} นาที  ยาวสุด {max(gaps) / 60:.1f} ชม.")
        print(f"  เวลาที่ระบบไม่ได้มองเลย (ช่วงห่างเกิน 30 นาที) รวม {blind:.0f} ชม."
              f" = {blind / (span * 24) * 100:.0f}% ของช่วงข้อมูล")

    base = sum(1 for _, v in usable if v)
    base_rate = base / len(usable) if usable else 0
    print(f"\n[ อัตราฐาน — ถ้าเดามั่วว่า 'ฝนจะตก' ตลอดเวลา ]")
    print(f"  ตัดสินได้ {len(usable)}/{len(rows)} แถว (ที่เหลือไม่มีข้อมูลข้างหน้า)")
    print(f"  ฝนตกจริงใน {a.lead:g} ชม.ข้างหน้า : {pct(base, len(usable))}")
    print("  ทริกเกอร์ไหนที่ % ไม่สูงกว่าเลขนี้ = ไม่ได้ช่วยอะไร เดามั่วยังได้เท่ากัน")

    # ---------- คะแนนรายทริกเกอร์ ----------
    print(f"\n[ คะแนนรายทริกเกอร์ ]")
    by = defaultdict(list)
    for r, v in usable:
        for t in r["trig"]:
            by[t].append(v)
    print(f"  {'ทริกเกอร์':<12} {'ยิง':>5} {'ฝนตกจริงตามมา':>16} {'เทียบอัตราฐาน':>16}")
    print("  " + "─" * 56)
    for t, vs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        hit = sum(1 for v in vs if v)
        rate = hit / len(vs)
        lift = rate / base_rate if base_rate else 0
        mark = "ดีกว่า" if lift > 1.15 else ("แย่กว่า" if lift < 0.9 else "พอ ๆ กัน")
        note = " ← วัดตัวเอง" if t == "radar_now" else ""
        print(f"  {t:<12} {len(vs):>5} {pct(hit, len(vs)):>16} "
              f"{f'{lift:.2f} เท่า {mark}':>16}{note}")

    # ---------- ข้อความที่ส่งจริง ----------
    sent = [(r, v) for r, v in usable if r["sent"]]
    quiet = [(r, v) for r, v in usable if not r["sent"]]
    print(f"\n[ ข้อความที่ส่งเข้า Telegram จริง ]")
    print(f"  ส่งไป {len(sent)} ครั้ง ({len(sent) / span:.1f}/วัน) "
          f"-> ฝนตกจริงตามมา {pct(sum(1 for _, v in sent if v), len(sent))}")
    print(f"  ไม่ได้ส่ง {len(quiet)} ครั้ง "
          f"-> ฝนตกจริงตามมา {pct(sum(1 for _, v in quiet if v), len(quiet))}")
    print("  บรรทัดล่างคือ 'ฝนที่พลาดไป' ยิ่งสูงยิ่งแปลว่าเกณฑ์เข้มเกินไป")

    # ---------- จูนเกณฑ์เรดาร์ ----------
    print(f"\n[ ฝนต้องคลุมวงแคบกี่ % ถึงจะเชื่อได้ — ใช้ตั้ง RADAR_OVER_COVERAGE ]")
    print(f"  {'ช่วง %':<14} {'จำนวน':>7} {'ฝนตกต่ออีก':>14}")
    print("  " + "─" * 40)
    for lo, hi in ((0, 1), (1, 10), (10, 25), (25, 50), (50, 101)):
        grp = [v for r, v in usable if lo <= r["over"] < hi]
        if grp:
            print(f"  {f'{lo}-{hi}%':<14} {len(grp):>7} {pct(sum(grp), len(grp)):>14}")
    print("  เลือกจุดที่ % กระโดดขึ้นชัดเป็นเกณฑ์")

    # ---------- จูนเกณฑ์ลม ----------
    have_gust = [(r, v) for r, v in usable if r["gust"] >= 0]
    print(f"\n[ ลมกระโชกกี่ กม./ชม. ถึงมีความหมาย — ใช้ตั้ง GUST_ALERT ]")
    if not have_gust:
        print("  ยังไม่มีคอลัมน์ลมกระโชกในไฟล์ — เริ่มเก็บตั้งแต่รอบถัดไป")
        print("  เก็บอีกสัก 3-4 วันแล้วรันใหม่ จะจูนได้")
    else:
        for lo, hi in ((0, 30), (30, 40), (40, 50), (50, 200)):
            grp = [v for r, v in have_gust if lo <= r["gust"] < hi]
            if grp:
                print(f"  {f'{lo}-{hi} กม./ชม.':<16} n={len(grp):>4} "
                      f"ฝนตกจริง {pct(sum(grp), len(grp))}")

    # ---------- จูนเกณฑ์ฝนจากโมเดล ----------
    print(f"\n[ โมเดลทำนายฝนกี่ มม. ถึงเชื่อได้ — ใช้ตั้ง RAIN_MM_ALERT ]")
    for lo, hi in ((0, 0.2), (0.2, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 999)):
        grp = [v for r, v in usable if lo <= r["mm"] < hi]
        if grp:
            print(f"  {f'{lo}-{hi} มม.':<16} n={len(grp):>4} "
                  f"ฝนตกจริง {pct(sum(grp), len(grp))}")
    reach = sum(1 for r, _ in usable if r["mm"] >= 1.0)
    if reach == 0:
        print("  ⚠️ ไม่มีแถวไหนแตะ 1.0 มม.เลย = เกณฑ์ฝนยังตายอยู่ ต้องลดเกณฑ์")

    print("\n" + "=" * 70)
    print("  อ่านค่าเสร็จแล้วแก้ตัวเลขในหัวไฟล์ rain_alert_telegram.py แล้ว push")
    print("=" * 70)


if __name__ == "__main__":
    main()
