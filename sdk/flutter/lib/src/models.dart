typedef JsonMap = Map<String, dynamic>;

enum Decision {
  pending,
  passed,
  rejected;

  static Decision fromJson(String value) {
    return Decision.values.firstWhere(
      (decision) => decision.name == value,
      orElse: () => Decision.pending,
    );
  }
}

enum ChallengeType {
  activeLiveness,
  handGesture;

  static ChallengeType fromJson(String value) {
    return switch (value) {
      'active_liveness' => ChallengeType.activeLiveness,
      'hand_gesture' => ChallengeType.handGesture,
      _ => ChallengeType.activeLiveness,
    };
  }
}

enum UploadStatus {
  pending,
  passed,
  rejected;

  static UploadStatus fromJson(String value) {
    return UploadStatus.values.firstWhere(
      (status) => status.name == value,
      orElse: () => UploadStatus.pending,
    );
  }
}

class Challenge {
  const Challenge({
    required this.id,
    required this.type,
    required this.prompt,
    required this.instruction,
    required this.passed,
  });

  factory Challenge.fromJson(JsonMap json) {
    return Challenge(
      id: json['id'] as String? ?? '',
      type: ChallengeType.fromJson(json['type'] as String? ?? ''),
      prompt: json['prompt'] as String? ?? '',
      instruction: json['instruction'] as String? ?? '',
      passed: json['passed'] as bool? ?? false,
    );
  }

  final String id;
  final ChallengeType type;
  final String prompt;
  final String instruction;
  final bool passed;
}

class FraudSignal {
  const FraudSignal({
    required this.code,
    required this.label,
    required this.severity,
    required this.score,
  });

  factory FraudSignal.fromJson(JsonMap json) {
    return FraudSignal(
      code: json['code'] as String? ?? '',
      label: json['label'] as String? ?? '',
      severity: json['severity'] as String? ?? 'low',
      score: _asDouble(json['score']),
    );
  }

  final String code;
  final String label;
  final String severity;
  final double score;
}

class OcrResult {
  const OcrResult({
    required this.documentType,
    required this.fullName,
    required this.passportNumber,
    required this.nationality,
    required this.dateOfBirth,
    required this.expiryDate,
    required this.confidence,
    required this.mrzText,
    required this.mrzValid,
    required this.mrzCheckDigitsValid,
    required this.extractedFields,
  });

  factory OcrResult.fromJson(JsonMap json) {
    return OcrResult(
      documentType: json['document_type'] as String? ?? 'passport',
      fullName: json['full_name'] as String?,
      passportNumber: json['passport_number'] as String?,
      nationality: json['nationality'] as String?,
      dateOfBirth: json['date_of_birth'] as String?,
      expiryDate: json['expiry_date'] as String?,
      confidence: _asDouble(json['confidence']),
      mrzText: json['mrz_text'] as String?,
      mrzValid: json['mrz_valid'] as bool?,
      mrzCheckDigitsValid: json['mrz_check_digits_valid'] as bool?,
      extractedFields: _stringMap(json['extracted_fields']),
    );
  }

  final String documentType;
  final String? fullName;
  final String? passportNumber;
  final String? nationality;
  final String? dateOfBirth;
  final String? expiryDate;
  final double confidence;
  final String? mrzText;
  final bool? mrzValid;
  final bool? mrzCheckDigitsValid;
  final Map<String, String> extractedFields;
}

class DocumentAnalysis {
  const DocumentAnalysis({
    required this.status,
    required this.imageQualityScore,
    required this.fraudRiskScore,
    required this.documentLikenessScore,
    required this.recaptureRiskScore,
    required this.tamperRiskScore,
    required this.ocr,
    required this.signals,
    required this.checks,
  });

