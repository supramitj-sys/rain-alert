/* คัดลอกไฟล์นี้เป็น config.js (ไฟล์เดียวกันโฟลเดอร์นี้) แล้วใส่ key ของ Google Weather API
   config.js ถูกกันไว้ใน .gitignore จะไม่ขึ้น GitHub แต่ลากไปกับโฟลเดอร์ pwa/ ตอนอัปขึ้น Netlify

   key ฝั่งเว็บใครเปิดดูซอร์สก็เห็น จึงต้องล็อกใน Google Cloud Console:
     1) Application restrictions = Websites → https://weatherbossku.netlify.app/*
     2) API restrictions = Weather API เท่านั้น
     3) ตั้งเพดานโควตา Weather API ต่อวัน (เช่น 300) ไม่ให้เกินโควตาฟรี 10,000 ครั้ง/เดือน

   ไม่มี config.js หรือปล่อยว่าง = หน้าเว็บซ่อนส่วน Google ที่เหลือทำงานปกติ */
window.GOOGLE_WEATHER_KEY = '';
