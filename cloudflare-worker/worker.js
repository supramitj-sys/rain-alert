/**
 * =====================================================================
 *  บอทอากาศ บางปะกง — Cloudflare Worker
 * ---------------------------------------------------------------------
 *  รันบนเซิร์ฟเวอร์ Cloudflare ฟรี ทำงาน 24 ชม. ไม่ต้องเปิดคอม
 *  ตอบทันทีที่พิมพ์ ไม่มีดีเลย์
 *
 *  วิธีติดตั้ง: ดูไฟล์ วิธีติดตั้ง_Cloudflare.md
 *
 *  ตัวแปรที่ต้องตั้งใน Settings > Variables and Secrets:
 *    TELEGRAM_TOKEN   (Secret)  TOKEN จาก BotFather
 *    TELEGRAM_CHAT_ID (Secret)  CHAT_ID ของคุณ — กันคนอื่นมาใช้บอท
 *    WEBHOOK_SECRET   (Secret)  รหัสอะไรก็ได้ที่คุณตั้งเอง ใช้ยืนยันว่า
 *                               คำขอมาจาก Telegram จริง ไม่ใช่คนสุ่มยิง
 *    TMD_TOKEN        (Secret)  โทเคนกรมอุตุฯ (ไม่ใส่ก็ได้ — คำสั่ง "ลม" จะ
 *                               ไม่มีทิศทางลม มีแต่ความแรง)
 *    WX_LAT           (Text)    13.53
 *    WX_LON           (Text)    100.99
 *    WX_PLACE         (Text)    บางปะกง
 * =====================================================================
 */

export default {
  async fetch(request, env) {
    // ---------- หน้าเช็คสถานะ เปิดด้วยเบราว์เซอร์ได้ ----------
    if (request.method === "GET") {
      return new Response(
        "บอทอากาศทำงานอยู่ ✅\n\n" +
        "หน้านี้มีไว้เช็คว่า Worker deploy สำเร็จเท่านั้น\n" +
        "การใช้งานจริงให้พิมพ์คุยกับบอทใน Telegram",
        { headers: { "content-type": "text/plain; charset=utf-8" } }
      );
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    // ---------- ยืนยันว่าคำขอมาจาก Telegram จริง ----------
    // ถ้าไม่เช็คตรงนี้ ใครก็ยิง URL นี้แล้วสั่งบอทส่งข้อความได้
    const got = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.WEBHOOK_SECRET || got !== env.WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("ok");   // ตอบ ok เสมอ ไม่งั้น Telegram จะยิงซ้ำ
    }

    const msg = update.message || update.edited_message;
    if (!msg || !msg.text) return new Response("ok");

    const chatId = String(msg.chat.id);

    // ---------- ตอบเฉพาะเจ้าของบอท ----------
    if (env.TELEGRAM_CHAT_ID && chatId !== String(env.TELEGRAM_CHAT_ID)) {
      return new Response("ok");
    }

    const cfg = {
      lat: parseFloat(env.WX_LAT || "13.53"),
      lon: parseFloat(env.WX_LON || "100.99"),
      place: env.WX_PLACE || "บางปะกง",
      tmdToken: env.TMD_TOKEN || "",
    };

    let reply;
    try {
      reply = await handle(msg.text, cfg);
    } catch (e) {
      reply = "❌ เกิดข้อผิดพลาด: " + e.message;
    }

    await send(env.TELEGRAM_TOKEN, chatId, reply);
    return new Response("ok");
  },
};

/* =====================================================================
   ส่งข้อความกลับ Telegram
   ===================================================================== */
async function send(token, chatId, text) {
  await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });
}

/* =====================================================================
   เวลาไทย — Worker รันบนเครื่อง UTC จึงต้องบวก 7 เอง
   ===================================================================== */
function nowTH() {
  return new Date(Date.now() + 7 * 3600 * 1000);
}
function hhmm(d) {
  return String(d.getUTCHours()).padStart(2, "0") + ":" +
         String(d.getUTCMinutes()).padStart(2, "0");
}
/* แปลงเวลาจาก Open-Meteo (เป็นเวลาไทยอยู่แล้ว แต่ไม่มี offset)
   ให้เป็น Date ที่อ่านด้วย getUTC* แล้วได้เวลาไทย */
function parseLocal(s) {
  return new Date(s + "Z");
}

