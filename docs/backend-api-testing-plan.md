# Kyron Backend API Testing Plan

## 1. Purpose

Validate the Kyron eKYC backend independently of any web, Flutter, or wallet frontend. The plan covers functional correctness, workflow enforcement, authentication, authorization, privacy, abuse resistance, error handling, and performance for every non-wallet API operation.

Demo-wallet endpoints are excluded.

## 2. Test Environments

Run the suite in two configurations:

1. **Local integration**: SQLite, local models, API authentication disabled where a test explicitly needs the public-demo behavior.
2. **Production-like**: PostgreSQL, API key enabled, JWT/admin controls enabled, encrypted/protected templates, contact confirmation enabled, production CORS and rate limits.

Record for every run:

- Git commit and build SHA.
- Pipeline and decision-policy versions.
- Model names, versions, and hashes.
- Threshold environment variables.
- Database type and migration version.
- Operating system, CPU/GPU, Python version, and test timestamp.

## 3. Shared Test Data

- Valid passport and Lao ID images with approved ground truth.
- Expired, blurred, rotated, screen-displayed, printed, edited, face-substituted, and non-document images.
- Genuine live-face bursts from enrolled users.
- Unknown genuine users and impostor pairs.
- Printed-photo, phone/tablet replay, video replay, mask, multiple-face, and no-face samples.
- Valid and invalid API keys, JWTs, admin tokens, session IDs, session tokens, challenge nonces, and contact codes.
- Files at, below, and above the configured upload-size limit.

Never use production customer PII or biometric samples in automated tests.

## 4. Common API Tests

Apply these tests to every applicable endpoint:

| ID | Scenario | Expected result |
| --- | --- | --- |
| COM-01 | Valid request with required authentication | Documented `2xx` response and schema-valid JSON |
| COM-02 | Missing API key when API keys are enabled | `401` or `403`; no sensitive response data |
| COM-03 | Invalid/retired credential | Rejected consistently and audit event recorded where applicable |
| COM-04 | Unsupported HTTP method | `405` |
| COM-05 | Malformed JSON or multipart request | `400` or `422`; stable machine-readable error |
| COM-06 | Unexpected extra fields | Follow documented validation policy; never change decision state unexpectedly |
| COM-07 | Excessive request rate | `429` with no partial state mutation |
| COM-08 | Concurrent duplicate request | No duplicate enrollment, challenge completion, or destructive action |
| COM-09 | Internal dependency/model failure | Controlled error; no stack trace, PII, template, or filesystem path leakage |
| COM-10 | Response headers | `Content-Type`, timing header, CORS, and cache behavior match policy |

## 5. Verification Workflow APIs

### `POST /api/verifications`

| ID | Scenario | Expected result |
| --- | --- | --- |
| VER-01 | Create with a valid new `user_id` | `200`; UUID session, binding token, three active and three hand challenges, `pending` decision, engine metadata |
| VER-02 | Empty, whitespace-only, overlength, or invalid-type user ID | `422`; no session created |
| VER-03 | Repeated creation for the same user | Separate short-lived sessions; no duplicate Face ID/profile enrollment |
| VER-04 | High-rate session creation | Rate-limited; memory remains bounded after pruning |
| VER-05 | Response secrecy | Session token returned only at creation and not logged in plaintext |

### `GET /api/verifications/{session_id}`

| ID | Scenario | Expected result |
| --- | --- | --- |
| VER-GET-01 | Correct session ID and binding token | Current result returned |
| VER-GET-02 | Missing, wrong, or another session's token | Rejected without revealing whether another user's session exists |
| VER-GET-03 | Unknown or malformed UUID | `404`/`422` according to contract |
| VER-GET-04 | Idle-expired and absolute-expired session | Rejected and removed from active storage |
| VER-GET-05 | Poll during concurrent update | Schema-valid, internally consistent state |

### `POST /api/verifications/{session_id}/document`

| ID | Scenario | Expected result |
| --- | --- | --- |
| DOC-01 | Clear genuine passport | Document passes; OCR fields and fraud/quality scores returned |
| DOC-02 | Clear genuine Lao ID | Correct document type and extracted fields; valid non-expired card can proceed |
| DOC-03 | Rotated genuine document | Orientation recovery succeeds where image quality is sufficient |
| DOC-04 | Weak MRZ but strong visible passport evidence | Recoverable/soft evidence policy applied; no invented fields |
| DOC-05 | Expired document | Rejected with expiry reason |
| DOC-06 | Printed/photocopied/screen-displayed document | Rejected when attack evidence reaches the policy threshold |
| DOC-07 | Text edit, crop/replace, or portrait substitution | Fraud signals returned and policy decision enforced |
| DOC-08 | Animal, person photo, object, blank image | Rejected as non-document |
| DOC-09 | Unsupported type, malformed image, decompression bomb | Rejected safely without excessive resource use |
| DOC-10 | File above configured maximum | `413`; body not fully processed by OCR/models |
| DOC-11 | Missing/wrong session token | Rejected with no session mutation |
| DOC-12 | Upload after a rejected upload | New analysis replaces prior document state consistently; later steps remain locked until pass |
| DOC-13 | Ground-truth OCR evaluation | Field exact-match, MRZ read/validity, country, number, DOB, expiry, and name metrics recorded |
| DOC-14 | Latency | p50/p95/p99 and per-stage timing recorded; no silent timeout |

