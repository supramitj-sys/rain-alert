/* =====================================================================
   Service Worker — เช็คฝน
   ---------------------------------------------------------------------
   หน้าที่: ทำให้แอปเปิดได้ทันทีและเปิดได้แม้ไม่มีเน็ต (แสดงหน้าเดิม)

   หลักการสำคัญ:
     - ไฟล์แอป (HTML/ไอคอน/ไลบรารี) → cache-first  เปิดเร็ว
     - ข้อมูลอากาศ (API/ภาพเรดาร์)   → network-only ห้าม cache เด็ดขาด
       เพราะข้อมูลอากาศเก่าอันตรายกว่าไม่มีข้อมูล
   ===================================================================== */

/* เลขเวอร์ชันนี้ต้องเลื่อนทุกครั้งที่แก้ index.html
   ไม่งั้นเบราว์เซอร์จะหยิบหน้าเก่าจาก cache มาแสดงก่อน แล้วค่อยอัปเดตรอบถัดไป
   ทำให้เห็นของใหม่ช้าไป 1 รอบ */
const CACHE = 'checkfon-v3';

const SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/apple-touch-icon.png',
  './icons/favicon.png',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
];

/* โดเมนที่ห้าม cache — ต้องสดเสมอ */
const NEVER_CACHE = [
  'api.open-meteo.com',
  'marine-api.open-meteo.com',      // ข้อมูลน้ำขึ้นน้ำลง ต้องสดเสมอ
  'geocoding-api.open-meteo.com',
  'api.rainviewer.com',
  'tilecache.rainviewer.com',
  'api.bigdatacloud.net',
  'weather.tmd.go.th',
  'sattmet.tmd.go.th',
  'tile.openstreetmap.org'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      // ใช้ทีละไฟล์ เพื่อไม่ให้ไฟล์เดียวพังแล้วล้มทั้งชุด
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  /* ข้อมูลสด — ผ่านตรงไปเครือข่ายเสมอ ไม่แตะ cache */
  if (NEVER_CACHE.some(h => url.hostname.includes(h))) return;

  /* ไฟล์แอป — เอาจาก cache ก่อน แล้วอัปเดตเบื้องหลัง */
  e.respondWith(
    caches.match(req).then(hit => {
      const net = fetch(req).then(res => {
        if (res && res.status === 200 && (res.type === 'basic' || res.type === 'cors')) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