/* =====================================================================
   ดึงพยากรณ์
   ===================================================================== */
async function fetchWx(cfg, days) {
  const url = "https://api.open-meteo.com/v1/forecast" +
    `?latitude=${cfg.lat}&longitude=${cfg.lon}` +
    "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m" +
    "&hourly=precipitation,precipitation_probability,temperature_2m,wind_gusts_10m," +
    "cape,uv_index,apparent_temperature" +
    "&daily=precipitation_sum,precipitation_probability_max,temperature_2m_max," +
    "temperature_2m_min,wind_gusts_10m_max,uv_index_max,apparent_temperature_max" +
    "&timezone=Asia%2FBangkok&forecast_days=" + days;

  const r = await fetch(url, { cf: { cacheTtl: 300 } });
  if (!r.ok) throw new Error("Open-Meteo ตอบ " + r.status);
  return r.json();
}

function hourIndex(d) {
  const now = nowTH().getTime();
  const t = d.hourly.time;
  for (let i = 0; i < t.length; i++) {
    if (parseLocal(t[i]).getTime() >= now) return Math.max(0, i - 1);
  }
  return 0;
}

function rainLevel(mm) {
  if (mm < 0.1) return ["ไม่มีฝน", "☀️"];
  if (mm < 0.5) return ["ฝนปรอย", "🌦️"];
  if (mm < 2)   return ["ฝนเบา", "🌦️"];
  if (mm < 7.5) return ["ฝนปานกลาง", "🌧️"];
  if (mm < 15)  return ["ฝนหนัก", "⛈️"];
  return ["ฝนหนักมาก", "⛈️"];
}

/* =====================================================================
   TMD (กรมอุตุฯ) — ใช้เฉพาะตอนต้องการทิศทางลม (Open-Meteo world model
   ที่ใช้คำนวณลมกระโชกด้านบนไม่มีทิศทางลมให้)
   ===================================================================== */
async function fetchTmd(cfg, hours) {
  if (!cfg.tmdToken) return null;
  const t = nowTH();
  const date = `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}` +
               `-${String(t.getUTCDate()).padStart(2, "0")}`;
  const url = "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/at" +
    `?lat=${cfg.lat}&lon=${cfg.lon}&fields=tc,rh,rain,ws10m,wd10m,slp,cond,cloudlow` +
    `&date=${date}&hour=${t.getUTCHours()}&duration=${hours}`;
  try {
    const r = await fetch(url, {
      headers: { accept: "application/json", authorization: "Bearer " + cfg.tmdToken },
    });
    if (!r.ok) return null;
    const d = await r.json();
    const fc = d && d.WeatherForecasts && d.WeatherForecasts[0] && d.WeatherForecasts[0].forecasts;
    if (!fc) return null;
    const out = {};
    for (const f of fc) {
      if (!f.time || !f.data || f.data.rain == null) continue;
      const key = String(f.time).replace(" ", "T").slice(0, 13);
      out[key] = f.data;
    }
    return out;
  } catch {
    return null;
  }
}

/* แปลงองศาทิศทางลมเป็นป้ายกำกับ "มาจากทิศไหน" + ลูกศรชี้ทิศที่ลมพัดไปหา
   (ทิศทางลมทางอุตุนิยมวิทยาบอกทิศที่ลม "มาจาก" ไม่ใช่ทิศที่พัดไป) */
function windCompass(deg) {
  if (deg == null) return null;
  deg = ((deg % 360) + 360) % 360;
  const idx = Math.round(deg / 45) % 8;
  const flowIdx = (idx + 4) % 8;
  const names  = ["เหนือ", "ตะวันออกเฉียงเหนือ", "ตะวันออก", "ตะวันออกเฉียงใต้",
                   "ใต้", "ตะวันตกเฉียงใต้", "ตะวันตก", "ตะวันตกเฉียงเหนือ"];
  const codes  = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const arrows = ["⬆️", "↗️", "➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️"];
  return { fromTh: names[idx], fromCode: codes[idx], arrow: arrows[flowIdx] };
}

/* =====================================================================
   คำสั่ง
   ===================================================================== */
