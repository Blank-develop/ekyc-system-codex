# LALIGENCE Flutter SDK

The Flutter SDK is a typed Dart client for the same FastAPI backend used by the web app. It keeps mobile apps thin: Flutter handles camera capture and challenge UI, then sends passport and selfie images to the backend for OCR, fraud checks, face matching, passive liveness, enrollment, and returning face login.

## Add The Local Package

From a Flutter app in a sibling folder:

```yaml
dependencies:
  laligence_ekyc: ^0.3.0
```

Then run:

```bash
flutter pub get
```

For company-wide use, publish `sdk/flutter` to a private pub registry or include it as a Git/path dependency.

## Signup And Verification

```dart
import 'package:laligence_ekyc/laligence_ekyc.dart';

final ekyc = EkycClient(
  baseUrl: 'https://ekyc-system-backend-singapore.onrender.com',
);

final session = await ekyc.createVerification('user-001');

final document = await ekyc.uploadDocument(
  session.sessionId,
  EkycUpload.fromPath(
    passportImagePath,
    filename: 'passport.jpg',
    contentType: 'image/jpeg',
  ),
);

for (final challenge in document.activeChallenges) {
  await ekyc.completeChallenge(document.sessionId, challenge.id);
}

for (final challenge in document.handChallenges) {
  await ekyc.completeChallenge(document.sessionId, challenge.id);
}

final selfie = await ekyc.analyzeSelfie(
  document.sessionId,
  EkycUpload.fromPath(
    selfieImagePath,
    filename: 'selfie.jpg',
    contentType: 'image/jpeg',
  ),
);

if (selfie.decision == Decision.passed) {
  final enrollment = await ekyc.enrollFace(selfie.sessionId);
  print(enrollment.profile.faceId);
}
```

## Returning Face Login

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
}
```

## Upload From Bytes

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

## Mobile Responsibilities

- Request camera permission in Flutter before capture.
- Capture passport, active liveness frames, gesture evidence, and selfie in the app.
- Call `completeChallenge` only after your Flutter challenge detector accepts the action.
- Keep backend URLs on `https`.
- Do not store raw passport or selfie images unless your production retention policy explicitly allows it.
- Protect profile admin methods before a real production launch.
