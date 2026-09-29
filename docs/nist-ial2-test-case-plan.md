# LALIGENCE eKYC NIST IAL2 Test Case Plan

Version: 1.0  
Prepared for: LALIGENCE eKYC readiness testing  
Reference date: 2026-05-20  
Target: NIST SP 800-63A-4 Identity Assurance Level 2 aligned remote identity proofing

## 1. Purpose

This document defines the test cases, evidence records, and acceptance criteria needed to evaluate whether the LALIGENCE eKYC workflow is ready for a NIST IAL2-aligned assessment.

Important: this document does not create a NIST certification by itself. It is a readiness and evidence package for internal QA, security review, customer due diligence, and future third-party assessment.

## 2. NIST References

- NIST SP 800-63-4, Digital Identity Guidelines: https://csrc.nist.gov/pubs/sp/800/63/4/final
- NIST SP 800-63A-4, Identity Proofing and Enrollment: https://csrc.nist.gov/pubs/sp/800/63/A/4/final
- Online NIST SP 800-63A-4 Identity Proofing Requirements: https://pages.nist.gov/800-63-4/sp800-63a/ial/
- NIST SP 800-63B-4, Authentication and Authenticator Management: https://csrc.nist.gov/pubs/sp/800/63/B/4/final
- NIST SP 800-63-3 implementation resources, useful until 800-63-4 conformance material is released: https://pages.nist.gov/800-63-3-Implementation-Resources/63A/

## 3. Product Scope

In scope:

- New user identity proofing using passport or Lao ID card.
- Document capture/upload.
- Document OCR/MRZ or OCR field extraction.
- Document expiry and fraud signal checks.
- Active face liveness.
- Hand gesture challenge.
- Selfie capture.
- Passive liveness / presentation attack detection.
- Face match between document portrait and selfie.
- Verified profile creation.
- Face ID enrollment linked to one user ID.
- Duplicate passport/profile protection.
- Audit record for verification decision.

Out of scope for IAL2 but important for production:

- Face login after enrollment. This belongs mainly to NIST SP 800-63B authentication assurance testing.
- Payment authorization. This needs additional financial/security controls.
- ISO/IEC 27001, ISO/IEC 30107, PCI DSS, or local financial regulator approval.

## 4. Target IAL2 Pathway

The current product should target the IAL2 Biometric Pathway:

1. Collect identity evidence: passport or government ID.
2. Extract core attributes: full name, date of birth, nationality, document number, expiry date, sex if available.
3. Validate evidence: document format, document security indicators, MRZ/checksum where available, expiry, OCR consistency, tamper/fraud signals.
4. Verify applicant ownership: compare live selfie to the document portrait using automated face matching.
5. Apply PAD and liveness controls: active liveness, passive liveness, screen/photo replay detection, multiple-face detection.
6. Store proofing result, decision reason codes, verified profile, and face embedding/template according to privacy policy.

Assessment warning: NIST IAL2 expects authoritative or credible source validation of core attributes where applicable. OCR/MRZ-only validation is not enough for a strong final compliance claim unless the business defines and documents a credible-source strategy.

## 5. Required Evidence Artifacts

For every test run, store:

- Test case ID.
- Tester name.
- Date/time.
- App version/commit hash.
- Backend version/commit hash.
- Device/browser/OS.
- Document type.
- Input class, such as real passport, expired ID, altered photo, paper replay, screen replay.
- Result: passed, rejected, manual review, or failed due to error.
- Decision scores: document quality, document fraud risk, face match score, passive risk, selfie quality.
- Reason codes.
- OCR/MRZ fields extracted.
- Whether active liveness completed.
- Whether gesture completed.
- Whether selfie/face match completed.
- Stored profile ID or user ID, if created.
- Logs or API response payload.
- Screenshot or redacted evidence image when allowed.

Do not store raw real identity documents unless the privacy policy, consent, encryption, retention, and deletion controls explicitly allow it. Prefer redacted samples for demos.

## 6. Acceptance Summary

The app is IAL2-readiness-pass only if all of these are true:

- Accepted genuine documents are not rejected at high rates.
- Expired documents are rejected.
- Non-document images are rejected.
- Tampered documents are rejected or routed to manual review.
- OCR/MRZ extraction is accurate enough for all required attributes.
- MRZ/checksum mismatch is rejected or manual review.
- The applicant cannot skip required workflow steps.
- Paper photo, screen replay, and video replay attacks fail liveness/PAD.
- A different person's selfie fails face match.
- Same person's selfie passes face match under normal lighting.
- Duplicate passport number cannot create multiple verified profiles.
- One user ID has only one active face ID.
- Verification result is stored with audit reason codes.
- Notification of proofing is implemented or documented as a known gap.
- Attribute validation against authoritative or credible source is implemented or documented as a known gap.