async function cmdNow(cfg) {
  const d = await fetchWx(cfg, 1);
  const c = d.current, H = d.hourly, i = hourIndex(d);

  const nxt  = H.precipitation.slice(i, i + 3);
  const prob = H.precipitation_probability.slice(i, i + 3);
  const gust = H.wind_gusts_10m.slice(i, i + 3);
  const rain3 = nxt.reduce((a, b) => a + (b || 0), 0);
  const [lvl, icon] = rainLevel(rain3);

  const L = [
    `${icon} <b>${cfg.place}</b> — ${hhmm(nowTH())}`,
    "",
    `🌡️ อุณหภูมิ ${c.temperature_2m.toFixed(0)}°C · ความชื้น ${c.relative_humidity_2m.toFixed(0)}%`,
    `💨 ลม ${c.wind_speed_10m.toFixed(0)} กม./ชม.`,
    "",
    `<b>3 ชม.ข้างหน้า: ${lvl}</b>`,
  ];
  for (let k = 0; k < nxt.length; k++) {
    const t = parseLocal(H.time[i + k]);
    const mm = nxt[k] || 0;
    const bar = mm >= 0.1 ? "█".repeat(Math.min(10, Math.round(mm * 2))) : "—";
    L.push(`  ${hhmm(t)}  ${mm.toFixed(1).padStart(4)} มม.  ` +
           `${String(Math.round(prob[k] || 0)).padStart(3)}%  ${bar}`);
  }
  const mg = Math.max(...gust.map(g => g || 0));
  if (mg >= 40) {
    L.push("", `⚠️ ลมกระโชกถึง ${mg.toFixed(0)} กม./ชม. — ระวังนั่งร้าน ผ้าใบคลุม`);
  }
  return L.join("\n");
}

async function cmdRain(cfg) {
  const d = await fetchWx(cfg, 2);
  const H = d.hourly, i = hourIndex(d);
  const now = nowTH().getTime();

  for (let k = i; k < Math.min(i + 24, H.time.length); k++) {
    const mm = H.precipitation[k] || 0;
    if (mm >= 0.5) {
      const t = parseLocal(H.time[k]);
      const gap = (t.getTime() - now) / 3600000;
      const [lvl, icon] = rainLevel(mm);
      const when = gap < 0.5 ? "กำลังตกอยู่" : `อีกประมาณ ${gap.toFixed(0)} ชม. (${hhmm(t)})`;
      return `${icon} <b>${lvl}</b> ที่${cfg.place}\n${when}\n` +
             `ปริมาณ ${mm.toFixed(1)} มม./ชม. · โอกาส ${Math.round(H.precipitation_probability[k] || 0)}%\n\n` +
             `<i>ข้อมูลเป็นรายชั่วโมง เวลาจึงเป็นค่าประมาณ</i>`;
    }
  }
  return `☀️ ไม่มีฝนที่${cfg.place}ใน 24 ชม.ข้างหน้า`;
}

async function cmdToday(cfg) {
  const d = await fetchWx(cfg, 3);
  const D = d.daily;
  const names = ["วันนี้", "พรุ่งนี้", "มะรืน"];
  const out = [`📅 <b>${cfg.place}</b> — สรุปพยากรณ์`, ""];

  for (let k = 0; k < Math.min(3, D.time.length); k++) {
    const mm = D.precipitation_sum[k] || 0;
    const [, icon] = rainLevel(mm / 8);
    out.push(
      `${icon} <b>${names[k]}</b>  ฝนรวม ${mm.toFixed(1)} มม. · ` +
      `โอกาส ${Math.round(D.precipitation_probability_max[k] || 0)}%\n` +
      `    ${D.temperature_2m_min[k].toFixed(0)}–${D.temperature_2m_max[k].toFixed(0)}°C` +
      ` · ลมสูงสุด ${Math.round(D.wind_gusts_10m_max[k] || 0)} กม./ชม.`
    );
  }

  const H = d.hourly, i = hourIndex(d), end = Math.min(i + 12, H.time.length);
  const cape = maxOf(H,"cape",i,end), uvm = maxOf(H,"uv_index",i,end),
        ht = maxOf(H,"apparent_temperature",i,end);
  const [cl,cLab] = capeLevel(cape), [ul,uLab] = uvLevel(uvm), [hl,hLab] = heatLevel(ht);
  out.push("", "<b>ความเสี่ยงอื่นวันนี้</b>",
    `${ICON_LV[cl]} ฟ้าคะนอง: ${cLab}` + (cape==null?"":` (${cape.toFixed(0)} J/kg)`),
    `${ICON_LV[ul]} UV: ${uLab}` + (uvm==null?"":` (${uvm.toFixed(0)})`),
    `${ICON_LV[hl]} ความร้อน: ${hLab}` + (ht==null?"":` (${ht.toFixed(0)}°C)`));
  return out.join("\n");
}

