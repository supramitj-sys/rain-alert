"""
วัดว่า Google WeatherNext 3 แม่นกว่าโมเดลหลักหรือไม่ เมื่อเทียบกับ "เรดาร์จริง" ที่ไซต์

ข้อมูลที่ใช้ (บอทจดให้เองทุกรอบ ไม่ต้องกรอกอะไร):
  google_compare.csv — ค่าพยากรณ์ 3 ชม.ข้างหน้าของ Google เทียบกับโมเดลหลักของบอท ณ เวลาที่เช็ค
  radar_watch.csv    — เรดาร์ที่วัดได้จริงทุกรอบ (ใช้เป็น "เฉลย")

วิธีวัด (เหมือนที่ใช้ทดสอบเว็บแอปเมื่อ 27 ก.ย.):
  - แต่ละแถวของ google_compare = คำทำนาย "จะมีฝนใน 3 ชม.ข้างหน้าไหม"
  - เฉลย = มีรอบใดใน 3 ชม.นั้นที่เรดาร์เห็นฝนเหนือจุด ≥ 25% ของวงแคบ (เกณฑ์เดียวกับบอท)
  - ใช้แค่แถวแรกของแต่ละชั่วโมง (รอบ 5 นาทีซ้อนทับกันมาก ถ้านับหมดจะดูมีตัวอย่างมากกว่าความจริง)
  - ใช้เฉพาะแถวที่ข้อมูลเรดาร์ครอบคลุมครบ 3 ชม.ถัดไป

ตัวชี้วัด (ตรงกับที่ใช้ใน PRD):
  จับฝนได้        = ฝนตกจริง แล้วสูตรเตือนไว้ก่อน        (recall)
  เตือนแล้วตกจริง = สูตรเตือน แล้วฝนตกจริง                (precision)
  บอกไม่มีฝนแล้วถูก = สูตรบอกไม่มีฝน แล้วไม่ตกจริง          (ค่านี้สำคัญกับคนวางงานเทคอนกรีต)

รัน:  python analyze_google.py            (รันในโฟลเดอร์ที่มี CSV ทั้งสองไฟล์)
      python analyze_google.py --days 14  (เฉพาะ 14 วันล่าสุด)
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timedelta

GOOGLE_CSV = "google_compare.csv"
WATCH_CSV = "radar_watch.csv"
OVER_COVER_PCT = 25          # ต้องตรงกับ RADAR_OVER_COVERAGE ในบอท
HORIZON_H = 3
MIN_ROWS, MIN_RAIN = 100, 20  # น้อยกว่านี้ ตัวเลขไม่น่าเชื่อถือ

WET_MM, WET_PROB = 0.2, 60    # เกณฑ์ "มีฝน" ของคำตัดสินในเว็บแอป (เหมือนกันทั้งสองฝั่ง จึงเทียบได้ตรง ๆ)


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def read_csv(path):
    if not os.path.exists(path):
        sys.exit(f"ไม่พบ {path} — ต้องรันบอทพร้อมตั้ง GOOGLE_WEATHER_KEY ก่อนจึงจะมีข้อมูล")
    with open(path, encoding="utf-8-sig", newline="") as fp:
        rows = [r for r in csv.reader(fp) if r]
    return rows[0], rows[1:]


def parse_time(s):
    try:
        return datetime.strptime(s.strip()[:16], "%Y-%m-%d %H:%M")
    except Exception:
        return None


def load():
    # --- เรดาร์ (เฉลย) ---
    h, rows = read_csv(WATCH_CSV)
    radar = []
    for r in rows:
        t = parse_time(r[0])
        over = _f(r[1]) if len(r) > 1 else None
        if t is not None and over is not None:
            radar.append((t, over))
    radar.sort()

    # --- Google เทียบโมเดลหลัก ---
    h, rows = read_csv(GOOGLE_CSV)
    col = {name: i for i, name in enumerate(h)}

    def get(r, name):
        i = col.get(name)
        return _f(r[i]) if i is not None and i < len(r) else None

    recs = []
    for r in rows:
        t = parse_time(r[0])
        if t is None:
            continue
        recs.append({
            "t": t,
            "g_sum": get(r, "Google ฝนรวม(มม.)"), "g_prob": get(r, "Google โอกาสฝน(%)"),
            "g_th": get(r, "Google ฟ้าคะนอง(%)"),
            "m_sum": get(r, "โมเดลหลัก ฝนรวม(มม.)"), "m_prob": get(r, "โมเดลหลัก โอกาสฝน(%)"),
            "near": get(r, "เรดาร์คลุมวงกว้าง(%)"),
        })
    return radar, recs


def evaluate(radar, recs, days=None):
    if not radar or not recs:
        return []
    last_radar = radar[-1][0]
    if days:
        cutoff = last_radar - timedelta(days=days)
        recs = [r for r in recs if r["t"] >= cutoff]

    seen, out = set(), []
    for r in recs:
        hour = r["t"].replace(minute=0)
        if hour in seen:
            continue
        end = r["t"] + timedelta(hours=HORIZON_H)
        if end > last_radar:
            continue                      # เรดาร์ยังไม่ครอบคลุมครบ 3 ชม. — ไม่ตัดสิน
        win = [c for (t, c) in radar if r["t"] < t <= end]
        if len(win) < HORIZON_H * 6:      # ต้องมีรอบเรดาร์พอสมควร (ควรได้ ~36 รอบ) กันหน้าต่างที่ข้อมูลขาด
            continue
        seen.add(hour)
        r["truth"] = max(win) >= OVER_COVER_PCT
        out.append(r)
    return out


def wet(sum_mm, prob):
    if sum_mm is None or prob is None:
        return None
    return sum_mm > WET_MM or prob >= WET_PROB


def score(rows, predict):
    tp = fp = tn = fn = 0
    for r in rows:
        p = predict(r)
        if p is None:
            continue
        if p and r["truth"]:
            tp += 1
        elif p and not r["truth"]:
            fp += 1
        elif not p and r["truth"]:
            fn += 1
        else:
            tn += 1
    pct = lambda a, b: f"{100 * a / b:5.1f}%" if b else "   — "
    return (pct(tp, tp + fn), pct(tp, tp + fp), pct(tn, tn + fn), tp + fp + tn + fn)


def main():
    ap = argparse.ArgumentParser(description="วัดความแม่น Google WeatherNext 3 เทียบเรดาร์จริง")
    ap.add_argument("--days", type=int, help="ใช้เฉพาะ N วันล่าสุด")
    args = ap.parse_args()

    radar, recs = load()
    rows = evaluate(radar, recs, args.days)
    n = len(rows)
    rain = sum(1 for r in rows if r["truth"])
    print(f"ตัวอย่าง {n} ชั่วโมง · ฝนตกเหนือจุดจริง (เรดาร์ ≥ {OVER_COVER_PCT}%) {rain} ชั่วโมง "
          f"({100 * rain / n:.0f}%)" if n else "ยังไม่มีตัวอย่างที่ข้อมูลเรดาร์ครอบคลุมครบ 3 ชม.")
    if n < MIN_ROWS or rain < MIN_RAIN:
        print(f"\n⚠️ ข้อมูลยังน้อยเกินสรุป (ต้องการอย่างน้อย {MIN_ROWS} ชั่วโมง และฝนจริง {MIN_RAIN} ชั่วโมง)"
              f" — เก็บต่ออีกสักพัก ตัวเลขด้านล่างเป็นแค่ภาพคร่าว ๆ")
    if not n:
        return

    formulas = [
        ("โมเดลหลักของบอท", lambda r: wet(r["m_sum"], r["m_prob"])),
        ("Google อย่างเดียว", lambda r: wet(r["g_sum"], r["g_prob"])),
        ("โมเดลหลัก หรือ Google (ระวังไว้ก่อน)",
         lambda r: None if wet(r["m_sum"], r["m_prob"]) is None or wet(r["g_sum"], r["g_prob"]) is None
         else (wet(r["m_sum"], r["m_prob"]) or wet(r["g_sum"], r["g_prob"]))),
        ("ทั้งสองตรงกัน (เตือนเมื่อเห็นพร้อมกัน)",
         lambda r: None if wet(r["m_sum"], r["m_prob"]) is None or wet(r["g_sum"], r["g_prob"]) is None
         else (wet(r["m_sum"], r["m_prob"]) and wet(r["g_sum"], r["g_prob"]))),
        ("Google ฟ้าคะนอง ≥ 40%", lambda r: None if r["g_th"] is None else r["g_th"] >= 40),
        ("(เทียบ) เรดาร์เห็นฝนในวงกว้างตอนนี้ ≥ 2%", lambda r: None if r["near"] is None else r["near"] >= 2),
    ]
    print(f"\n{'สูตร':<44}{'จับฝนได้':>10}{'เตือนแล้วตก':>13}{'บอกไม่มีฝนแล้วถูก':>20}{'n':>6}")
    print("-" * 93)
    for name, fn in formulas:
        rec, prec, spec, k = score(rows, fn)
        print(f"{name:<44}{rec:>10}{prec:>13}{spec:>20}{k:>6}")

    # โอกาสฝนของ Google เปลี่ยนเกณฑ์แล้วเป็นอย่างไร — ไว้เลือกเกณฑ์ถ้าจะให้ Google โหวต
    print("\nปรับเกณฑ์ 'โอกาสฝน' ของ Google อย่างเดียว (ไม่ดูปริมาณ):")
    print(f"{'เกณฑ์':<10}{'จับฝนได้':>10}{'เตือนแล้วตก':>13}{'บอกไม่มีฝนแล้วถูก':>20}")
    for th in (30, 40, 50, 60, 70, 80):
        rec, prec, spec, _ = score(rows, lambda r, th=th: None if r["g_prob"] is None else r["g_prob"] >= th)
        print(f"≥ {th}%".ljust(10) + f"{rec:>10}{prec:>13}{spec:>20}")

    print("\nวิธีอ่าน: ถ้า 'Google อย่างเดียว' หรือ 'หรือ' ได้ทั้ง จับฝนได้ และ บอกไม่มีฝนแล้วถูก สูงกว่า"
          "\n'โมเดลหลักของบอท' ชัดเจน (ตัวอย่างพอ) จึงค่อยพิจารณาให้ Google ร่วมโหวตใน rain_alert_telegram.py"
          "\n(อย่าลืม: หลังเพิ่มเข้า per_model ต้องคำนวณ rain_mm ใหม่ด้วย desc[MIN_MODEL_AGREE-1] ไม่ใช่ค่ากลาง)")


if __name__ == "__main__":
    main()
