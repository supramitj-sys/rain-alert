#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 analyze_alerts.py — วิเคราะห์ว่าระบบเตือนแม่นแค่ไหน แล้วแนะนำเกณฑ์
=====================================================================
 อ่านไฟล์ alert_log.csv ที่ระบบบันทึกไว้ แล้วบอกว่า
   - เตือนไปกี่ครั้ง ถูกกี่ครั้ง รบกวนวันละกี่ข้อความ
   - "ทริกเกอร์" ตัวไหนแม่น ตัวไหนมั่ว  <-- คำถามที่สำคัญที่สุด
   - เรดาร์ต้องเห็นฝนคลุมกี่ % ถึงจะเชื่อได้
   - ถ้าขยับเกณฑ์ฝนแต่ละตัว ผลจะดีขึ้นหรือแย่ลง

 ต้องกรอกช่อง "ฝนตกจริง(กรอกเอง Y/N)" ในไฟล์ก่อน ถึงจะวิเคราะห์ได้
 กรอกแค่ Y หรือ N (ตัวเล็กก็ได้) แถวไหนยังไม่กรอกจะถูกข้าม

 วิธีใช้:
   python analyze_alerts.py
   python analyze_alerts.py path\\to\\alert_log.csv

 ควรมีข้อมูลอย่างน้อย 15-20 แถวที่กรอกแล้ว ผลถึงจะเชื่อถือได้
---------------------------------------------------------------------
 หมายเหตุสำคัญเรื่องการอ่านไฟล์:
 ไฟล์นี้เคยเปลี่ยนจำนวนคอลัมน์มาแล้ว 2 ครั้ง และหัวตารางเก่าค้างอยู่
 จึงต้องเดาโครงจาก "จำนวนคอลัมน์ของแต่ละแถว" ไม่ใช่เชื่อหัวตาราง
 (เวอร์ชันก่อนของสคริปต์นี้เชื่อหัวตาราง เลยอ่านคอลัมน์เพี้ยนและ
  มองไม่เห็นผลที่กรอกไว้เลยสักแถว)
---------------------------------------------------------------------
 สิ่งที่ไฟล์นี้บอกไม่ได้ — ต้องรู้ไว้ก่อนตีความ:
 log บันทึกเฉพาะตอนที่ระบบ "คิดจะเตือน" เท่านั้น ตอนที่ระบบเงียบแล้ว
 ฝนตกจริง (miss) ไม่มีอยู่ในไฟล์ ตัวเลข "จับได้กี่ %" จึงคำนวณได้
 เฉพาะภายในกลุ่มที่ระบบเคยสนใจ ไม่ใช่ recall จริงของทั้งระบบ
