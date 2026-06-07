import { chromium } from "playwright-core";

const BASE = process.argv[2] || "http://127.0.0.1:8020";
const CHROME = process.env.CHROME_BIN;
const OUT = "scripts/shots/";

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const ctx = await browser.newContext({
  viewport: { width: 390, height: 844 },      // iPhone 12/13/14
  deviceScaleFactor: 2, isMobile: true, hasTouch: true,
});
const page = await ctx.newPage();

async function login(email, pw) {
  await page.goto(`${BASE}/accounts/logout/`, { waitUntil: "networkidle" });
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" });
  await page.fill("input[name=email]", email);
  await page.fill("input[name=password]", pw);
  await page.click("button[type=submit]");
  await page.waitForLoadState("networkidle");
}

// 1) Home with nav collapsed
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}m1-home.png`, fullPage: false });

// 2) Home with the hamburger menu open
await page.click(".nav-toggle");
await page.waitForTimeout(250);
await page.screenshot({ path: `${OUT}m2-nav-open.png`, fullPage: false });

// 3) A data-heavy table page (finance dashboard) to prove horizontal scroll
await login("finance@mwar.org.pk", "staff12345");
await page.goto(`${BASE}/dues/staff/dashboard/`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}m3-finance.png`, fullPage: false });

// 4) The member pay-dues form
await login("member@mwar.org.pk", "member12345");
await page.goto(`${BASE}/dues/pay/`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}m4-pay.png`, fullPage: true });

console.log("Mobile screenshots written.");
await browser.close();