## 7. Requirement Mapping

| NIST IAL2 area | Product control | Evidence to collect | Current readiness |
|---|---|---|---|
| Identity service documentation | Written workflow, privacy policy, retention policy, operational SOP | `AGENT.md`, this test plan, privacy/retention docs | Partial |
| Evidence collection | Passport or Lao ID card capture/upload | Test run logs showing document type and evidence class | Partial |
| Attribute collection | OCR/MRZ extracts name, DOB, nationality, document number, expiry | API response and UI result screenshot | Partial |
| Evidence validation | MRZ checksum, expiry, image quality, document-shape, fraud/tamper signals | Reason codes, scores, dataset test report | Partial |
| Attribute validation | Confirm core attributes against authoritative or credible source | API integration logs or manual source-check policy | Gap |
| Evidence ownership verification | Face match document portrait vs live selfie | Face score, threshold, pass/fail result | Partial |
| PAD/liveness | Active liveness, gesture, passive anti-spoof | Attack test report with FAR/FRR | Partial |
| Injection / modified media controls | HTTPS camera capture, replay detection, screenshot/video attack rejection | Security test results, browser/device logs | Partial |
| Notification of proofing | Notify validated email/phone/address after proofing | Notification template and delivery log | Gap |
| Initial authenticator binding | Bind face ID to user ID after proofing | Profile database record, one active face ID rule | Partial |
| Records and auditability | Store verification result and reason codes | DB record, audit log export | Partial |
| Privacy risk management | Consent, data minimization, deletion process | Privacy policy, retention schedule, delete API test | Partial |

## 8. Test Data Requirements

Minimum internal dataset before customer demo:

| Category | Minimum count | Purpose |
|---|---:|---|
| Genuine passport images | 200 | Estimate false reject rate |
| Genuine Lao ID card images | 100 | Estimate Lao ID false reject rate |
| Expired documents | 50 | Expiry rejection |
| Blurry/low-quality genuine documents | 100 | Quality threshold tuning |
| Non-document images | 100 | Reject cats, people, objects, screenshots |
| Edited/tampered documents | 200 | Text overlay, face substitution, date edit, document number edit |
| Screen replay selfie attacks | 100 | Passive liveness attack testing |
| Paper photo selfie attacks | 100 | Passive liveness attack testing |
| Genuine live selfies | 200 | False reject rate for real users |
| Impostor selfie attempts | 200 | False accept rate for wrong person |
| Active liveness screen replay attempts | 100 | Challenge replay attack testing |
| Gesture challenge wrong attempts | 100 | Gesture failure logic |

Recommended pre-assessment dataset:

- 1,000+ genuine document samples across lighting, blur, camera angle, glare, phone models.
- 1,000+ attack samples across print, screen, replay, edited document, face substitution, and non-document images.
- At least 50 testers if possible, because face matching and liveness performance changes across real users and devices.

## 9. Core Test Cases

### A. Document Evidence Capture

| ID | Test case | Input | Expected result | Required evidence |
|---|---|---|---|---|
| DOC-001 | Upload clear valid passport | Genuine non-expired passport | Pass document step | OCR/MRZ fields, expiry, quality score, reason code |
| DOC-002 | Capture clear valid passport by camera | Genuine non-expired passport | Pass document step | Camera image accepted, same fields as upload |
| DOC-003 | Upload clear valid Lao ID card | Genuine non-expired Lao ID | Pass document step | OCR name, DOB, expiry, document number |
| DOC-004 | Upload expired passport | Expiry date before test date | Reject | `DOCUMENT_EXPIRED` or equivalent |
| DOC-005 | Upload expired Lao ID | Expiry date before test date | Reject | `LAO_ID_EXPIRED` or equivalent |
| DOC-006 | Upload future-valid Lao ID | Expiry date after test date | Pass expiry check | Extracted expiry date and parsed date |
| DOC-007 | Upload non-document image | Animal/object/person photo | Reject | `NON_DOCUMENT_UPLOAD` or equivalent |
| DOC-008 | Upload document screenshot | Screenshot/cropped browser image | Reject or manual review | Screenshot/screen risk code |
| DOC-009 | Upload very blurry document | Genuine but unreadable | Reject or manual review | Blur/quality reason code |
| DOC-010 | Upload low-light document | Genuine under poor light | Reject or manual review if unreadable | Quality score and reason code |
| DOC-011 | Upload glare-covered document | Genuine with heavy reflection | Reject or manual review if fields hidden | Quality/glare reason code |
| DOC-012 | Upload rotated document | Genuine rotated 90 degrees | Either auto-correct and pass or reject with clear error | Orientation handling result |
| DOC-013 | Upload partial/cropped document | Missing MRZ or key fields | Reject | Missing field/code |
| DOC-014 | Upload wrong file type | PDF, SVG, text file, executable | Reject safely | File validation log |

