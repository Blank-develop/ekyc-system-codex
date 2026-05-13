import 'package:laligence_ekyc_sdk/laligence_ekyc_sdk.dart';
import 'package:test/test.dart';

void main() {
  test('parses verification result contract', () {
    final result = VerificationResult.fromJson({
      'session_id': 'session-001',
      'user_id': 'user-001',
      'created_at': '2026-05-13T00:00:00Z',
      'updated_at': '2026-05-13T00:01:00Z',
      'decision': 'passed',
      'reason_codes': ['SELFIE_PASSED'],
      'document': {
        'status': 'passed',
        'image_quality_score': 0.91,
        'fraud_risk_score': 0.12,
        'document_likeness_score': 0.95,
        'recapture_risk_score': 0.1,
        'tamper_risk_score': 0.05,
        'ocr': {
          'document_type': 'passport',
          'full_name': 'SAMPLE USER',
          'passport_number': 'PA123456',
          'nationality': 'LAO',
          'date_of_birth': '2001-11-09',
          'expiry_date': '2032-03-14',
          'confidence': 0.88,
          'mrz_text': 'P<LAOSAMPLE<<USER',
          'mrz_valid': true,
          'mrz_check_digits_valid': true,
          'extracted_fields': {'surname': 'SAMPLE'},
        },
        'signals': [],
        'checks': {'document_total_ms': 1200},
      },
      'biometric': {
        'active_liveness_passed': true,
        'hand_challenge_passed': true,
        'passive_liveness_passed': true,
        'face_match_score': 0.82,
        'passive_liveness_risk': 0.08,
        'selfie_quality_score': 0.94,
        'selfie_checks': {},
        'selfie_signals': [],
      },
      'active_challenges': [
        {
          'id': 'blink',
          'type': 'active_liveness',
          'prompt': 'Blink',
          'instruction': 'Blink once',
          'passed': true,
        },
      ],
      'hand_challenges': [],
    });

    expect(result.decision, Decision.passed);
    expect(result.document.ocr.passportNumber, 'PA123456');
    expect(result.activeChallenges.single.type, ChallengeType.activeLiveness);
  });
}