async function cmdConcrete(cfg) {
  const d = await fetchWx(cfg, 2);
  const H = d.hourly, i = hourIndex(d);
  const end = Math.min(i + 36, H.time.length);

  const windows = [];
  let run = [];
  for (let k = i; k < end; k++) {
    const mm = H.precipitation[k] || 0;
    if (mm < 0.2) {
      run.push(parseLocal(H.time[k]));
    } else {
      if (run.length >= 6) windows.push([run[0], run[run.length - 1]]);
      run = [];
    }
  }
  if (run.length >= 6) windows.push([run[0], run[run.length - 1]]);

  if (!windows.length) {
    return `⛔ <b>ไม่มีช่วงแห้งต่อเนื่อง 6 ชม.</b> ที่${cfg.place}ใน 36 ชม.ข้างหน้า\n` +
           `ไม่แนะนำให้ล็อกคิวรถโม่`;
  }

  const today = nowTH().getUTCDate();
  const out = [`🧱 <b>ช่วงเทคอนกรีตได้ — ${cfg.place}</b>`, ""];
  for (const [a, b] of windows.slice(0, 4)) {
    const hrs = Math.round((b - a) / 3600000) + 1;
    const day = a.getUTCDate() === today ? "" :
      ` (${String(a.getUTCDate()).padStart(2, "0")}/${String(a.getUTCMonth() + 1).padStart(2, "0")})`;
    out.push(`✅ ${hhmm(a)} – ${hhmm(b)}${day}  (${hrs} ชม.)`);
  }
  out.push("", "<i>เกณฑ์: ฝนต่ำกว่า 0.2 มม./ชม. ติดต่อกัน 6 ชม.ขึ้นไป",
           "คอนกรีตสดต้องการเวลาแห้ง 4-6 ชม. ฝนใน 2 ชม.แรกทำผิวหน้าเสีย</i>");
  return out.join("\n");
}

async function cmdWind(cfg) {
  const d = await fetchWx(cfg, 1);
  const H = d.hourly, i = hourIndex(d);
  const g = [];
  for (let k = i; k < Math.min(i + 12, H.time.length); k++) {
    g.push([parseLocal(H.time[k]), H.wind_gusts_10m[k] || 0]);
  }
  const mx = Math.max(...g.map(x => x[1]));

  let head;
  if (mx >= 60)      head = "🛑 <b>ลมแรงมาก</b> — หยุดงานที่สูงทั้งหมด ตรวจยึดโยงนั่งร้าน";
  else if (mx >= 50) head = "⚠️ <b>ลมแรง</b> — ควรหยุดงานยกของด้วยเครน/รถเฮี๊ยบ";
  else if (mx >= 40) head = "💨 <b>ลมค่อนข้างแรง</b> — ระวังผ้าใบคลุม แผ่นเมทัลชีท";
  else               head = "✅ ลมปกติ ทำงานได้ตามแผน";

  const out = [head, "", `สูงสุด ${mx.toFixed(0)} กม./ชม. ใน 12 ชม.ข้างหน้า`];

  // ทิศทางลม — Open-Meteo world model ด้านบนไม่มีทิศทางลมให้ ต้องขอจาก TMD
  if (cfg.tmdToken) {
    const tmd = await fetchTmd(cfg, 6);
    if (tmd) {
      let best = null;
      for (const [k, v] of Object.entries(tmd)) {
        if (v.ws10m != null && (!best || v.ws10m > best[1].ws10m)) best = [k, v];
      }
      const wc = best ? windCompass(best[1].wd10m) : null;
      out.push(wc
        ? `🧭 ทิศทางล่าสุด: มาจากทิศ${wc.fromTh} (${wc.fromCode}) ${wc.arrow}`
        : "🧭 ทิศทางลม: TMD ไม่ส่งค่าทิศทางมาในรอบนี้");
    } else {
      out.push("🧭 ทิศทางลม: ดึงจาก TMD ไม่ได้ตอนนี้ (โทเคนอาจหมดอายุ)");
    }
  } else {
    out.push("🧭 ทิศทางลม: ยังไม่ได้ตั้งค่า TMD_TOKEN — มีแต่ความแรงลม ไม่มีทิศทาง");
  }

  out.push("");
  for (let k = 0; k < g.length; k += 3) {
    out.push(`  ${hhmm(g[k][0])}  ${String(Math.round(g[k][1])).padStart(3)} กม./ชม.`);
  }
  return out.join("\n");
}