### B. Document Fraud / Tamper Detection

| ID | Test case | Input | Expected result | Required evidence |
|---|---|---|---|---|
| FRD-001 | Face substitution | Passport with edited portrait | Reject or manual review | Tamper/face-substitution reason code |
| FRD-002 | Date of expiry edited | Passport expiry changed | Reject or manual review | Text/date inconsistency code |
| FRD-003 | Passport number edited | Visual number changed but MRZ differs | Reject | MRZ/visual mismatch |
| FRD-004 | Name edited | Visual name changed but MRZ differs | Reject | OCR/MRZ consistency code |
| FRD-005 | Text overlay added | Artificial text added | Reject or manual review | Overlay/tamper reason code |
| FRD-006 | Copy-paste region | Cloned texture over field | Reject or manual review | Manipulation score/code |
| FRD-007 | MRZ checksum invalid | Modified MRZ check digit | Reject | MRZ invalid reason |
| FRD-008 | MRZ valid but visual mismatch | MRZ internally valid but visual fields differ | Reject/manual review | Cross-field mismatch |
| FRD-009 | Synthetic passport template | Fake generated document | Reject | Template/fraud risk high |
| FRD-010 | High-quality printed copy | Printed/scanned passport copy | Reject or manual review | Presence/security feature risk |

### C. Attribute Extraction and Validation

| ID | Test case | Input | Expected result | Required evidence |
|---|---|---|---|---|
| ATR-001 | Extract passport full name | Valid passport | Name exactly matches MRZ/display logic | OCR and normalized name |
| ATR-002 | Extract passport number | Valid passport | Number matches visual/MRZ | OCR/MRZ result |
| ATR-003 | Extract DOB | Valid passport | DOB correctly parsed | Parsed ISO date |
| ATR-004 | Extract expiry | Valid passport | Expiry correctly parsed | Parsed ISO date |
| ATR-005 | Extract nationality | Valid passport | Nationality code correct | OCR/MRZ result |
| ATR-006 | Lao ID name extraction | Lao ID card | Name extracted or manual review when OCR weak | OCR confidence |
| ATR-007 | Lao ID expiry extraction | Lao ID card | Expiry date correctly parsed | Parsed ISO date |
| ATR-008 | Field consistency | Document with matching visual/MRZ | No mismatch code | Consistency check result |
| ATR-009 | Attribute authoritative check | Real test profile against credible source | Pass only if matched | Source response/log |
| ATR-010 | Attribute authoritative mismatch | Name/DOB mismatch against source | Reject or manual review | Source mismatch log |

Known gap: if there is no authoritative or credible source integration, mark ATR-009 and ATR-010 as blocked and document a mitigation plan.

### D. Workflow Gating

| ID | Test case | Input/action | Expected result | Required evidence |
|---|---|---|---|---|
| GATE-001 | Try liveness before document | Click Face liveness first | Blocked | UI screenshot |
| GATE-002 | Rejected document then liveness | Upload rejected document, click next | Blocked | Reason code and UI block |
| GATE-003 | Skip active liveness | Pass document, click gesture | Blocked | UI screenshot |
| GATE-004 | Skip gesture | Pass liveness, click selfie | Blocked | UI screenshot |
| GATE-005 | Skip selfie | Pass gesture, click result | Blocked | UI screenshot |
| GATE-006 | Browser refresh after pass | Refresh after document passed | State restored or clear restart behavior | Session behavior log |
| GATE-007 | Multi-tab session conflict | Same user opens two sessions | Safe behavior, no duplicated profile | Session/audit log |

### E. Active Liveness