### `POST /api/verifications/{session_id}/active-liveness`

| ID | Scenario | Expected result |
| --- | --- | --- |
| LIVE-01 | Correct challenge with genuine live burst | Challenge passes and state advances |
| LIVE-02 | Attempt before document pass | `409`; no liveness state mutation |
| LIVE-03 | Unknown challenge ID | `400` |
| LIVE-04 | Missing frame(s) | `400`/`422` |
| LIVE-05 | No face or multiple faces | Rejected with specific reason code |
| LIVE-06 | Face too small, too far, blurred, or poorly lit | Retry-quality reason; must not be mislabeled as confirmed fraud without supporting evidence |
| LIVE-07 | Printed face | Rejected |
| LIVE-08 | Phone/tablet/laptop image replay | Rejected across brightness, crop, angle, and visible/hidden bezel variations |
| LIVE-09 | Video replay performing the requested action | Rejected |
| LIVE-10 | Genuine recovery after prior replay failure | Recovery policy works only with clean new evidence; old attack evidence cannot incorrectly pass |
| LIVE-11 | Repeated/replayed HTTP payload | One attempt cannot satisfy multiple challenges or sessions |
| LIVE-12 | Latency and load | p50/p95/p99 by device/frame count; bounded concurrency and memory |

### `POST /api/verifications/{session_id}/challenge`

| ID | Scenario | Expected result |
| --- | --- | --- |
| GES-01 | Correct hand challenge, valid one-time nonce, after liveness | Challenge recorded once |
| GES-02 | Attempt before active liveness passes | `409` |
| GES-03 | Active-liveness challenge sent to hand endpoint | `409` |
| GES-04 | Missing, wrong, cross-session, or consumed nonce | `401`; no state mutation |
| GES-05 | Unknown challenge | `400` |
| GES-06 | `passed=false` | `400` and challenge remains incomplete |
| GES-07 | All three valid completions | `hand_challenge_passed=true`; selfie becomes eligible |

### `POST /api/verifications/{session_id}/selfie`

| ID | Scenario | Expected result |
| --- | --- | --- |
| SELF-01 | Genuine live selfie matching document | PAD and face match pass; decision progresses |
| SELF-02 | Genuine nonmatching person | Rejected for face mismatch |
| SELF-03 | Printed photo | PAD rejects |
| SELF-04 | Phone/tablet/laptop screen photo | PAD rejects |
| SELF-05 | Video replay burst | PAD rejects |
| SELF-06 | No face or multiple faces | Rejected with specific reason |
| SELF-07 | Face too small, occluded, blurred, mask, poor lighting | Quality/retry reason; no false identity match |
| SELF-08 | Attempt before document/liveness/gesture prerequisites | `409` |
| SELF-09 | Cross-session selfie or wrong binding token | Rejected |
| SELF-10 | Threshold boundary pairs | Deterministic result at below/equal/above configured match and PAD thresholds |
| SELF-11 | Latency | p50/p95/p99 for face extraction, PAD, matching, and total request |

### `POST /api/verifications/{session_id}/enroll-face`

| ID | Scenario | Expected result |
| --- | --- | --- |
| ENR-01 | Fully passed verification with selfie template | One active Face ID and verified profile created |
| ENR-02 | Pending or rejected verification | `409`; no profile/template stored |
| ENR-03 | Missing selfie template | Rejected safely |
| ENR-04 | Same user enrolls again | Existing active Face ID replaced/deactivated according to one-user/one-active-face policy |
| ENR-05 | Same passport number used by another user | Duplicate verified profile prevented according to policy |
| ENR-06 | Concurrent duplicate enroll calls | Idempotent outcome; no duplicate active records |
| ENR-07 | Storage protection enabled | Stored template is encrypted/protected; raw selfie and document are not retained |
| ENR-08 | Database failure | Transaction rolls back completely |

## 6. Contact Confirmation APIs

### `POST /api/verifications/{session_id}/contact/request`

| ID | Scenario | Expected result |
| --- | --- | --- |
| CON-01 | Valid email/phone channel and destination | Code sent; masked destination and expiry returned |
| CON-02 | Empty/invalid destination or channel | `400`/`422` |
| CON-03 | Repeated requests | Rate/resend policy enforced; prior challenge behavior documented |
| CON-04 | Notifier failure | Controlled response and audit record; no false confirmation |
| CON-05 | Production mode | Code never returned in response or logs |

