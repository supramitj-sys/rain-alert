# PROMPT 1 — ออกแบบ UI แอปมือถือ "เช็คฝน"

> **ใช้กับ:** Figma AI / Google Stitch / Uizard / Galileo AI / Midjourney / Claude (ขอภาพ mockup)
> **ได้ผลลัพธ์:** ภาพหน้าจอ mockup ที่เอาไปให้ AI เขียนโค้ดต่อได้
> **วิธีใช้:** คัดลอกทั้งบล็อกด้านล่างไปวางในเครื่องมือที่เลือก

---

## บล็อกที่ต้องคัดลอก

```
Design a mobile weather app focused on RAIN NOWCASTING for a civil engineer
who supervises a housing-estate construction site in Bang Pakong,
Chachoengsao province, Thailand.

=== CORE PURPOSE ===
This is NOT a generic weather app. Every screen answers one question:
"Will it rain on my construction site, when, and should I stop work?"
The user is standing outdoors in bright sun, holding the phone one-handed,
often wearing gloves. Decisions must be readable in under 3 seconds.

=== LANGUAGE ===
All UI text in Thai. Use a Thai-supporting typeface such as
IBM Plex Sans Thai, Noto Sans Thai, or Sarabun.
Numbers use tabular figures so they don't jitter when values update.

=== VISUAL DIRECTION ===
- Clean, calm, utilitarian — closer to a professional instrument than a
  consumer lifestyle app. No cartoon weather mascots, no playful gradients
  on primary data.
- Light mode primary, with a true dark mode variant for early-morning use.
- High contrast: this app is read in direct Thai sunlight. Body text must
  hit at least 7:1 contrast. Avoid thin font weights for data.
- One accent colour (deep blue #2563EB) for interactive elements only.
  Status colour is reserved exclusively for weather severity — never
  decorative.
- Generous spacing. Large tap targets (minimum 48x48dp) for gloved hands.
- Rounded corners 12-16px, soft single-layer shadows, no heavy bevels.

=== SEVERITY COLOUR SYSTEM (strict, used across all screens) ===
Green  #16A34A  ปลอดฝน       — no rain expected, safe for exterior work
Blue   #3B82C4  ฝนเบา         — light rain, under 2 mm/hr
Amber  #F59E0B  ฝนปานกลาง     — moderate rain, 2 to 7.5 mm/hr
Red    #DC2626  ฝนหนัก        — heavy rain, above 7.5 mm/hr
Purple #7C3AED  ลมแรง         — wind gust warning, above 40 km/hr
These colours must be paired with an icon and a text label so the app is
usable by colour-blind users. Never rely on colour alone.

=== SCREENS TO DESIGN ===

--- SCREEN 1: หน้าหลัก (Home / Now) ---
The single most important screen. Vertical scroll.

Top: location bar showing the current site name in Thai
     (e.g. "บางปะกง, ฉะเชิงเทรา") with a small pin icon and a chevron
     that opens the location switcher. Right side shows last-updated time.

Hero block: an oversized verdict card that fills roughly the top third.
     It states the decision in plain Thai, very large type:
       "ไม่มีฝน 3 ชม.ข้างหน้า" / "ฝนหนักอีก 40 นาที" / "ลมแรง หยุดงานที่สูง"
     Below it, one supporting line of practical advice for site work,
     e.g. "เหมาะกับงานเทคอนกรีต" or "คลุมวัสดุ เก็บเครื่องมือไฟฟ้า".
     The whole card takes the severity colour as a soft tinted background
     with a strong left border in the full-strength colour.

Countdown ribbon: if rain is expected, a prominent horizontal strip
     "ฝนจะถึงในอีก 40 นาที" with a small animated approach indicator.
     If no rain, this strip is replaced by a calm green confirmation.

Stat row: four compact metric tiles in a 2x2 grid or horizontal scroll:
     - ฝน 3 ชม.ข้างหน้า (mm)
     - โอกาสฝน (%)
     - ลมกระโชกสูงสุด (km/hr)
     - อุณหภูมิ / ความชื้น
     Each tile shows a large number, a small unit, and a tiny caption.
     Tiles adopt severity colour when they cross a threshold.

Hourly rain chart: horizontal scrolling bar chart, 24 hours ahead.
     Bars coloured by the severity system. Hour labels beneath.
     Current hour marked with a vertical accent line and bold label.
     Tapping a bar jumps the map to that hour.

Concrete-pour window finder: a distinctive horizontal timeline strip
     that highlights continuous dry windows of 6+ hours in green,
     labelled "ช่วงเทคอนกรีตได้ 09:00-16:00". This is the app's
     signature feature — give it visual weight.

--- SCREEN 2: แผนที่พยากรณ์ (Forecast Map) ---
Full-bleed map filling the screen, controls floating on top.

     - A translucent grid of coloured cells overlaid on the map showing
       forecast rainfall intensity, using the severity colours at about
       50% opacity so map labels stay readable underneath.
     - A pin marking the user's site, with a dashed 25 km radius ring.
     - Bottom sheet, draggable, containing a time scrubber for the next
       24 hours with a play/pause button. The scrubber shows the hour and
       a relative label ("อีก 3 ชม.").
     - A compact legend, collapsible.
     - A floating toggle chip: "ซ้อนเรดาร์จริง" to overlay live radar.
     - A floating locate-me button.
     Design both the collapsed bottom-sheet state (peek, showing just the
     scrubber) and the expanded state (showing legend and layer options).

--- SCREEN 3: เรดาร์ & ดาวเทียม (Radar & Satellite) ---
Segmented control at top with two tabs: เรดาร์ / ดาวเทียม.

     Radar tab: a vertically scrolling list of radar station cards.
     Each card shows the station image, station name, distance from the
     site in km, and a one-line explanation of what that station is good
     for. The nearest station carries a small filled badge "ใกล้ที่สุด"
     and a highlighted border. Cards are tappable to open a full-screen
     zoomable viewer with an animation loop control.

     Satellite tab: three cards for infrared, visible, and water-vapour
     imagery. Each carries a short plain-Thai explanation of when that
     image type is useful — this is a teaching surface, not just a gallery.

--- SCREEN 4: ตั้งค่าการแจ้งเตือน (Alert Settings) ---
A settings form with grouped sections.

     - Master toggle for push notifications.
     - Threshold sliders with live plain-Thai preview of what each setting
       means, e.g. moving the rain slider updates a sentence reading
       "จะเตือนเมื่อคาดว่าฝนตกเกิน 0.5 มม./ชม."
       Sliders: rain intensity, rain probability, wind gust.
     - Lead time selector as a segmented control: 30 นาที / 1 ชม. / 3 ชม.
     - Quiet hours with a time-range picker.
     - Cooldown control to prevent repeat alerts.
     - A section listing saved sites, each row with a name, coordinates,
       and its own enable toggle, so alerts can differ per site.

--- SCREEN 5: เลือกตำแหน่ง (Location Switcher) ---
Presented as a modal sheet sliding from the bottom.

     - A prominent "ใช้ตำแหน่งปัจจุบัน" button with a GPS icon at top.
     - A search field.
     - A saved-sites list with swipe-to-delete and a star for the default.
     - A grouped list of preset districts, with a section header for
       ฉะเชิงเทรา and another for จังหวัดใกล้เคียง.
     - A small map preview at the bottom where the user can drop a pin
       manually.

--- SCREEN 6: การแจ้งเตือนแบบ Push ---
Design the notification appearances themselves, on both lock screen
and as an expanded banner:
     - Rain alert with severity colour, headline, and the countdown.
     - Wind alert.
     - Morning daily summary.
Include a rich expanded state showing a miniature rain chart.

=== ADDITIONAL STATES TO DESIGN ===
- Loading skeletons for each screen.
- Offline state with the last-known data, clearly time-stamped and
  visually de-emphasised so stale data is never mistaken for live data.
- Error state when the location cannot be determined.
- Empty state for the saved-sites list.

=== DELIVERABLE ===
Produce each screen as a separate high-resolution portrait mockup at
iPhone dimensions, shown inside a subtle device frame. Keep typography
consistently sized across screens. Include a compact style-guide sheet
showing the colour tokens, type scale, and the icon set used.
```

---

## เคล็ดลับการใช้

**ถ้าเครื่องมือรับ prompt ยาวไม่ไหว** ให้ตัดเป็นทีละหน้าจอ — เอาส่วน `=== VISUAL DIRECTION ===`
กับ `=== SEVERITY COLOUR SYSTEM ===` แปะไปด้วยทุกครั้ง เพื่อให้สไตล์ตรงกันทุกหน้า

**ถ้าผลลัพธ์ออกมาดูเหมือนแอปทั่วไปเกินไป** เพิ่มบรรทัดนี้ต่อท้าย:

```
Avoid generic weather-app conventions: no large sun/cloud illustration
occupying the hero, no five-day forecast row as the primary element,
no city skyline backgrounds. The hero must be a text-based decision
statement, not an icon.
```

**ถ้าอยากได้โทนมืออาชีพกว่าเดิม** เพิ่ม:

```
Reference the visual language of aviation weather briefing tools and
industrial control dashboards rather than consumer weather apps.
```