  factory DocumentAnalysis.fromJson(JsonMap json) {
    return DocumentAnalysis(
      status: UploadStatus.fromJson(json['status'] as String? ?? ''),
      imageQualityScore: _asDouble(json['image_quality_score']),
      fraudRiskScore: _asDouble(json['fraud_risk_score']),
      documentLikenessScore: _asDouble(json['document_likeness_score']),
      recaptureRiskScore: _asDouble(json['recapture_risk_score']),
      tamperRiskScore: _asDouble(json['tamper_risk_score']),
      ocr: OcrResult.fromJson(_map(json['ocr'])),
      signals: _list(json['signals']).map(FraudSignal.fromJson).toList(),
      checks: _dynamicMap(json['checks']),
    );
  }

  final UploadStatus status;
  final double imageQualityScore;
  final double fraudRiskScore;
  final double documentLikenessScore;
  final double recaptureRiskScore;
  final double tamperRiskScore;
  final OcrResult ocr;
  final List<FraudSignal> signals;
  final Map<String, Object?> checks;
}

class BiometricAnalysis {
  const BiometricAnalysis({
    required this.activeLivenessPassed,
    required this.handChallengePassed,
    required this.passiveLivenessPassed,
    required this.faceMatchScore,
    required this.passiveLivenessRisk,
    required this.selfieQualityScore,
    required this.selfieChecks,
    required this.selfieSignals,
  });

  factory BiometricAnalysis.fromJson(JsonMap json) {
    return BiometricAnalysis(
      activeLivenessPassed: json['active_liveness_passed'] as bool? ?? false,
      handChallengePassed: json['hand_challenge_passed'] as bool? ?? false,
      passiveLivenessPassed: json['passive_liveness_passed'] as bool? ?? false,
      faceMatchScore: _asDouble(json['face_match_score']),
      passiveLivenessRisk: _asDouble(json['passive_liveness_risk']),
      selfieQualityScore: _asDouble(json['selfie_quality_score']),
      selfieChecks: _dynamicMap(json['selfie_checks']),
      selfieSignals: _list(
        json['selfie_signals'],
      ).map(FraudSignal.fromJson).toList(),
    );
  }

  final bool activeLivenessPassed;
  final bool handChallengePassed;
  final bool passiveLivenessPassed;
  final double faceMatchScore;
  final double passiveLivenessRisk;
  final double selfieQualityScore;
  final Map<String, Object?> selfieChecks;
  final List<FraudSignal> selfieSignals;
}

class VerificationResult {
  const VerificationResult({
    required this.sessionId,
    required this.userId,
    required this.createdAt,
    required this.updatedAt,
    required this.decision,
    required this.reasonCodes,
    required this.document,
    required this.biometric,
    required this.activeChallenges,
    required this.handChallenges,
  });

  factory VerificationResult.fromJson(JsonMap json) {
    return VerificationResult(
      sessionId: json['session_id'] as String? ?? '',
      userId: json['user_id'] as String? ?? '',
      createdAt: json['created_at'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
      decision: Decision.fromJson(json['decision'] as String? ?? ''),
      reasonCodes: _stringList(json['reason_codes']),
      document: DocumentAnalysis.fromJson(_map(json['document'])),
      biometric: BiometricAnalysis.fromJson(_map(json['biometric'])),
      activeChallenges: _list(
        json['active_challenges'],
      ).map(Challenge.fromJson).toList(),
      handChallenges: _list(
        json['hand_challenges'],
      ).map(Challenge.fromJson).toList(),
    );
  }

  final String sessionId;
  final String userId;
  final String createdAt;
  final String updatedAt;
  final Decision decision;
  final List<String> reasonCodes;
  final DocumentAnalysis document;
  final BiometricAnalysis biometric;
  final List<Challenge> activeChallenges;
  final List<Challenge> handChallenges;
}

class UserProfile {
  const UserProfile({
    required this.faceId,
    required this.userId,
    required this.active,
    required this.verificationSessionId,
    required this.fullName,
    required this.firstName,
    required this.lastName,
    required this.age,
    required this.dateOfBirth,
    required this.nationality,
    required this.passportNumber,
    required this.passportExpiry,
    required this.enrolledAt,
    required this.lastLoginAt,
  });

