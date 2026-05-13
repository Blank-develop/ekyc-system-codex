# LALIGENCE Mobile SDK

The mobile SDK is a small TypeScript client for the deployed FastAPI backend. It does not run OCR, face matching, or anti-spoofing on the phone; it sends captured images to the eKYC API and returns the backend decision, scores, reason codes, and verified profile.

## Package

Local package:

```bash
npm --workspace @laligence/ekyc-sdk run build
```

Use it from this repo during app development:

```json
{
  "dependencies": {
    "@laligence/ekyc-sdk": "file:../ekyc-system-codex/sdk/typescript"
  }
}
```

For company-wide mobile apps, publish the built package to a private npm registry or GitHub Packages.

## React Native / Expo Example

```ts
import { EkycClient } from "@laligence/ekyc-sdk";

const ekyc = new EkycClient({
  baseUrl: "https://ekyc-system-backend-singapore.onrender.com",
  defaultRetries: 2,
  defaultTimeoutMs: 90000
});

const session = await ekyc.createVerification("user-001");

const afterDocument = await ekyc.uploadDocument(session.session_id, {
  uri: passportImageUri,
  name: "passport.jpg",
  type: "image/jpeg"
});

for (const challenge of afterDocument.active_challenges) {
  await ekyc.completeChallenge(afterDocument.session_id, challenge.id, true);
}

for (const challenge of afterDocument.hand_challenges) {
  await ekyc.completeChallenge(afterDocument.session_id, challenge.id, true);
}

const afterSelfie = await ekyc.analyzeSelfie(afterDocument.session_id, {
  uri: selfieImageUri,
  name: "selfie.jpg",
  type: "image/jpeg"
});

if (afterSelfie.decision === "passed") {
  const enrollment = await ekyc.enrollFace(afterSelfie.session_id);
  console.log(enrollment.profile.face_id);
}
```

## Returning Face Login

```ts
const login = await ekyc.faceLogin({
  uri: liveSelfieUri,
  name: "face-login.jpg",
  type: "image/jpeg"
});

if (login.matched && login.profile) {
  console.log("Welcome", login.profile.full_name);
}
```

## Mobile Flow

1. New user enters a real app `user_id` during signup.
2. Mobile app captures passport image and calls `uploadDocument`.
3. Mobile app performs active liveness and hand gesture challenges locally, then calls `completeChallenge`.
4. Mobile app captures a live selfie and calls `analyzeSelfie`.
5. If the verification decision is `passed`, mobile app calls `enrollFace`.
6. Returning users skip passport proofing and call `faceLogin` with a fresh live selfie.

## Notes

- Camera permissions are handled by the mobile app, not the SDK.
- Use `https` backend URLs for mobile camera and upload workflows.
- The backend CORS allowlist does not block native mobile requests, but it still matters for web or WebView builds.
- The SDK accepts `Blob`, `File`, or React Native image objects shaped like `{ uri, name, type }`.
- Admin helpers `listProfiles`, `deleteProfile`, and `deleteProfiles` exist for testing only. Protect or remove those backend routes before production.
