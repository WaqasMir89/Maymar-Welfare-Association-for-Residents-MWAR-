// Screenshot/E2E driver for the M.W.A.R platform.
//
// Drives the running dev server with headless Chromium (Playwright) — logs in,
// visits the key surfaces, and writes PNGs to scripts/shots/. Doubles as a
// smoke check: any page that 500s makes the script exit non-zero.
//
//   node scripts/shoot.mjs [baseURL]
//
// Requires the dev server to be running (see the run-mwar skill).

import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BASE = process.argv[2] || "http://127.0.0.1:8009";
const OUT = new URL("./shots/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const CHROME =
  process.env.CHROME_BIN ||
  `${process.env.HOME}/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome`;

// [path, filename, {login?, viewport?}]
const PAGES = [
  ["/", "01-home.png", {}],
  ["/content/projects/", "02-projects.png", {}],
  ["/about/", "02a-about.png", {}],
  ["/core/.. ", null, null], // placeholder removed below
  ["/transparency/", "03-transparency.png", {}],
  ["/members/apply/", "04-apply.png", {}],
  ["/accounts/login/", "05-login.png", {}],
  ["/accounts/password-reset/", "05a-password-reset.png", {}],
  ["/staff/", "06-staff-dashboard.png", { login: "secretary" }],
  ["/members/staff/queue/", "07-membership-queue.png", { login: "secretary" }],
  ["/dues/staff/billing/", "08-billing-board.png", { login: "finance" }],
  ["/dues/staff/donations/", "08a-donations.png", { login: "finance" }],
  ["/dues/staff/donations/record/", "08b-donation-form.png", { login: "finance" }],
  ["/dues/staff/expenses/", "08c-expenses.png", { login: "finance" }],
  ["/dues/staff/submissions/", "08e-payment-approvals.png", { login: "finance" }],
  ["/dues/pay/", "08f-pay-dues.png", { login: "member" }],
  ["/dues/staff/expenses/new/", "08d-expense-form.png", { login: "finance" }],
  ["/complaints/", "09-complaints.png", { login: "secretary" }],
  ["/content/events/", "11-events.png", { login: "secretary" }],
  ["/content/documents/", "11a-documents.png", { login: "secretary" }],
  ["/content/documents/upload/", "11b-document-upload.png", { login: "secretary" }],
  ["/content/notifications/", "12-notifications.png", { login: "member" }],
  ["/members/dashboard/", "13-member-dashboard.png", { login: "member" }],
  ["/", "10-home-urdu.png", { urdu: true }],
].filter((p) => p[1]);

const CREDS = {
  secretary: ["secretary@mwar.org.pk", "staff12345"],
  finance: ["finance@mwar.org.pk", "staff12345"],
  admin: ["admin@mwar.org.pk", "admin12345"],
  member: ["member@mwar.org.pk", "member12345"],
};

async function login(page, who) {
  const [email, password] = CREDS[who];
  // Ensure a clean session so the login form is actually shown.
  await page.goto(`${BASE}/accounts/logout/`, { waitUntil: "networkidle" });
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" });
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await Promise.all([
    page.waitForLoadState("networkidle"),
    page.click('button[type="submit"]'),
  ]);
}

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--no-sandbox", "--disable-gpu"],
});

let failures = 0;
let currentLogin = null;
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();

page.on("response", (r) => {
  if (r.url().startsWith(BASE) && r.status() >= 500) {
    console.error(`  !! ${r.status()} ${r.url()}`);
    failures++;
  }
});

for (const [path, file, opts] of PAGES) {
  if (opts.login && opts.login !== currentLogin) {
    await login(page, opts.login);
    currentLogin = opts.login;
  }
  if (opts.urdu) {
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    await page.click('.lang-switch button'); // toggle to Urdu
  }
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(350);
  await page.screenshot({ path: `${OUT}${file}`, fullPage: true });
  console.log(`  ✓ ${file}  (${path})`);
}

await browser.close();
console.log(failures ? `\n${failures} server error(s) seen` : "\nAll pages rendered cleanly.");
process.exit(failures ? 1 : 0);