=====================================================================
"""

import csv
import sys
import os
from datetime import datetime
from collections import Counter, defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else "alert_log.csv"
WATCH = "radar_watch.csv"     # ค่าที่ระบบจดทุก 20 นาที (ไม่ต้องกรอกมือ)
RAIN_TIMES = "rain_times.txt"  # ช่วงเวลาที่ฝนตกจริง — ไฟล์เดียวที่ต้องกรอกเอง

# โครงคอลัมน์ทุกเวอร์ชันที่เคยมี — คีย์คือจำนวนคอลัมน์
LAYOUTS = {
    7:  ["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)",
         "เรดาร์เห็นฝน", "ส่งจริง", "ฝนตกจริง(กรอกเอง Y/N)"],
    10: ["เวลา", "ระดับ", "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)", "โมเดลตรงกัน",
         "จำนวนโมเดล", "TMD_WRF(มม.)", "เรดาร์เห็นฝน", "ส่งจริง",
         "ฝนตกจริง(กรอกเอง Y/N)"],
    13: ["เวลา", "ระดับ", "ทริกเกอร์", "ฝนที่ทำนาย(มม./ชม.)", "โอกาสฝน(%)",
         "โมเดลตรงกัน", "จำนวนโมเดล", "TMD_WRF(มม.)", "เรดาร์เห็นฝน",
         "เรดาร์คลุมวงแคบ(%)", "เรดาร์คลุมวงกว้าง(%)", "ส่งจริง",
         "ฝนตกจริง(กรอกเอง Y/N)"],
}


def _f(v, default=0.0):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def load(path):
    """อ่านทุกแถว แปลงตามโครงที่เดาได้จากจำนวนคอลัมน์ คืน (ทุกแถว, แถวที่กรอกผลแล้ว)"""
    if not os.path.exists(path):
        print(f"ไม่พบไฟล์ {path}")
        print("ไฟล์นี้จะถูกสร้างอัตโนมัติเมื่อระบบเตือนครั้งแรก")
        sys.exit(1)

    with open(path, encoding="utf-8-sig", newline="") as f:
        raw = [r for r in csv.reader(f) if r]
    if not raw:
        print("ไฟล์ว่าง")
        sys.exit(1)

    all_rows, skipped = [], Counter()
    for r in raw[1:]:                       # ข้ามหัวตาราง (ซึ่งอาจเป็นของเวอร์ชันเก่า)
        layout = LAYOUTS.get(len(r))
        if layout is None:
            skipped[len(r)] += 1
            continue
        d = dict(zip(layout, r))
        actual = (d.get("ฝนตกจริง(กรอกเอง Y/N)") or "").strip().upper()
        all_rows.append({
            "time": d.get("เวลา", ""),
            "sev": (d.get("ระดับ") or "").strip(),
            # แถวเก่าไม่มีคอลัมน์ทริกเกอร์ — ใช้ระดับแทนไปก่อน จะได้นับรวมได้
            "trig": [t for t in (d.get("ทริกเกอร์") or "").split("|") if t]
                    or ([d["ระดับ"].strip()] if d.get("ระดับ") else []),
            "mm": _f(d.get("ฝนที่ทำนาย(มม./ชม.)")),
            "prob": _f(d.get("โอกาสฝน(%)")),
            "agree": _i(d.get("โมเดลตรงกัน")),
            "n": _i(d.get("จำนวนโมเดล")),
            "radar": (d.get("เรดาร์เห็นฝน") or "").strip(),
            "cov_over": _f(d.get("เรดาร์คลุมวงแคบ(%)"), -1),
            "cov_near": _f(d.get("เรดาร์คลุมวงกว้าง(%)"), -1),
            "sent": (d.get("ส่งจริง") or "").strip() == "yes",
            "labeled": actual in ("Y", "N"),
            "rain": actual == "Y",
            "cols": len(r),
        })

    if skipped:
        print(f"  ⚠️ ข้ามแถวที่มีจำนวนคอลัมน์ไม่รู้จัก: {dict(skipped)}")
    return all_rows, [r for r in all_rows if r["labeled"]]


def hit(rows):
    """คืนข้อความ 'ตกจริง n/N = xx%' สำหรับกลุ่มแถวที่กรอกผลแล้ว"""
    if not rows:
        return "ยังไม่มีข้อมูล"
    y = sum(1 for r in rows if r["rain"])
    return f"{y}/{len(rows)} = {y / len(rows) * 100:.0f}%"


def score(rows, mm_th, prob_th, agree_th):
    """
    ลองใช้เกณฑ์ฝนชุดหนึ่งกับข้อมูลย้อนหลัง แล้วนับผล

    TP = เตือนแล้วตกจริง       (ดี)
    FP = เตือนแล้วไม่ตก        (น่ารำคาญ)
    FN = ไม่เตือนแต่ตกจริง     (อันตราย — พลาดงาน)
    TN = ไม่เตือนและไม่ตก      (ดี)
    """
    tp = fp = fn = tn = 0
    for r in rows:
        would_alert = (r["mm"] >= mm_th and r["prob"] >= prob_th
                       and r["agree"] >= min(agree_th, max(r["n"], 1)))
        if would_alert and r["rain"]:       tp += 1
        elif would_alert and not r["rain"]: fp += 1
        elif not would_alert and r["rain"]: fn += 1
        else:                               tn += 1
    return tp, fp, fn, tn


def fbeta(prec, rec, beta=2.0):
    """
    คะแนนรวมที่ให้น้ำหนัก "ไม่พลาด" มากกว่า "ไม่เตือนเกิน"

    ใช้ beta=2 คือถือว่าการพลาดฝนจริง (FN) แย่กว่าการเตือนผิด (FP) 2 เท่า
    เพราะงานก่อสร้าง: เตือนเกิน = เสียเวลาเก็บของรอบเดียว
                      พลาดฝน   = ปูนเสีย งานเสีย เครื่องมือเปียก คนเปียก
    ถ้าใช้ F1 (น้ำหนักเท่ากัน) ระบบจะเลือกเกณฑ์ที่เข้มเกินไปจนพลาดของจริง
    """
    if not (prec + rec):
        return 0.0
    b2 = beta * beta
    return (1 + b2) * prec * rec / (b2 * prec + rec)


def summarize(tp, fp, fn, tn):
    prec = tp / (tp + fp) if (tp + fp) else 0      # เตือนแล้วถูกกี่ %
    rec = tp / (tp + fn) if (tp + fn) else 0       # ฝนจริงจับได้กี่ %
    return prec, rec, fbeta(prec, rec)


def section(title):
    print(f"\n[ {title} ]")


# =====================================================================
#  จูนเกณฑ์เรดาร์จาก radar_watch.csv + rain_times.txt
# =====================================================================

def load_rain_times(path):
    """
    อ่านไฟล์ที่จดว่าฝนตกจริงช่วงไหน

    รูปแบบ 2 แบบ บรรทัดละ 1 รายการ:
      2026-08-04 14:20 15:10   = วันนั้นฝนตกช่วง 14:20-15:10
      2026-08-05 -             = วันนั้นเฝ้าดูแล้ว ไม่มีฝนเลย

    คืน (ช่วงที่ฝนตก, วันที่เฝ้าดู)

    ทำไมต้องมีบรรทัด "-" ด้วย: ถ้าไม่มี เราจะแยกไม่ออกระหว่าง "วันนั้นไม่มีฝน"
    กับ "วันนั้นลืมจด" แล้ววันที่ลืมจดจะถูกนับเป็นไม่มีฝนทั้งวัน
    ทำให้สถิติเพี้ยนหนักโดยไม่มีใครรู้ตัว
    จึงวิเคราะห์เฉพาะวันที่ปรากฏในไฟล์นี้เท่านั้น วันอื่นข้ามไปทั้งหมด
    """
    if not os.path.exists(path):
        return None, None
    spans, days = [], set()
    with open(path, encoding="utf-8-sig") as f:
        for ln, line in enumerate(f, 1):
            line = line.split("#")[0].strip()
            if not line:
                continue
            p = line.split()
            try:
                day = datetime.strptime(p[0], "%Y-%m-%d").date()
            except ValueError:
                print(f"  ⚠️ {path} บรรทัด {ln}: วันที่ผิดรูปแบบ -> {line}")
                continue
            days.add(day)
            if len(p) >= 3 and p[1] != "-":
                try:
                    a = datetime.strptime(f"{p[0]} {p[1]}", "%Y-%m-%d %H:%M")
                    b = datetime.strptime(f"{p[0]} {p[2]}", "%Y-%m-%d %H:%M")
                    spans.append((a, b))
                except ValueError:
                    print(f"  ⚠️ {path} บรรทัด {ln}: เวลาผิดรูปแบบ -> {line}")
    return spans, days


def tune_radar():
    """หาจุดตัด % ที่แยกฝนจริงออกจากฝนหลอกได้ดีที่สุด"""
    if not os.path.exists(WATCH):
        return
    spans, days = load_rain_times(RAIN_TIMES)

    with open(WATCH, encoding="utf-8-sig", newline="") as f:
        obs = list(csv.DictReader(f))
    if not obs:
        return

    section(f"จูนเกณฑ์เรดาร์จาก {WATCH} ({len(obs)} จุดสังเกต)")

    if spans is None:
        print(f"  ยังไม่มีไฟล์ {RAIN_TIMES} — ระบบจดค่าไว้ให้แล้ว {len(obs)} จุด")
        print(f"  แต่ยังไม่รู้ว่าฝนตกจริงตอนไหน สร้างไฟล์ {RAIN_TIMES} แล้วจดแบบนี้:")
        print("      2026-08-04 14:20 15:10     <- ฝนตกช่วงนี้")
        print("      2026-08-05 -               <- วันนี้เฝ้าดูแล้ว ไม่มีฝน")
        return
    if not days:
        print(f"  {RAIN_TIMES} ยังว่างอยู่ — ยังจับคู่กับอะไรไม่ได้")
        return

    rows = []
    for o in obs:
        try:
            t = datetime.strptime(o["เวลา"], "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            continue
        if t.date() not in days:
            continue                       # วันที่ไม่ได้เฝ้าดู ข้ามทั้งหมด
        cov = _f(o.get("เรดาร์คลุมวงแคบ(%)"), -1)
        if cov < 0:
            continue
        rows.append((cov, any(a <= t <= b for a, b in spans)))

    if not rows:
        print("  ยังไม่มีจุดสังเกตที่ตรงกับวันที่จดไว้")
        return

    wet = sum(1 for _, r in rows if r)
    print(f"  ใช้ได้ {len(rows)} จุด จาก {len(days)} วันที่เฝ้าดู "
          f"| อยู่ในช่วงฝนตกจริง {wet} จุด ({wet/len(rows)*100:.0f}%)")
    if wet < 5:
        print("  ⚠️ จุดที่ฝนตกจริงยังน้อยเกินไป เก็บต่ออีกหน่อยก่อนเชื่อผล")

    print(f"\n  {'ถ้าตั้งเกณฑ์ที่':>14} │ {'เตือน':>5} {'ถูก':>4} {'ผิด':>4} {'พลาด':>5} │"
          f" {'แม่น%':>6} {'จับได้%':>7} {'คะแนน':>6}")
    print("  " + "─" * 66)
    best = None
    for th in (2, 5, 10, 15, 20, 25, 30, 40, 50, 60):
        tp = sum(1 for c, r in rows if c >= th and r)
        fp = sum(1 for c, r in rows if c >= th and not r)
        fn = sum(1 for c, r in rows if c < th and r)
        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        sc = fbeta(prec, rec)
        if best is None or sc > best[0]:
            best = (sc, th, tp, fp, fn, prec, rec)
        mark = ""
        print(f"  {th:>13}% │ {tp+fp:5d} {tp:4d} {fp:4d} {fn:5d} │"
              f" {prec*100:5.0f}% {rec*100:6.0f}% {sc:6.2f}{mark}")
    print("  (คะแนนให้น้ำหนัก 'ไม่พลาดฝนจริง' มากกว่า 'ไม่เตือนเกิน' 2 เท่า)")

    if best and best[0] > 0:
        f1, th, tp, fp, fn, prec, rec = best
        print(f"\n  → ตั้ง RADAR_OVER_COVERAGE = {th/100:.2f}  (คือ {th}%)")
        print(f"     ในไฟล์ rain_alert_telegram.py")
        print(f"     ที่เกณฑ์นี้: เตือน {tp+fp} ครั้ง ถูก {tp} ผิด {fp} พลาด {fn}")
        print(f"     เตือนแล้วถูก {prec*100:.0f}% · ฝนจริงจับได้ {rec*100:.0f}%")
        print("\n     ถ้างานคุณกลัวพลาดมากกว่ากลัวรำคาญ ให้เลือกแถวที่ 'จับได้%'")
        print("     สูงกว่านี้ แล้วยอมรับตัวเลข 'ผิด' ที่มากขึ้น")
    else:
        print("\n  ยังหาจุดตัดที่ใช้ได้ไม่เจอ — เก็บข้อมูลต่ออีกสักพัก")


def main():
    all_rows, rows = load(LOG)

    print("=" * 66)
    print(f"  alert_log.csv — ทั้งหมด {len(all_rows)} แถว "
          f"| กรอกผลจริงแล้ว {len(rows)} แถว")
    print("=" * 66)

    if not rows:
        print("\nยังไม่มีแถวที่กรอกช่อง 'ฝนตกจริง' เลย")
        print("เปิดไฟล์ alert_log.csv แล้วกรอก Y หรือ N ในคอลัมน์สุดท้ายก่อน")
        sys.exit(0)

    if len(rows) < 15:
        print(f"\n  ⚠️ ข้อมูลยังน้อย ({len(rows)} แถว) ผลอาจยังไม่น่าเชื่อถือ")
        print("     ควรเก็บให้ได้อย่างน้อย 15-20 แถวก่อนตัดสินใจปรับเกณฑ์")

    # ---------- ภาพรวม ----------
    rained = sum(1 for r in rows if r["rain"])
    sent_rows = [r for r in rows if r["sent"]]
    section("สภาพจริงที่ผ่านมา")
    print(f"  ฝนตกจริง            {rained}/{len(rows)} แถวที่กรอก")
    print(f"  ส่งเข้า Telegram     {len(sent_rows)} ครั้ง -> ตกจริง {hit(sent_rows)}")
    quiet = [r for r in rows if not r["sent"]]
    if quiet:
        print(f"  คิดจะเตือนแต่ไม่ส่ง  {len(quiet)} ครั้ง -> ตกจริง {hit(quiet)}")
        print("  (ถ้าบรรทัดนี้ % สูงกว่าบรรทัดบน = ตัวกรอง cooldown/งดรบกวนกรองผิดตัว)")

    # ---------- ความถี่ = ต้นทุนความรำคาญ ----------
    days = sorted({r["time"][:10] for r in all_rows if r["time"]})
    if days:
        n_sent = sum(1 for r in all_rows if r["sent"])
        section("ความถี่ (ต้นทุนความรำคาญ)")
        print(f"  ช่วงข้อมูล {days[0]} ถึง {days[-1]} รวม {len(days)} วัน")
        print(f"  ระบบพิจารณาเตือน {len(all_rows)/len(days):.1f} ครั้ง/วัน")
        print(f"  ส่งเข้า Telegram  {n_sent/len(days):.1f} ข้อความ/วัน")
        if n_sent / len(days) > 3:
            print("  ⚠️ เกิน 3 ข้อความ/วัน คนจะเริ่มเลื่อนผ่านโดยไม่อ่าน")

    # ---------- ทริกเกอร์ไหนแม่น ทริกเกอร์ไหนมั่ว ----------
    section("ทริกเกอร์ตัวไหนเชื่อถือได้ (สำคัญที่สุด)")
    by_trig = defaultdict(list)
    fired = Counter()
    for r in all_rows:
        for t in r["trig"]:
            fired[t] += 1
            if r["labeled"]:
                by_trig[t].append(r)
    print(f"  {'ทริกเกอร์':<14} {'ยิงทั้งหมด':>10} {'กรอกแล้ว':>9}  ตกจริง")
    print("  " + "─" * 56)
    for t, _ in fired.most_common():
        print(f"  {t:<14} {fired[t]:>10} {len(by_trig[t]):>9}  {hit(by_trig[t])}")
    print("\n  ตัวที่ยิงบ่อยแต่ % ต่ำ = ต้นตอของความรำคาญ ควรบังคับให้มีหลักฐาน")
    print("  ฝนจริงยืนยันก่อน หรือย้ายไปเป็นข้อมูลประกอบแทนการเตือน")

    # ---------- เรดาร์ ----------
    with_r = [r for r in rows if r["radar"] in ("yes", "no")]
    if with_r:
        section("เรดาร์ช่วยแยกแยะได้แค่ไหน")
        print(f"  เรดาร์เห็นฝนเหนือจุดนี้   -> ตกจริง "
              f"{hit([r for r in with_r if r['radar'] == 'yes'])}")
        print(f"  เรดาร์ไม่เห็น            -> ตกจริง "
              f"{hit([r for r in with_r if r['radar'] == 'no'])}")
        print("  ถ้าสองบรรทัดนี้ต่างกันมาก = เรดาร์ใช้ได้ ควรใช้เป็นเงื่อนไขหลัก")

    # ---------- % พื้นที่ที่เรดาร์เห็นฝน (คอลัมน์ใหม่) ----------
    cov = [r for r in rows if r["cov_over"] >= 0]
    if cov:
        section("ฝนต้องคลุมกี่ % ถึงจะเชื่อได้ (ใช้จูน RADAR_OVER_COVERAGE)")
        for lo, hi in ((0, 10), (10, 25), (25, 50), (50, 101)):
            grp = [r for r in cov if lo <= r["cov_over"] < hi]
            print(f"  คลุมวงแคบ {lo:>3}-{hi:<3}%  n={len(grp):>3}  ตกจริง {hit(grp)}")
        print("  ตั้ง RADAR_OVER_COVERAGE ที่ช่วงแรกที่ % ตกจริงกระโดดขึ้นชัด")
    else:
        print("\n  (ยังไม่มีคอลัมน์ % พื้นที่เรดาร์ — จะเริ่มเก็บตั้งแต่รอบถัดไป")
        print("   เก็บอีกสัปดาห์แล้วรันใหม่ จะจูนเกณฑ์เรดาร์จากข้อมูลจริงได้)")

    # ---------- โมเดลตรงกัน ----------
    if any(r["n"] for r in rows):
        section("จำนวนโมเดลที่ตรงกัน บอกอะไรได้บ้าง")
        for a in sorted({r["agree"] for r in rows}):
            grp = [r for r in rows if r["agree"] == a]
            print(f"  ตรงกัน {a} ตัว -> ตกจริง {hit(grp)}   (n={len(grp)})")
        print("  ยิ่งตรงกันมาก % ควรยิ่งสูง ถ้าใช่ = ใช้เกณฑ์นี้ได้ผล")

    # ---------- เกณฑ์ฝน 3 ชั้น ----------
    gate = [r for r in rows
            if r["mm"] >= 1.0 and r["prob"] >= 70 and r["agree"] >= min(2, max(r["n"], 1))]
    section("เกณฑ์ฝน 3 ชั้นปัจจุบัน (mm>=1.0 & prob>=70 & agree>=2)")
    print(f"  แถวที่กรอกแล้วและผ่านเกณฑ์นี้: {len(gate)}/{len(rows)} -> ตกจริง {hit(gate)}")
    if len(gate) < 5:
        print("  ⚠️ แถวส่วนใหญ่ไม่ได้เตือนเพราะเกณฑ์นี้ แต่เตือนผ่านทางลัด")
        print("     (เรดาร์/CAPE/ความกดอากาศ) ตารางจูนเกณฑ์ข้างล่างจึงยัง")
        print("     สรุปอะไรไม่ได้มาก — ไปดูตาราง 'ทริกเกอร์' ข้างบนแทน")

    # ---------- ลองเกณฑ์ต่าง ๆ ----------
    section("ลองปรับเกณฑ์ฝนดูว่าผลจะเป็นอย่างไร")
    print(f"  {'ฝน':>5} {'โอกาส':>6} {'ตรงกัน':>7} │ {'เตือน':>5} {'ถูก':>4} {'ผิด':>4} {'พลาด':>5} │"
          f" {'แม่น%':>6} {'จับได้%':>7} {'คะแนน':>6}")
    print("  " + "─" * 74)

    best = None
    for mm in (0.5, 1.0, 1.5, 2.0, 3.0):
        for pb in (60, 70, 80):
            for ag in (1, 2, 3):
                tp, fp, fn, tn = score(rows, mm, pb, ag)
                prec, rec, f1 = summarize(tp, fp, fn, tn)
                if best is None or f1 > best[0]:
                    best = (f1, mm, pb, ag, tp, fp, fn, prec, rec)

    for mm in (0.5, 1.0, 1.5, 2.0, 3.0):
        for ag in (1, 2, 3):
            tp, fp, fn, tn = score(rows, mm, 70, ag)
            prec, rec, f1 = summarize(tp, fp, fn, tn)
            mark = " ←" if best and (mm, 70, ag) == best[1:4] else ""
            print(f"  {mm:5.1f} {70:6.0f} {ag:7d} │ {tp+fp:5d} {tp:4d} {fp:4d} {fn:5d} │"
                  f" {prec*100:5.0f}% {rec*100:6.0f}% {f1:6.2f}{mark}")

    if best and best[0] > 0:
        f1, mm, pb, ag, tp, fp, fn, prec, rec = best
        section("เกณฑ์ฝนที่สมดุลที่สุดจากข้อมูลชุดนี้")
        print(f"  RAIN_MM_ALERT   = {mm}")
        print(f"  PROB_ALERT      = {pb}")
        print(f"  MIN_MODEL_AGREE = {ag}")
        print(f"  → เตือน {tp+fp} ครั้ง ถูก {tp} ผิด {fp} พลาดฝนจริง {fn}")
        print(f"  → เตือนแล้วถูก {prec*100:.0f}% · ฝนจริงจับได้ {rec*100:.0f}%")
        print("\n  แก้ 3 บรรทัดนี้ในไฟล์ rain_alert_telegram.py แล้วอัปขึ้น GitHub ใหม่")
    else:
        section("ยังหาเกณฑ์ฝนที่ดีกว่าเดิมไม่ได้")
        print("  ไม่มีชุดเกณฑ์ไหนจับฝนจริงได้เลยในข้อมูลชุดนี้ แปลว่าฝนที่ตกจริง")
        print("  ไม่ได้ถูกโมเดลทำนายไว้ล่วงหน้า — ต้องพึ่งเรดาร์เป็นหลัก ไม่ใช่โมเดล")

    # ---------- จูนเกณฑ์เรดาร์จากสมุดจดค่า ----------
    tune_radar()

    print("\n  ⚠️ ดูช่อง 'พลาด' ด้วย ไม่ใช่แค่ 'ผิด'")
    print("     เกณฑ์ที่เข้มจนไม่เตือนอะไรเลยจะดูแม่น 100% แต่ไร้ประโยชน์")
    print("     สำหรับงานก่อสร้าง การพลาดฝนหนักแพงกว่าการเตือนเกิน")
    print("\n" + "=" * 66)


if __name__ == "__main__":
    main()