### `POST /api/verifications/{session_id}/contact/confirm`

| ID | Scenario | Expected result |
| --- | --- | --- |
| CON-C-01 | Correct unexpired code | `contact_confirmed=true`; decision reevaluated |
| CON-C-02 | Wrong, expired, reused, or another session's code | Rejected |
| CON-C-03 | Maximum failed attempts | Challenge locked/invalidated according to policy |
| CON-C-04 | Contact confirmation disabled | Behavior matches documented deployment mode |

## 7. Face Login API

### `POST /api/face-login`

| ID | Scenario | Expected result |
| --- | --- | --- |
| LOGIN-01 | Enrolled genuine live burst | Correct profile matched above threshold |
| LOGIN-02 | Unknown genuine user | No match; no candidate identity leakage |
| LOGIN-03 | Printed photo, screen photo, video replay | Liveness rejection |
| LOGIN-04 | Another enrolled person's face | Never returns the target user's profile |
| LOGIN-05 | No face or multiple faces | Rejected |
| LOGIN-06 | Borderline match score | Deterministic threshold behavior; score exposure follows policy |
| LOGIN-07 | Repeated attacks from one client | Per-client throttle enforced |
| LOGIN-08 | Distributed/high-volume attacks | Global throttle and resource protection enforced |
| LOGIN-09 | Response privacy default | Only redacted profile fields returned unless trusted PII mode is explicitly enabled |
| LOGIN-10 | Template corruption/model unavailable | Controlled failure; no fallback that bypasses liveness or matching |
| LOGIN-11 | Scale | Accuracy and p50/p95/p99 measured as enrolled profile count increases |

## 8. Authentication APIs

### `POST /api/auth/token`

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUTH-01 | Correct configured username/password | Signed access token with expected role and expiry |
| AUTH-02 | Wrong username/password | Generic rejection; no account enumeration |
| AUTH-03 | Malformed form/body | `400`/`422` |
| AUTH-04 | Repeated failures | Rate limiting and audit trail |
| AUTH-05 | JWT disabled | Endpoint fails closed according to deployment contract |

### `GET /api/auth/me`

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUTH-ME-01 | Valid user/admin bearer token | Correct subject and role |
| AUTH-ME-02 | Missing, malformed, expired, wrong-signature token | Rejected |
| AUTH-ME-03 | Token signed by configured retired secret | Accepted only during rotation window |
| AUTH-ME-04 | Privilege claim tampering | Signature validation fails |

## 9. Profile and Privacy APIs

### `GET /api/profiles`

| ID | Scenario | Expected result |
| --- | --- | --- |
| PRO-01 | Valid admin credential | Profiles returned in documented schema |
| PRO-02 | Missing/non-admin credential | Rejected |
| PRO-03 | Empty database | Empty list, not an error |
| PRO-04 | Data minimization | No raw images, plaintext templates, secret keys, or unrelated PII |

### `DELETE /api/profiles/{user_id}`

| ID | Scenario | Expected result |
| --- | --- | --- |
| PRO-D-01 | Existing user with admin authorization | Profile and active template deleted/deactivated consistently |
| PRO-D-02 | Unknown user | Idempotent documented result or `404` |
| PRO-D-03 | Missing/non-admin credential | Rejected with no mutation |
| PRO-D-04 | User ID encoding/injection payload | Safely handled; no other profile affected |

### `DELETE /api/profiles`

| ID | Scenario | Expected result |
| --- | --- | --- |
| PRO-ALL-01 | Authorized bulk deletion | All profiles removed and count returned/audited |
| PRO-ALL-02 | Unauthorized request | Rejected with zero deletion |
| PRO-ALL-03 | Concurrent enrollment | Transactional behavior defined and tested |

### `POST /api/profiles/purge-expired`

| ID | Scenario | Expected result |
| --- | --- | --- |
| PURGE-01 | Profiles older than retention period | Only expired profiles removed |
| PURGE-02 | Retention disabled or no expired records | Zero removed |
| PURGE-03 | Boundary timestamp | Deterministic treatment at exact cutoff |
| PURGE-04 | Unauthorized request | Rejected and audited |

### `GET /api/consent`

| ID | Scenario | Expected result |
| --- | --- | --- |
| CONS-01 | Request current consent information | Current terms/version and retention information returned |
| CONS-02 | Version consistency | Matches version stored during enrollment and deployment configuration |

### `POST /api/self-service/export`

| ID | Scenario | Expected result |
| --- | --- | --- |
| SS-EXP-01 | Valid verified identity/authorization proof | Only that subject's export returned |
| SS-EXP-02 | Wrong or insufficient proof | Rejected without confirming profile existence |
| SS-EXP-03 | Export contents | Machine-readable, minimized, no raw biometric template/secrets |
| SS-EXP-04 | Repeated export abuse | Rate limited and audited |

