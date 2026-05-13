# LALIGENCE eKYC SDK for Flutter

`laligence_ekyc` is a Dart and Flutter client SDK for the LALIGENCE eKYC backend API. It helps a mobile app connect to your verification backend for passport proofing, document fraud analysis, active liveness completion, selfie face matching, passive anti-spoofing, Face ID enrollment, and returning-user face login.

The SDK is intentionally thin. Your Flutter app owns the camera UI and user experience. The backend owns OCR, fraud detection, face matching, passive liveness, profile storage, and final decisions.

## What This SDK Does

- Creates a new eKYC verification session for a real app `user_id`.
- Uploads a passport image captured by the mobile app.
- Sends completed active liveness and hand gesture challenge results.
- Uploads a live selfie for passport-to-selfie face matching and passive liveness checks.
- Enrolls a verified user's Face ID after a passed verification.
- Performs returning-user face login with a fresh live selfie.
- Parses typed response models for decisions, OCR fields, biometric scores, reason codes, and verified profiles.
- Supports file-path uploads and in-memory byte uploads.

## What This SDK Does Not Do

- It does not open the camera.
- It does not perform on-device OCR.
- It does not run face recognition or passive anti-spoofing on the phone.
- It does not store passport images, selfies, or biometric templates on the device.
- It does not replace your app's consent, privacy, retention, or compliance workflows.

## Backend Requirement

You need a running LALIGENCE eKYC backend. For example:

```dart
final ekyc = EkycClient(
  baseUrl: 'https://ekyc-system-backend-singapore.onrender.com',
);
```

The backend must expose these endpoints:

- `POST /api/verifications`
- `GET /api/verifications/{session_id}`
- `POST /api/verifications/{session_id}/document`
- `POST /api/verifications/{session_id}/challenge`
- `POST /api/verifications/{session_id}/selfie`
- `POST /api/verifications/{session_id}/enroll-face`
- `POST /api/face-login`

Testing-only profile admin helpers are also available when enabled by your backend:

- `GET /api/profiles`
- `DELETE /api/profiles/{user_id}`
- `DELETE /api/profiles`

## Installation

Add the package to your `pubspec.yaml`:

```yaml
dependencies:
  laligence_ekyc: ^0.3.1
```

Then run:

```bash
flutter pub get
```

Import it:

```dart
import 'package:laligence_ekyc/laligence_ekyc.dart';
```

## Create The Client

```dart
final ekyc = EkycClient(
  baseUrl: 'https://ekyc-system-backend-singapore.onrender.com',
);
```

You can adjust retries and timeouts:

```dart
final ekyc = EkycClient(
  baseUrl: 'https://ekyc-system-backend-singapore.onrender.com',
  defaultRetries: 2,
  defaultTimeout: const Duration(seconds: 90),
);
```

When you are done with the client, close the underlying HTTP client:

```dart
ekyc.close();
```

## New User Verification Flow

Use this flow when a new user signs up and needs passport verification plus Face ID enrollment.

### 1. Create A Verification Session

Use your real app user ID. This ID should come from your auth/user system.

```dart
final session = await ekyc.createVerification('user-001');

print(session.sessionId);
print(session.decision); // Decision.pending
```

### 2. Upload Passport Image

Capture a clear passport image in your Flutter app, then upload the saved file path:

```dart
final documentResult = await ekyc.uploadDocument(
  session.sessionId,
  EkycUpload.fromPath(
    passportImagePath,
    filename: 'passport.jpg',
    contentType: 'image/jpeg',
  ),
);

if (documentResult.document.status == UploadStatus.rejected) {
  print(documentResult.reasonCodes);
  print(documentResult.document.signals.map((signal) => signal.code).toList());
}
```

The backend analyzes:

- passport/document likeness
- image quality
- MRZ/OCR fields
- expiry date
- fraud risk
- recapture risk
- tamper risk
- passport portrait face extraction

### 3. Complete Active Liveness Challenges

Your Flutter app should run the camera UI and detect the requested action. After the user performs the correct action, call `completeChallenge`.

```dart
for (final challenge in documentResult.activeChallenges) {
  // Your app should verify the real action first.
  await ekyc.completeChallenge(
    documentResult.sessionId,
    challenge.id,
    passed: true,
  );
}
```

Example challenge IDs may include:

- `blink`
- `turn_left`
- `turn_right`
- `open_mouth`

### 4. Complete Hand Gesture Challenges

Your Flutter app should show the gesture challenge and verify the user performs it inside the required area. Then send the result:

```dart
for (final challenge in documentResult.handChallenges) {
  // Your app should verify the gesture first.
  await ekyc.completeChallenge(
    documentResult.sessionId,
    challenge.id,
    passed: true,
  );
}
```

### 5. Upload Selfie

Capture a fresh live selfie and upload it:

```dart
final selfieResult = await ekyc.analyzeSelfie(
  documentResult.sessionId,
  EkycUpload.fromPath(
    selfieImagePath,
    filename: 'selfie.jpg',
    contentType: 'image/jpeg',
  ),
);

print(selfieResult.biometric.faceMatchScore);
print(selfieResult.biometric.passiveLivenessRisk);
print(selfieResult.decision);
```

The backend checks:

- selfie quality
- face detection
- passport portrait to selfie face match
- passive liveness / anti-spoofing
- phone or screen replay signals
- multiple faces
- final verification decision

### 6. Enroll Face ID

Only enroll after the full verification passes.

```dart
if (selfieResult.decision == Decision.passed) {
  final enrollment = await ekyc.enrollFace(selfieResult.sessionId);

  print(enrollment.enrolled);
  print(enrollment.profile.faceId);
  print(enrollment.profile.fullName);
  print(enrollment.profile.passportNumber);
}
```