/* =====================================================================
   เกณฑ์ความเสี่ยงเพิ่มเติม
   ===================================================================== */
function capeLevel(v){
  if(v == null) return [0,"ไม่มีข้อมูล",""];
  if(v < 500)   return [1,"บรรยากาศเสถียร","โอกาสฟ้าคะนองต่ำ"];
  if(v < 1000)  return [1,"เสถียรปานกลาง","อาจมีฝนฟ้าคะนองเล็กน้อย"];
  if(v < 2500)  return [2,"เสี่ยงฟ้าคะนอง","ระวังฝนฟ้าคะนองก่อตัวเร็วช่วงบ่าย"];
  return [3,"เสี่ยงพายุรุนแรง","อาจมีลมกระโชกแรง ฟ้าผ่า — เตรียมหยุดงานที่สูง"];
}
function uvLevel(v){
  if(v == null) return [0,"ไม่มีข้อมูล",""];
  if(v < 3)     return [1,"ต่ำ","ไม่ต้องป้องกันเป็นพิเศษ"];
  if(v < 6)     return [1,"ปานกลาง","ควรใส่หมวกและเสื้อแขนยาว"];
  if(v < 8)     return [2,"สูง","เลี่ยงแดดจัด 11:00-15:00 ทาครีมกันแดด"];
  if(v < 11)    return [3,"สูงมาก","จำกัดเวลากลางแจ้ง จัดจุดพักในร่ม"];
  return [3,"อันตรายมาก","หลีกเลี่ยงกลางแจ้งช่วงเที่ยง"];
}
function heatLevel(v){
  if(v == null) return [0,"ไม่มีข้อมูล",""];
  if(v < 32)    return [1,"ปกติ","ทำงานได้ตามปกติ"];
  if(v < 41)    return [2,"ร้อนจัด","เพิ่มรอบพัก จัดน้ำดื่มให้เพียงพอ"];
  if(v < 54)    return [3,"อันตราย","เสี่ยงตะคริวและเพลียแดด พัก 15 นาทีทุกชั่วโมง"];
  return [3,"อันตรายมาก","เสี่ยงโรคลมแดด ควรเลื่อนงานกลางแจ้ง"];
}
const ICON_LV = {0:"⬜",1:"🟢",2:"🟡",3:"🔴"};

function maxOf(H, key, i, end){
  const a = (H[key] || []).slice(i, end).filter(x => x != null);
  return a.length ? Math.max(...a) : null;
}

async function cmdHeat(cfg){
  const d = await fetchWx(cfg, 1);
  const H = d.hourly, i = hourIndex(d), end = Math.min(i + 12, H.time.length);
  const heat = maxOf(H,"apparent_temperature",i,end);
  const uv   = maxOf(H,"uv_index",i,end);
  const cape = maxOf(H,"cape",i,end);
  const [hl,hLab,hMsg] = heatLevel(heat);
  const [ul,uLab,uMsg] = uvLevel(uv);
  const [cl,cLab,cMsg] = capeLevel(cape);

  const L = [`🥵 <b>ความเสี่ยงต่อคนงาน — ${cfg.place}</b>`,
             "<i>ค่าสูงสุดใน 12 ชม.ข้างหน้า</i>",""];
  L.push(`${ICON_LV[hl]} <b>อุณหภูมิที่รู้สึกได้ ${heat==null?"—":heat.toFixed(0)+"°C"}</b> · ${hLab}`);
  if(hMsg) L.push(`    ${hMsg}`);
  L.push("", `${ICON_LV[ul]} <b>ดัชนี UV ${uv==null?"—":uv.toFixed(0)}</b> · ${uLab}`);
  if(uMsg) L.push(`    ${uMsg}`);
  L.push("", `${ICON_LV[cl]} <b>ฟ้าคะนอง (CAPE) ${cape==null?"—":cape.toFixed(0)+" J/kg"}</b> · ${cLab}`);
  if(cMsg) L.push(`    ${cMsg}`);
  L.push("", "<i>อุณหภูมิที่รู้สึกได้คำนวณจากอุณหภูมิ ความชื้น ลม และแดด",
             "ไม่ใช่ค่า WBGT ตามมาตรฐานความปลอดภัยในการทำงาน ใช้เป็นแนวทางเท่านั้น</i>");
  return L.join("\n");
}

