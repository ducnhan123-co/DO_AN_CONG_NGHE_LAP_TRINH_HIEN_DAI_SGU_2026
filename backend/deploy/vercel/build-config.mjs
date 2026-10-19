// Chạy lúc build trên Vercel: ghi frontend/config.js trỏ về backend thật.
// Đặt biến môi trường API_BASE_URL (vd https://api.ten-mien-cua-ban.com) trong Project Settings.
import { writeFileSync } from "node:fs";
const base = (process.env.API_BASE_URL || "").replace(/\/$/, "");
if (!base) { console.error("Thiếu API_BASE_URL"); process.exit(1); }
writeFileSync("config.js", `window.APP_API_BASE = ${JSON.stringify(base)};\n`);
console.log("config.js ->", base);