| ID | Test case | Input/action | Expected result | Required evidence |
|---|---|---|---|---|
| LIV-001 | Correct blink | Real user blinks | Pass challenge | Challenge result |
| LIV-002 | Correct mouth open | Real user opens mouth | Pass challenge | Challenge result |
| LIV-003 | Correct turn left/right | Real user turns head | Pass challenge | Challenge result |
| LIV-004 | Wrong action | User performs wrong movement | Reject or continue waiting | Challenge result |
| LIV-005 | No face | Camera sees background | Reject/no pass | Face absent code |
| LIV-006 | Multiple faces | Two people in frame | Reject | Multiple face code |
| LIV-007 | Phone screen replay | Video of person performing action | Reject | Replay/spoof code |
| LIV-008 | Printed photo movement | Printed photo moved by hand | Reject | PAD reason code |
| LIV-009 | Deepfake/replayed video | Synthetic or replayed face video | Reject or manual review | Spoof/high-risk code |
| LIV-010 | Low light real user | Real user in poor lighting | Reject with useful message or pass if confident | Quality code |

### F. Hand Gesture Challenge

| ID | Test case | Input/action | Expected result | Required evidence |
|---|---|---|---|---|
| GST-001 | Correct gesture sequence | Real user performs 3 required gestures | Pass | Gesture results |
| GST-002 | Wrong gesture | User shows wrong sign | Reject/continue waiting | Gesture result |
| GST-003 | Gesture outside circle | Correct hand outside target | Reject/continue waiting | Position check |
| GST-004 | No hand | Face only | Reject/no pass | Hand absent code |
| GST-005 | Printed hand image | Paper hand gesture | Reject | Spoof/manual review |
| GST-006 | Screen replay gesture | Video on screen | Reject or manual review | Replay risk |
| GST-007 | Random circle movement | Circle changes position | User can still complete | UI/telemetry |
| GST-008 | Mobile gesture challenge | Phone browser | Pass for real user | Device/browser log |

### G. Selfie, Passive Liveness, and Face Match

| ID | Test case | Input | Expected result | Required evidence |
|---|---|---|---|---|
| BIO-001 | Same person live selfie | Document owner live selfie | Pass | Match score above threshold |
| BIO-002 | Different person selfie | Impostor live selfie | Reject | Match score below threshold |
| BIO-003 | Paper photo attack | Printed face photo | Reject | Passive spoof reason |
| BIO-004 | Phone screen attack | Face photo/video on phone | Reject | Screen/replay reason |
| BIO-005 | Laptop screen attack | Face on monitor | Reject | Screen/replay reason |
| BIO-006 | Multiple faces | Real user plus another face/photo | Reject | Multiple face code |
| BIO-007 | No face | Background/object/cat | Reject | Face not found |
| BIO-008 | Mask/sunglasses | Face partly covered | Reject or manual review | Occlusion/quality reason |
| BIO-009 | Poor light live user | Real user poor light | Reject with guidance or pass if confident | Quality score |
| BIO-010 | Borderline match | Same person with angle/aging difference | Manual review or reject based on threshold | Score and policy |
| BIO-011 | Low quality selfie | Blurry selfie | Reject | Selfie quality reason |
| BIO-012 | Face crop only | Uploaded/captured image containing cropped face | Reject if not live camera | Injection/PAD reason |

### H. Profile, User ID, and Duplicate Rules

| ID | Test case | Input/action | Expected result | Required evidence |
|---|---|---|---|---|
| PROF-001 | New verified user | Complete full flow | One verified profile created | DB record |
| PROF-002 | Same passport new user ID | Re-enroll same passport number | Reject duplicate or link to existing verified profile | Duplicate passport result |
| PROF-003 | Same user re-enroll face | Same user enrolls new face ID | Old face ID deactivated or replaced | DB active face rule |
| PROF-004 | One user multiple active faces | Force second active face ID | System prevents it | DB constraint/API error |
| PROF-005 | Face login after enrollment | Use enrolled face | Login accepted | Face login response |
| PROF-006 | Impostor face login | Different user attempts login | Login rejected | Match score/reason |
| PROF-007 | Delete test user | Delete profile/user ID | Profile and face template removed or deactivated | DB/API result |
| PROF-008 | List users for audit | Admin lists profiles | PII-minimized structured result | API response |

### I. Security, Privacy, and Operational Controls