### `POST /api/self-service/delete`

| ID | Scenario | Expected result |
| --- | --- | --- |
| SS-DEL-01 | Valid subject authorization | Subject profile/template deleted and audit evidence retained per policy |
| SS-DEL-02 | Wrong proof or another person's identifier | Rejected with no deletion |
| SS-DEL-03 | Repeat deletion | Safe idempotent outcome |
| SS-DEL-04 | Post-deletion face login | Deleted identity cannot authenticate |

## 10. Audit, Attempts, and Administration APIs

### `GET /api/audit`

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUD-01 | Authorized admin query | Ordered, paginated/minimized events returned |
| AUD-02 | Unauthorized query | Rejected |
| AUD-03 | Sensitive-data inspection | No session tokens, contact codes, raw PII, images, or templates |
| AUD-04 | Filtering/pagination bounds | Stable ordering and bounded response size |

### `GET /api/audit/verify`

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUD-V-01 | Untampered hash chain | Valid result |
| AUD-V-02 | Modified, removed, inserted, or reordered event in test copy | Verification fails and identifies failure position without exposing secrets |
| AUD-V-03 | Empty/new audit log | Defined valid result |

### `GET /api/attempts`

| ID | Scenario | Expected result |
| --- | --- | --- |
| ATT-01 | Authorized query | Verification attempts and summary returned accurately |
| ATT-02 | Unauthorized query | Rejected |
| ATT-03 | Filtering/limit boundary | Bounded deterministic response |
| ATT-04 | Data minimization | No raw document, selfie, template, session token, or contact code |

### `POST /api/attempts/purge-expired`

| ID | Scenario | Expected result |
| --- | --- | --- |
| ATT-P-01 | Expired attempts exist | Only records beyond retention removed; count returned |
| ATT-P-02 | Retention disabled/no expired attempts | Zero removed |
| ATT-P-03 | Unauthorized request | Rejected with no mutation |

### `GET /api/admin/overview`

| ID | Scenario | Expected result |
| --- | --- | --- |
| ADM-01 | Authorized admin | Counts and operational summary match underlying stores |
| ADM-02 | Unauthorized/non-admin | Rejected |
| ADM-03 | Empty and high-volume datasets | Correct values, bounded latency, no PII leakage |

## 11. End-to-End Backend Scenarios

| ID | Scenario | Expected result |
| --- | --- | --- |
| E2E-01 | Happy path: create → document → active liveness → gesture → selfie → enroll → face login | Passed decision, one active profile, successful genuine login |
| E2E-02 | Rejected document then attempt later steps | Every later step remains locked |
| E2E-03 | Replay at active liveness | Rejected/retry policy applied; no gesture/selfie/enrollment bypass |
| E2E-04 | Nonmatching selfie | No enrollment |
| E2E-05 | Duplicate user/passport enrollment | Uniqueness policies preserved under concurrency |
| E2E-06 | Session expires mid-flow | Further updates rejected; new verification required |
| E2E-07 | Database/model/network failure at each stage | No partial identity enrollment; controlled recovery |
| E2E-08 | Delete enrolled profile | Subsequent face login fails and export reflects deletion policy |

## 12. Performance and Reliability Targets

Set contractual targets before customer acceptance. At minimum measure:

- Request success rate under expected and peak load.
- p50, p95, and p99 latency per endpoint and model stage.
- Cold-start versus warm-model latency.
- Maximum safe concurrent document, liveness, selfie, and login analyses.
- CPU, memory, database connections, file descriptors, and queue depth.
- Behavior during process restart and database reconnect.
- Timeout/retry behavior without duplicated state changes.

Do not approve a release using average latency alone.

## 13. Release Exit Criteria

- All critical/high-priority API tests pass.
- No open identity-bypass, cross-session, cross-user, privilege-escalation, or biometric-template exposure defect.
- Backend unit/integration suite and API contract tests pass from a clean commit.
- Genuine and attack holdout datasets produce approved per-class metrics and confidence intervals.
- Performance targets pass in the production-like environment.
- OpenAPI specification and Flutter/TypeScript SDK contracts match the deployed API.
- Audit-chain verification passes and destructive/privacy operations are evidenced.
- Known failures have documented severity, owner, workaround, and release disposition.

## 14. Evidence to Retain

- Test execution JSON/JUnit report.
- OpenAPI snapshot.
- Environment and version manifest.
- Dataset manifest and immutable holdout hashes.
- Confusion matrices and per-class biometric/document metrics.
- Latency and load-test reports.
- Audit verification result.
- Defect list and approval record.

Retain only results and non-sensitive evidence. Do not attach raw identity documents or biometric captures to general issue trackers.