async function cmdTide(cfg){
  const url = "https://marine-api.open-meteo.com/v1/marine"
    + `?latitude=${cfg.lat}&longitude=${cfg.lon}`
    + "&hourly=sea_level_height_msl&timezone=Asia%2FBangkok"
    + "&forecast_days=2&cell_selection=sea";

  let d;
  try{
    const r = await fetch(url, { cf: { cacheTtl: 900 } });
    if(!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  }catch(e){ return "❌ ดึงข้อมูลน้ำไม่ได้ (" + e.message + ")"; }

  const t = d.hourly.time, v = d.hourly.sea_level_height_msl;
  if(!v || v.every(x => x == null)){
    return `❌ ไม่มีข้อมูลน้ำสำหรับพิกัด ${cfg.place}\n`
         + "พิกัดอาจอยู่ลึกเข้าไปในแผ่นดินเกินกว่าที่โมเดลน้ำทะเลครอบคลุม";
  }

  const now = nowTH().getTime();
  let ex = [];
  for(let i = 1; i < v.length - 1; i++){
    if(v[i]==null || v[i-1]==null || v[i+1]==null) continue;
    const hi = v[i] >= v[i-1] && v[i] >= v[i+1];
    const lo = v[i] <= v[i-1] && v[i] <= v[i+1];
    if(hi || lo){
      const tm = parseLocal(t[i]);
      if(tm.getTime() >= now) ex.push({t: tm, v: v[i], hi});
    }
  }
  /* กรองจุดซ้ำจาก plateau — จุดชนิดเดียวกันต้องห่างกันอย่างน้อย 4 ชม. */
  const ded = [];
  for(const e of ex){
    const last = ded[ded.length-1];
    if(last && last.hi === e.hi && (e.t - last.t) < 4*3600*1000){
      if(e.hi ? e.v > last.v : e.v < last.v) ded[ded.length-1] = e;
      continue;
    }
    ded.push(e);
  }
  if(!ded.length) return "ไม่พบจุดน้ำขึ้น-น้ำลงในช่วง 48 ชม.ข้างหน้า";

  const L = [`🌊 <b>น้ำขึ้น-น้ำลง — ${cfg.place}</b>`, ""];
  for(const e of ded.slice(0,6)){
    const gap = (e.t.getTime() - now) / 3600000;
    L.push(`${e.hi?"▲ น้ำขึ้น":"▼ น้ำลง"}  ${hhmm(e.t)}  `
         + `(${e.v>=0?"+":""}${e.v.toFixed(2)} ม.)  อีก ${gap.toFixed(0)} ชม.`);
  }

  /* เช็คว่าฝนหนักตรงกับน้ำขึ้นสูงไหม */
  try{
    const w = await fetchWx(cfg, 2);
    const H = w.hourly, i = hourIndex(w);
    const clash = [];
    for(const e of ded){
      if(!e.hi) continue;
      for(let k = i; k < Math.min(i+36, H.time.length); k++){
        const mm = H.precipitation[k] || 0;
        if(mm >= 7.5 && Math.abs(parseLocal(H.time[k]) - e.t) <= 90*60*1000){
          clash.push([e, mm]); break;
        }
      }
    }
    if(clash.length){
      L.push("", "🚨 <b>ฝนหนักตรงกับช่วงน้ำขึ้นสูง</b>");
      for(const [e,mm] of clash.slice(0,3)){
        L.push(`    ${hhmm(e.t)} — ฝน ${mm.toFixed(1)} มม./ชม. + น้ำ ${e.v>=0?"+":""}${e.v.toFixed(2)} ม.`);
      }
      L.push("    น้ำระบายลงแม่น้ำช้ากว่าปกติ เสี่ยงท่วมขังในไซต์",
             "    ตรวจปั๊มสูบน้ำ ทางระบายน้ำ และความลาดชันบ่อขุดล่วงหน้า");
    }
  }catch(e){ /* ถ้าเช็คไม่ได้ก็ข้าม ไม่ให้ทั้งคำสั่งพัง */ }

  L.push("", "<i>⚠️ ค่าจากแบบจำลอง ความละเอียด ~8 กม. ไม่ใช่ตารางน้ำอย่างเป็นทางการ",
         "ผู้ให้บริการระบุว่าความแม่นยำในเขตชายฝั่งและปากแม่น้ำมีข้อจำกัด",
         "ถ้าต้องใช้ตัวเลขจริง อ้างอิงกรมอุทกศาสตร์ hydro.navy.mi.th",
         "ระดับอ้างอิงเป็นระดับน้ำทะเลปานกลางโลก ไม่ใช่ระดับน้ำลงต่ำสุด</i>");
  return L.join("\n");
}

function cmdRadar(cfg) {
  return `📡 <b>เรดาร์สด — ${cfg.place}</b>\n\n` +
    `<a href="https://www.rainviewer.com/map.html?loc=${cfg.lat},${cfg.lon},9">RainViewer (ซูมตรงพิกัดให้แล้ว)</a>\n` +
    `<a href="https://weather.tmd.go.th/svp120Loop.php">เรดาร์สุวรรณภูมิ (Loop)</a>\n` +
    `<a href="http://www.sattmet.tmd.go.th/satmet/thai/loop/ir/gifir_se.html">ภาพดาวเทียม IR (Loop)</a>\n\n` +
    `<i>ดาวเทียม IR เห็นเมฆฝนก่อตัวก่อนเรดาร์จับฝนได้ 1-3 ชม.</i>`;
}

function cmdHelp() {
  return "🤖 <b>คำสั่งที่ใช้ได้</b>\nพิมพ์ไทยหรืออังกฤษก็ได้ ไม่ต้องมี /\n\n" +
    "<b>ตอนนี้</b>  — อากาศตอนนี้ + 3 ชม.ข้างหน้า\n" +
    "<b>ฝน</b>      — ฝนจะตกกี่โมง อีกนานไหม\n" +
    "<b>วันนี้</b>   — สรุปวันนี้ พรุ่งนี้ มะรืน\n" +
    "<b>เท</b>      — ช่วงเวลาเทคอนกรีตได้\n" +
    "<b>ลม</b>      — ลมกระโชก 12 ชม.ข้างหน้า\n" +
    "<b>ร้อน</b>     — ความร้อน UV และความเสี่ยงฟ้าคะนอง\n" +
    "<b>น้ำ</b>      — น้ำขึ้น-น้ำลง + เตือนฝนหนักตรงน้ำขึ้น\n" +
    "<b>เรดาร์</b>   — ลิงก์ดูเรดาร์และดาวเทียมสด\n" +
    "<b>ช่วย</b>     — ข้อความนี้\n\n" +
    "<i>ที่มา: Open-Meteo / กรมอุตุนิยมวิทยา</i>";
}

/* =====================================================================
   แยกคำสั่ง
   ===================================================================== */
const ROUTES = [
  [["ตอนนี้", "now", "/now", "เดี๋ยวนี้", "ปัจจุบัน"], cmdNow],
  [["ฝน", "rain", "/rain", "ฝนตก", "จะตกไหม"], cmdRain],
  [["วันนี้", "today", "/today", "สรุป", "พรุ่งนี้"], cmdToday],
  [["เทคอนกรีต", "เทปูน", "คอนกรีต", "เท", "concrete", "/concrete"], cmdConcrete],
  [["ลมแรง", "ลม", "wind", "/wind"], cmdWind],
  [["เรดาร์", "radar", "/radar", "ดาวเทียม"], cmdRadar],
  [["น้ำขึ้น", "น้ำลง", "น้ำ", "tide", "/tide"], cmdTide],
  [["ความร้อน", "ร้อน", "แดด", "uv", "heat", "/heat"], cmdHeat],
  [["ช่วย", "help", "/help", "/start", "คำสั่ง", "คําสั่ง"], cmdHelp],
];

async function handle(text, cfg) {
  const t = text.trim().toLowerCase();
  for (const [keys, fn] of ROUTES) {
    if (keys.some(k => t === k || t.startsWith(k))) {
      return await fn(cfg);
    }
  }
  return "ไม่เข้าใจคำสั่งนี้\n\n" + cmdHelp();
}