| ID | Test case | Input/action | Expected result | Required evidence |
|---|---|---|---|---|
| SEC-001 | HTTPS required for camera | Open public URL | Camera works only over HTTPS | Browser test |
| SEC-002 | HTTP camera blocked | Open non-local HTTP URL | Camera blocked or warning shown | Browser test |
| SEC-003 | API CORS policy | Call API from unknown origin | Blocked | API response |
| SEC-004 | Upload size limit | Upload very large image | Rejected safely | API response |
| SEC-005 | Malware-like file upload | Upload non-image payload | Rejected safely | API response |
| SEC-006 | Rate limiting | Many failed attempts | Throttled or locked | API/log evidence |
| SEC-007 | Audit log completeness | Complete pass and reject flows | Logs include decision and reason codes | Log export |
| SEC-008 | Data minimization | Complete proofing | Only required result/profile fields stored | DB inspection |
| SEC-009 | Encryption at rest | Inspect production DB/storage config | Encryption enabled | Cloud/DB config |
| SEC-010 | Deletion request | Delete test profile | Data removed/deactivated per policy | DB/API result |
| SEC-011 | Consent shown | Start verification | Consent/privacy notice available | UI screenshot |
| SEC-012 | Proofing notification | Successful proofing | Notification sent to validated address | Notification log |

## 10. Performance Metrics to Report

Report these metrics before claiming production readiness:

- Document genuine pass rate.
- Document false reject rate.
- Fraud document detection rate by attack type.
- Non-document rejection rate.
- OCR exact-match rate for name, DOB, document number, expiry, nationality.
- MRZ valid parse rate.
- Active liveness pass rate for genuine users.
- Active liveness attack rejection rate.
- Passive liveness false accept rate for paper/screen attacks.
- Passive liveness false reject rate for genuine users.
- Face match false accept rate.
- Face match false reject rate.
- Average processing latency per step.
- Mobile vs desktop success rate.
- Manual review rate.

Suggested initial targets for demo readiness:

- Genuine document false reject rate below 10 percent.
- Non-document rejection above 99 percent.
- Expired document rejection 100 percent.
- MRZ checksum invalid rejection 100 percent.
- Impostor face match rejection above 99 percent.
- Paper/screen passive spoof rejection above 95 percent.
- Real live selfie false reject rate below 10 percent.
- Full workflow completion time below 3 minutes for normal users.

These are internal targets, not official NIST thresholds.

## 11. Test Execution Template

Use this template for each run:

```text
Test Case ID:
Tester:
Date/Time:
Environment:
Frontend URL:
Backend URL:
Commit SHA:
Device:
Browser:
Document Type:
Input Dataset/File:
Expected Result:
Actual Result:
Decision:
Scores:
Reason Codes:
OCR/MRZ Output:
Profile/User ID:
Screenshots:
API Response:
Logs:
Pass/Fail:
Notes:
```

## 12. Known Gaps to Close Before External Review

1. Authoritative or credible source validation for document attributes.
2. Formal notification of successful proofing to a validated address.
3. Written privacy notice, consent text, retention schedule, and deletion process.
4. Formal model evaluation report for document fraud, face match, and PAD.
5. Manual review process for borderline scores and document uncertainty.
6. Production audit log export and tamper-resistant log storage.
7. Security testing for upload abuse, API abuse, CORS, rate limiting, and injection/replay.
8. Dataset report that separates genuine users, impostors, document fraud, paper attacks, and screen attacks.

## 13. Final Readiness Decision

Use this sign-off table after all test cases are executed:

| Area | Status | Owner | Evidence link | Notes |
|---|---|---|---|---|
| Document proofing | Not started / In progress / Passed / Failed |  |  |  |
| OCR/MRZ | Not started / In progress / Passed / Failed |  |  |  |
| Attribute validation | Not started / In progress / Passed / Failed |  |  |  |
| Active liveness | Not started / In progress / Passed / Failed |  |  |  |
| Gesture challenge | Not started / In progress / Passed / Failed |  |  |  |
| Passive liveness | Not started / In progress / Passed / Failed |  |  |  |
| Face matching | Not started / In progress / Passed / Failed |  |  |  |
| Profile storage | Not started / In progress / Passed / Failed |  |  |  |
| Privacy controls | Not started / In progress / Passed / Failed |  |  |  |
| Security controls | Not started / In progress / Passed / Failed |  |  |  |
| Audit evidence | Not started / In progress / Passed / Failed |  |  |  |

Final recommendation:

- Pass: all critical tests passed and no open NIST-blocking gaps.
- Conditional pass: core flow works, but some process controls require documented mitigation.
- Fail: any critical test allows identity proofing bypass, accepts obvious fraud, or cannot produce audit evidence.
