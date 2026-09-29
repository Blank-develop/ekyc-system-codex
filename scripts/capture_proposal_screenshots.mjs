import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const root = "/Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex";
const outDir = path.join(root, "outputs", "project_proposal", "screenshots");
const appUrl = "http://127.0.0.1:5173";
const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const baseResult = {
  session_id: "proposal-session-001",
  user_id: "user-20260521-demo",
  created_at: "2026-05-21T09:00:00Z",
  updated_at: "2026-05-21T09:04:00Z",
  decision: "passed",
  reason_codes: ["DOCUMENT_PASSED", "ACTIVE_LIVENESS_PASSED", "HAND_GESTURE_PASSED", "SELFIE_PASSED"],
  document: {
    status: "passed",
    image_quality_score: 0.94,
    fraud_risk_score: 0.12,
    document_likeness_score: 0.96,
    recapture_risk_score: 0.08,
    tamper_risk_score: 0.1,
    ocr: {
      document_type: "passport",
      full_name: "CHILANHOUTH NITVONGKHAY",
      document_number: "PA0523605",
      id_number: null,
      passport_number: "PA0523605",
      nationality: "LAO",
      date_of_birth: "2001-11-09",
      expiry_date: "2036-02-12",
      confidence: 0.92,
      mrz_text: "POLAONITVONGKHAY<<CHILANHOUTH<<<<<<<<<<<<",
      mrz_valid: true,
      mrz_check_digits_valid: true,
      extracted_fields: {
        surname: "NITVONGKHAY",
        given_names: "CHILANHOUTH",
        sex: "M"
      }
    },
    signals: [],
    checks: {
      expiry_valid: true,
      mrz_valid: true,
      visual_mrz_consistent: true
    }
  },
  biometric: {
    active_liveness_passed: true,
    hand_challenge_passed: true,
    active_liveness_checks: { blink: true, head_turn: true, mouth_open: true },
    active_liveness_signals: [],
    passive_liveness_passed: true,
    face_match_score: 0.86,
    passive_liveness_risk: 0.08,
    selfie_quality_score: 0.93,
    selfie_checks: { face_detected: true, multiple_faces: false, screen_replay_risk: "low" },
    selfie_signals: []
  },
  active_challenges: [
    { id: "blink", type: "active_liveness", prompt: "Blink", instruction: "Blink naturally once.", passed: true },
    { id: "turn_left", type: "active_liveness", prompt: "Turn left", instruction: "Turn your head left.", passed: true },
    { id: "open_mouth", type: "active_liveness", prompt: "Open mouth", instruction: "Open your mouth briefly.", passed: true }
  ],
  hand_challenges: [
    { id: "gesture_one", type: "hand_gesture", prompt: "Show 1", instruction: "Show one finger inside the circle.", passed: true },
    { id: "gesture_ok", type: "hand_gesture", prompt: "Show OK", instruction: "Show OK inside the circle.", passed: true },
    { id: "gesture_thumb", type: "hand_gesture", prompt: "Thumb up", instruction: "Show thumb up inside the circle.", passed: true }
  ]
};

const profile = {
  face_id: "face-demo-001",
  user_id: "user-20260521-demo",
  active: true,
  verification_session_id: "proposal-session-001",
  full_name: "CHILANHOUTH NITVONGKHAY",
  first_name: "CHILANHOUTH",
  last_name: "NITVONGKHAY",
  age: 24,
  date_of_birth: "2001-11-09",
  nationality: "LAO",
  passport_number: "PA0523605",
  passport_expiry: "2036-02-12",
  enrolled_at: "2026-05-21T09:05:00Z",
  last_login_at: "2026-05-21T09:10:00Z"
};

async function screenshot(page, name) {
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: true });
}

async function clickByText(page, text) {
  await page.getByText(text, { exact: false }).first().click();
  await page.waitForTimeout(450);
}

async function main() {
  await fs.mkdir(outDir, { recursive: true });
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 980 },
    deviceScaleFactor: 1
  });
  const page = await context.newPage();

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/api/face-login")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          decision: "passed",
          matched: true,
          match_score: 0.91,
          passive_liveness_risk: 0.06,
          reason_codes: ["FACE_LOGIN_PASSED"],
          profile,
          checks: { face_detected: true, liveness: "passed" },
          signals: []
        })
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(baseResult)
    });
  });

  await page.goto(appUrl, { waitUntil: "networkidle" });
  await screenshot(page, "01-start-page");

  await page.getByRole("button", { name: /new user signup/i }).click();
  await screenshot(page, "02-new-user-signup");

  await page.getByRole("button", { name: /start verification/i }).click();
  await page.waitForSelector("text=Secure document eKYC", { timeout: 10000 });
  await page.waitForTimeout(1000);
  await screenshot(page, "03-document-proofing");

  await clickByText(page, "Face liveness");
  await screenshot(page, "04-active-liveness");

  await clickByText(page, "Gesture");
  await screenshot(page, "05-gesture-challenge");

  await clickByText(page, "Selfie");
  await screenshot(page, "06-selfie-face-match");

  await clickByText(page, "Result");
  await screenshot(page, "07-result-decision");

  await page.goto(appUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /face login only/i }).click();
  await screenshot(page, "08-face-login");

  await page.goto(appUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /face pay transfer/i }).click();
  await screenshot(page, "09-face-pay-transfer");

  await browser.close();
  console.log(JSON.stringify({ outDir }, null, 2));
}

await main();
