# LALIGENCE eKYC Flutter SDK

Flutter client for the LALIGENCE eKYC backend.

```yaml
dependencies:
  laligence_ekyc_sdk:
    path: ../ekyc-system-codex/sdk/flutter
```

```dart
import 'package:laligence_ekyc_sdk/laligence_ekyc_sdk.dart';

final ekyc = EkycClient(
  baseUrl: 'https://ekyc-system-backend-singapore.onrender.com',
);

final session = await ekyc.createVerification('user-001');

final document = await ekyc.uploadDocument(
  session.sessionId,
  EkycUpload.fromPath('/path/to/passport.jpg'),
);

final selfie = await ekyc.analyzeSelfie(
  document.sessionId,
  EkycUpload.fromPath('/path/to/selfie.jpg'),
);

if (selfie.decision == Decision.passed) {
  final enrollment = await ekyc.enrollFace(selfie.sessionId);
  print(enrollment.profile.faceId);
}
```