  factory UserProfile.fromJson(JsonMap json) {
    return UserProfile(
      faceId: json['face_id'] as String? ?? '',
      userId: json['user_id'] as String? ?? '',
      active: json['active'] as bool? ?? false,
      verificationSessionId: json['verification_session_id'] as String? ?? '',
      fullName: json['full_name'] as String?,
      firstName: json['first_name'] as String?,
      lastName: json['last_name'] as String?,
      age: json['age'] as int?,
      dateOfBirth: json['date_of_birth'] as String?,
      nationality: json['nationality'] as String?,
      passportNumber: json['passport_number'] as String?,
      passportExpiry: json['passport_expiry'] as String?,
      enrolledAt: json['enrolled_at'] as String? ?? '',
      lastLoginAt: json['last_login_at'] as String?,
    );
  }

  final String faceId;
  final String userId;
  final bool active;
  final String verificationSessionId;
  final String? fullName;
  final String? firstName;
  final String? lastName;
  final int? age;
  final String? dateOfBirth;
  final String? nationality;
  final String? passportNumber;
  final String? passportExpiry;
  final String enrolledAt;
  final String? lastLoginAt;
}

class FaceEnrollmentResponse {
  const FaceEnrollmentResponse({required this.enrolled, required this.profile});

  factory FaceEnrollmentResponse.fromJson(JsonMap json) {
    return FaceEnrollmentResponse(
      enrolled: json['enrolled'] as bool? ?? false,
      profile: UserProfile.fromJson(_map(json['profile'])),
    );
  }

  final bool enrolled;
  final UserProfile profile;
}

class UserProfileListResponse {
  const UserProfileListResponse({required this.profiles});

  factory UserProfileListResponse.fromJson(JsonMap json) {
    return UserProfileListResponse(
      profiles: _list(json['profiles']).map(UserProfile.fromJson).toList(),
    );
  }

  final List<UserProfile> profiles;
}

class DeleteProfileResponse {
  const DeleteProfileResponse({
    required this.deleted,
    required this.deletedCount,
  });

  factory DeleteProfileResponse.fromJson(JsonMap json) {
    return DeleteProfileResponse(
      deleted: json['deleted'] as bool? ?? false,
      deletedCount: json['deleted_count'] as int? ?? 0,
    );
  }

  final bool deleted;
  final int deletedCount;
}

class FaceLoginResponse {
  const FaceLoginResponse({
    required this.decision,
    required this.matched,
    required this.matchScore,
    required this.passiveLivenessRisk,
    required this.reasonCodes,
    required this.profile,
    required this.checks,
    required this.signals,
  });

  factory FaceLoginResponse.fromJson(JsonMap json) {
    return FaceLoginResponse(
      decision: Decision.fromJson(json['decision'] as String? ?? ''),
      matched: json['matched'] as bool? ?? false,
      matchScore: _asDouble(json['match_score']),
      passiveLivenessRisk: _asDouble(json['passive_liveness_risk']),
      reasonCodes: _stringList(json['reason_codes']),
      profile: json['profile'] == null
          ? null
          : UserProfile.fromJson(_map(json['profile'])),
      checks: _dynamicMap(json['checks']),
      signals: _list(json['signals']).map(FraudSignal.fromJson).toList(),
    );
  }

  final Decision decision;
  final bool matched;
  final double matchScore;
  final double passiveLivenessRisk;
  final List<String> reasonCodes;
  final UserProfile? profile;
  final Map<String, Object?> checks;
  final List<FraudSignal> signals;
}

double _asDouble(Object? value) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '') ?? 0.0;
}

JsonMap _map(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  return <String, dynamic>{};
}

List<JsonMap> _list(Object? value) {
  if (value is List) {
    return value.map(_map).toList();
  }
  return <JsonMap>[];
}

List<String> _stringList(Object? value) {
  if (value is List) {
    return value.map((item) => item.toString()).toList();
  }
  return <String>[];
}

Map<String, String> _stringMap(Object? value) {
  return _dynamicMap(
    value,
  ).map((key, value) => MapEntry(key, value.toString()));
}

Map<String, Object?> _dynamicMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, Object?>.from(value);
  return <String, Object?>{};
}