Backend enrollment rules:

- One `user_id` maps to one active `face_id`.
- One `passport_number` maps to one verified profile.
- Re-enrolling the same user updates the active Face ID.
- Enrolling the same passport under a different user is rejected.

## Returning User Face Login

Use face login when the user already has a verified Face ID profile.

```dart
final login = await ekyc.faceLogin(
  EkycUpload.fromPath(
    liveSelfiePath,
    filename: 'face-login.jpg',
    contentType: 'image/jpeg',
  ),
);

if (login.matched && login.profile != null) {
  print('Welcome ${login.profile!.fullName}');
  print(login.profile!.nationality);
} else {
  print(login.reasonCodes);
}
```

The backend checks passive liveness before matching the selfie against enrolled templates.

## Upload From Bytes

Use `EkycUpload.fromBytes` when your camera package gives you image bytes instead of a file path.

```dart
final result = await ekyc.uploadDocument(
  session.sessionId,
  EkycUpload.fromBytes(
    imageBytes,
    filename: 'passport.jpg',
    contentType: 'image/jpeg',
  ),
);
```

The same upload type works for selfie and face login:

```dart
final login = await ekyc.faceLogin(
  EkycUpload.fromBytes(
    selfieBytes,
    filename: 'face-login.jpg',
    contentType: 'image/jpeg',
  ),
);
```

## Fetch Session Status

You can fetch the latest server state at any time:

```dart
final latest = await ekyc.getVerification(session.sessionId);

print(latest.decision);
print(latest.reasonCodes);
```

## Testing Profile Helpers

These methods are useful for local demos and QA. Protect or remove the backend routes before production.

```dart
final profiles = await ekyc.listProfiles();

for (final profile in profiles.profiles) {
  print('${profile.userId}: ${profile.fullName}');
}

await ekyc.deleteProfile('user-001');
await ekyc.deleteProfiles();
```

## Error Handling

Backend validation errors throw `EkycApiException`.

```dart
try {
  final result = await ekyc.faceLogin(
    EkycUpload.fromPath(liveSelfiePath),
  );
  print(result.decision);
} on EkycApiException catch (error) {
  print(error.statusCode);
  print(error.detail);
} on Exception catch (error) {
  print(error);
}
```

Common status codes:

- `400`: missing or empty upload
- `409`: verification not ready for enrollment, duplicate passport conflict, or rejected session state
- `413`: uploaded image is too large
- `415`: unsupported image type

## Important Response Fields

`VerificationResult` includes:

- `sessionId`
- `userId`
- `decision`
- `reasonCodes`
- `document`
- `biometric`
- `activeChallenges`
- `handChallenges`

Document result fields:

- `document.status`
- `document.imageQualityScore`
- `document.fraudRiskScore`
- `document.ocr.fullName`
- `document.ocr.passportNumber`
- `document.ocr.nationality`
- `document.ocr.dateOfBirth`
- `document.ocr.expiryDate`
- `document.ocr.mrzValid`
- `document.signals`

Biometric result fields:

- `biometric.activeLivenessPassed`
- `biometric.handChallengePassed`
- `biometric.passiveLivenessPassed`
- `biometric.faceMatchScore`
- `biometric.passiveLivenessRisk`
- `biometric.selfieQualityScore`
- `biometric.selfieSignals`

Face login result fields:

- `matched`
- `decision`
- `matchScore`
- `passiveLivenessRisk`
- `reasonCodes`
- `profile`

## Camera And Permission Notes

This SDK does not request permissions. Your Flutter app should request camera permission before capture.

Popular Flutter packages for capture include:

- `camera`
- `image_picker`
- `permission_handler`

Recommended mobile capture behavior:

- Use HTTPS backend URLs.
- Compress images before upload, but keep enough detail for OCR and face matching.
- Ask the user to capture passport images in good lighting.
- Avoid storing raw passport or selfie images after upload unless your retention policy explicitly allows it.
- Show backend reason codes in a user-friendly way.

## Security Notes

For production, your app and backend should add:

- explicit user consent before biometric enrollment
- encrypted transport with HTTPS
- authenticated API access
- encrypted biometric template storage on the backend
- audit logs
- retention limits
- user deletion workflows
- abuse and rate-limit controls

The demo backend is designed for testing and internal validation. Do not treat it as a complete production compliance system without a formal security review.

## Troubleshooting

### The request times out

If the backend is hosted on a service that sleeps or cold-starts, the first request can be slow. Increase timeout or retry:

```dart
final ekyc = EkycClient(
  baseUrl: 'https://your-backend.example.com',
  defaultRetries: 2,
  defaultTimeout: const Duration(seconds: 120),
);
```

### Upload is rejected as unsupported image type

Set the correct content type:

```dart
EkycUpload.fromPath(
  imagePath,
  filename: 'passport.jpg',
  contentType: 'image/jpeg',
);
```

Supported backend types are usually:

- `image/jpeg`
- `image/png`
- `image/webp`

### Face login returns no match

Check:

- the user has already completed verification
- `enrollFace` was called successfully
- the selfie is live, centered, and well lit
- backend passive liveness did not reject the selfie
- `reasonCodes` for the exact rejection reason

## Local Development

Run package checks:

```bash
dart pub get
dart analyze
dart test
dart pub publish --dry-run
```

Use this package from a local Flutter app:

```yaml
dependencies:
  laligence_ekyc:
    path: ../ekyc-system-codex/sdk/flutter
```
