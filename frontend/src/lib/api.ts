import { getAuthToken } from "./auth";
import { L } from "./i18n";

export type Decision = "pending" | "passed" | "rejected";
export type ChallengeType = "active_liveness" | "hand_gesture";
export type DocumentType = "passport" | "lao_id_card";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: string;
}

export interface AuthUserInfo {
  username: string;
  role: string;
}

export interface UserProfileListResponse {
  profiles: UserProfile[];
}

export interface DeleteProfileResponse {
  deleted: boolean;
  deleted_count: number;
}

export interface AuditEvent {
  seq: number;
  event_time: string;
  event_type: string;
  actor: string | null;
  action: string;
  subject: string | null;
  detail: Record<string, unknown> | null;
  entry_hash: string;
}

export interface AuditListResponse {
  events: AuditEvent[];
}

export interface AuditVerifyResponse {
  ok: boolean;
  entries: number;
  broken_at: number | null;
}

export interface Attempt {
  session_id: string;
  user_id: string;
  decision: Decision;
  reason_codes: string[];
  document_type: string | null;
  document_status: string | null;
  document_fraud_risk: number | null;
  active_liveness_passed: boolean;
  hand_challenge_passed: boolean;
  passive_liveness_passed: boolean;
  face_match_score: number | null;
  passive_liveness_risk: number | null;
  contact_confirmed: boolean;
  client_ip: string | null;
  step_count: number;
  created_at: string;
  updated_at: string;
}

export interface AttemptListResponse {
  attempts: Attempt[];
  total: number;
}

export interface AttemptSummary {
  total: number;
  passed: number;
  pending: number;
  rejected: number;
}

export interface WatchlistHit {
  id: string;
  session_id: string;
  user_id: string | null;
  subject_id: string;
  subject_name: string;
  matched_on: string;
  matched_value: string | null;
  confidence: number;
  severity: string;
  reason: string | null;
  status: "pending" | "confirmed" | "dismissed";
  created_at: string | null;
  adjudicated_by: string | null;
  adjudicated_at: string | null;
  note: string | null;
  has_probe?: boolean;
}

export interface WatchlistSummary {
  enabled: boolean;
  subject_count: number;
  active_subject_count: number;
  pending_hits: number;
  total_hits: number;
}

export interface WatchlistSubject {
  id: string;
  full_name: string;
  date_of_birth: string | null;
  nationality: string | null;
  passport_numbers: string[];
  reason: string | null;
  source: string | null;
  active: boolean;
  added_at: string | null;
  has_face: boolean;
}

export interface EvidenceFrame {
  id: string;
  step: string;
  label: string | null;
  sequence: number;
  byte_size: number;
  encrypted: boolean;
  sha256: string;
  captured_at: string | null;
  expires_at: string | null;
  available: boolean;
}

export interface EvidenceEvent {
  step: string;
  action: string;
  outcome: string | null;
  reason_codes: string[];
  duration_ms: number | null;
  occurred_at: string | null;
}

export interface EvidenceAccess {
  actor: string;
  action: string;
  client_ip: string | null;
  occurred_at: string | null;
}

export interface SessionEvidence {
  session_id: string;
  frames: EvidenceFrame[];
  events: EvidenceEvent[];
  access_log: EvidenceAccess[];
}

export interface AdminOverview {
  attempts: AttemptSummary;
  enrolled_face_ids: number;
  audit_chain_ok: boolean;
  audit_entries: number;
  audit_log_enabled: boolean;
  profile_retention_days: number;
  attempt_retention_days: number;
}

export interface ConsentInfo {
  version: string;
  notice: string;
}

export type ContactChannel = "email" | "sms";

export interface ContactChallengeResponse {
  sent: boolean;
  channel: ContactChannel;
  destination_masked: string;
  expires_in: number;
  debug_code: string | null;
}

export interface SelfServiceExportResponse {
  verified: boolean;
  match_score: number;
  reason_codes: string[];
  profile: UserProfile | null;
}

export interface SelfServiceDeleteResponse {
  verified: boolean;
  deleted: boolean;
  user_id: string | null;
  reason_codes: string[];
}

export interface Challenge {
  id: string;
  type: ChallengeType;
  prompt: string;
  instruction: string;
  image_url?: string | null;
  passed: boolean;
  nonce?: string | null;
}

export interface FraudSignal {
  code: string;
  label: string;
  severity: "low" | "medium" | "high";
  score: number;
}

export interface VerificationResult {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  decision: Decision;
  engine?: {
    pipeline_version: string;
    decision_policy_version: string;
    build_sha: string;
  };
  reason_codes: string[];
  document: {
    status: "pending" | "passed" | "rejected";
    image_quality_score: number;
    fraud_risk_score: number;
    document_likeness_score: number;
    recapture_risk_score: number;
    tamper_risk_score: number;
    ocr: {
      document_type: DocumentType;
      full_name: string | null;
      document_number: string | null;
      id_number: string | null;
      passport_number: string | null;
      nationality: string | null;
      date_of_birth: string | null;
      expiry_date: string | null;
      confidence: number;
      mrz_text: string | null;
      mrz_valid: boolean | null;
      mrz_check_digits_valid: boolean | null;
      extracted_fields: Record<string, string>;
    };
    signals: FraudSignal[];
    checks: Record<string, string | number | boolean | null>;
  };
  biometric: {
    active_liveness_passed: boolean;
    hand_challenge_passed: boolean;
    active_liveness_checks: Record<string, string | number | boolean | null>;
    active_liveness_signals: FraudSignal[];
    passive_liveness_passed: boolean;
    face_match_score: number;
    passive_liveness_risk: number;
    selfie_quality_score: number;
    selfie_checks: Record<string, string | number | boolean | null>;
    selfie_signals: FraudSignal[];
  };
  active_challenges: Challenge[];
  hand_challenges: Challenge[];
  watchlist_blocked?: boolean;
  session_token?: string | null;
}

export interface UserProfile {
  face_id: string;
  user_id: string;
  active: boolean;
  verification_session_id: string;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  age: number | null;
  date_of_birth: string | null;
  nationality: string | null;
  passport_number: string | null;
  passport_expiry: string | null;
  enrolled_at: string;
  last_login_at: string | null;
  consent_version: string | null;
  consented_at: string | null;
}

export interface FaceEnrollmentResponse {
  enrolled: boolean;
  profile: UserProfile;
}

export interface FaceLoginResponse {
  decision: Decision;
  matched: boolean;
  match_score: number;
  passive_liveness_risk: number;
  reason_codes: string[];
  profile: UserProfile | null;
  checks: Record<string, string | number | boolean | null>;
  signals: FraudSignal[];
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const NETWORK_RETRY_DELAYS_MS = [900, 2200];

// Per-session client-binding token, issued when a verification is created and
// echoed back on every session-scoped request as X-Session-Token.
let sessionToken: string | null = null;
export const setSessionToken = (token: string | null) => {
  sessionToken = token;
};

type RequestOptions = RequestInit & {
  retries?: number;
  timeoutMs?: number;
};

const request = async <T>(path: string, init: RequestOptions = {}): Promise<T> => {
  const { retries = 1, timeoutMs = 45000, headers, ...requestInit } = init;
  let lastError: unknown;

  // Attach the operator JWT and the per-session binding token (when present).
  const token = getAuthToken();
  const authHeaders: Record<string, string> = { ...((headers ?? {}) as Record<string, string>) };
  if (token) authHeaders.Authorization = `Bearer ${token}`;
  if (sessionToken) authHeaders["X-Session-Token"] = sessionToken;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        ...requestInit,
        headers: authHeaders,
        signal: controller.signal
      });
      window.clearTimeout(timeout);
      if (!response.ok) {
        throw new Error(await readableApiError(response));
      }
      return response.json() as Promise<T>;
    } catch (error) {
      window.clearTimeout(timeout);
      lastError = error;
      if (!isRetryableNetworkError(error) || attempt >= retries) break;
      await delay(NETWORK_RETRY_DELAYS_MS[Math.min(attempt, NETWORK_RETRY_DELAYS_MS.length - 1)]);
    }
  }

  throw normalizeNetworkError(lastError);
};

const readableApiError = async (response: Response) => {
  const message = await response.text();
  return message || L(`ຄຳຮ້ອງຂໍບໍ່ສຳເລັດ (ລະຫັດ ${response.status}).`, `Request failed with status ${response.status}.`);
};

const isRetryableNetworkError = (error: unknown) => {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "AbortError");
};

const normalizeNetworkError = (error: unknown) => {
  if (error instanceof DOMException && error.name === "AbortError") {
    return new Error(L("ເຊີບເວີຕອບສະໜອງຊ້າເກີນໄປ. ກະລຸນາລອງໃໝ່.", "The server took too long to respond. Render may be waking up, please try again."));
  }
  if (error instanceof TypeError) {
    return new Error(L("ບໍ່ສາມາດເຊື່ອມຕໍ່ເຊີບເວີໄດ້. ກວດການເຊື່ອມຕໍ່ ແລ້ວລອງໃໝ່.", "Could not reach the verification server. Check your connection and try again."));
  }
  return error instanceof Error ? error : new Error(L("ເກີດຂໍ້ຜິດພາດ.", "Something went wrong."));
};

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export const api = {
  createSession: async (userId: string) => {
    const result = await request<VerificationResult>("/api/verifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
      retries: 2
    });
    setSessionToken(result.session_token ?? null);
    return result;
  },

  uploadDocument: (sessionId: string, file: File | Blob, documentType: DocumentType = "passport") => {
    const body = new FormData();
    body.append("document_type", documentType);
    body.append("file", file, file instanceof File ? file.name : `${documentType}-capture.jpg`);
    return request<VerificationResult>(`/api/verifications/${sessionId}/document`, {
      method: "POST",
      body,
      retries: 2,
      timeoutMs: 90000
    });
  },

  completeChallenge: (
    sessionId: string,
    challengeId: string,
    nonce?: string | null,
    passed = true,
    frames?: Blob[]
  ) => {
    // Multipart so the gesture can carry face evidence: the server binds the
    // face in these frames to the passport portrait, preventing one person from
    // performing the gesture on another's behalf.
    const body = new FormData();
    body.append("challenge_id", challengeId);
    body.append("passed", String(passed));
    if (nonce) body.append("nonce", nonce);
    (frames ?? []).forEach((frame, index) => {
      body.append("frames", frame, `${challengeId}-gesture-${index + 1}.jpg`);
    });
    return request<VerificationResult>(`/api/verifications/${sessionId}/challenge`, {
      method: "POST",
      body,
      retries: 2
    });
  },

  verifyActiveLiveness: (sessionId: string, challengeId: string, file: File | Blob | Blob[]) => {
    const body = new FormData();
    body.append("challenge_id", challengeId);
    if (Array.isArray(file)) {
      file.forEach((frame, index) => {
        body.append("frames", frame, frame instanceof File ? frame.name : `${challengeId}-active-liveness-${index + 1}.jpg`);
      });
    } else {
      body.append("file", file, file instanceof File ? file.name : `${challengeId}-active-liveness.jpg`);
    }
    return request<VerificationResult>(`/api/verifications/${sessionId}/active-liveness`, {
      method: "POST",
      body,
      retries: 1,
      timeoutMs: 90000
    });
  },

  analyzeSelfie: (sessionId: string, file: File | Blob | Blob[]) => {
    const body = new FormData();
    if (Array.isArray(file)) {
      file.forEach((frame, index) => {
        body.append("frames", frame, frame instanceof File ? frame.name : `selfie-burst-${index + 1}.jpg`);
      });
    } else {
      body.append("file", file, file instanceof File ? file.name : "selfie-capture.jpg");
    }
    return request<VerificationResult>(`/api/verifications/${sessionId}/selfie`, {
      method: "POST",
      body,
      retries: 2,
      timeoutMs: 90000
    });
  },

  enrollFace: (sessionId: string) =>
    request<FaceEnrollmentResponse>(`/api/verifications/${sessionId}/enroll-face`, {
      method: "POST",
      retries: 2,
      timeoutMs: 60000
    }),

  faceLogin: (capture: File | Blob | Blob[]) => {
    const body = new FormData();
    if (Array.isArray(capture)) {
      capture.forEach((frame, index) => {
        body.append("frames", frame, frame instanceof File ? frame.name : `face-login-${index + 1}.jpg`);
      });
    } else {
      body.append("file", capture, capture instanceof File ? capture.name : "face-login.jpg");
    }
    return request<FaceLoginResponse>("/api/face-login", {
      method: "POST",
      body,
      retries: 2,
      timeoutMs: 90000
    });
  },

  // --- Operator auth + admin console (JWT) -----------------------------------

  login: (username: string, password: string) => {
    // OAuth2 password grant expects application/x-www-form-urlencoded.
    const body = new URLSearchParams({ username, password });
    return request<TokenResponse>("/api/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      retries: 1
    });
  },

  me: () => request<AuthUserInfo>("/api/auth/me", { retries: 1 }),

  listProfiles: () =>
    request<UserProfileListResponse>("/api/profiles", { retries: 1 }),

  deleteProfile: (userId: string) =>
    request<DeleteProfileResponse>(`/api/profiles/${encodeURIComponent(userId)}`, {
      method: "DELETE",
      retries: 1
    }),

  purgeExpiredProfiles: () =>
    request<DeleteProfileResponse>("/api/profiles/purge-expired", {
      method: "POST",
      retries: 1
    }),

  listAudit: (limit = 100) =>
    request<AuditListResponse>(`/api/audit?limit=${limit}`, { retries: 1 }),

  verifyAudit: () =>
    request<AuditVerifyResponse>("/api/audit/verify", { retries: 1 }),

  sessionEvidence: (sessionId: string) =>
    request<SessionEvidence>(`/api/evidence/${sessionId}`, { retries: 1 }),

  // Frames are served as bytes (decrypted server-side) and every view is
  // access-logged, so they are fetched with auth rather than referenced by URL.
  evidenceFrameUrl: async (frameId: string): Promise<string> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE_URL}/api/evidence/frame/${frameId}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!response.ok) throw new Error(L("ບໍ່ສາມາດໂຫຼດຮູບຫຼັກຖານໄດ້.", "Evidence frame could not be loaded."));
    return URL.createObjectURL(await response.blob());
  },

  purgeExpiredEvidence: () =>
    request<{ files_removed: number; rows_removed: number }>("/api/evidence/purge-expired", {
      method: "POST",
      retries: 0
    }),

  adminOverview: () => request<AdminOverview>("/api/admin/overview", { retries: 1 }),

  listAttempts: (opts: { limit?: number; offset?: number; decision?: string; userId?: string } = {}) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 50));
    params.set("offset", String(opts.offset ?? 0));
    if (opts.decision) params.set("decision", opts.decision);
    if (opts.userId) params.set("user_id", opts.userId);
    return request<AttemptListResponse>(`/api/attempts?${params.toString()}`, { retries: 1 });
  },

  purgeExpiredAttempts: () =>
    request<DeleteProfileResponse>("/api/attempts/purge-expired", {
      method: "POST",
      retries: 1
    }),

  watchlistSummary: () => request<WatchlistSummary>("/api/watchlist/summary", { retries: 1 }),

  watchlistHits: (status?: string) =>
    request<{ hits: WatchlistHit[] }>(
      `/api/watchlist/hits${status ? `?status=${encodeURIComponent(status)}` : ""}`,
      { retries: 1 }
    ),

  watchlistSubjects: () =>
    request<{ subjects: WatchlistSubject[] }>("/api/watchlist/subjects?limit=500", { retries: 1 }),

  removeWatchlistSubject: (subjectId: string) =>
    request<{ deleted: boolean; subject_id: string }>(`/api/watchlist/subjects/${subjectId}`, {
      method: "DELETE",
      retries: 1
    }),

  adjudicateWatchlistHit: (hitId: string, status: "confirmed" | "dismissed", note?: string) =>
    request<{ ok: boolean; hit_id: string; status: string }>(
      `/api/watchlist/hits/${hitId}/adjudicate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note }),
        retries: 1
      }
    ),

  addWatchlistFace: async (fullName: string, file: File, reason?: string) => {
    const token = getAuthToken();
    const body = new FormData();
    body.append("full_name", fullName);
    if (reason) body.append("reason", reason);
    body.append("file", file);
    const response = await fetch(`${API_BASE_URL}/api/watchlist/subjects/face`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body
    });
    if (!response.ok) throw new Error(await readableApiError(response));
    return response.json();
  },

  // Auth-fetched image blobs for the officer side-by-side.
  watchlistSubjectPhotoUrl: async (subjectId: string): Promise<string> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE_URL}/api/watchlist/subjects/${subjectId}/photo`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!response.ok) throw new Error("photo unavailable");
    return URL.createObjectURL(await response.blob());
  },

  watchlistHitProbeUrl: async (hitId: string): Promise<string> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE_URL}/api/watchlist/hits/${hitId}/probe`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!response.ok) throw new Error("probe unavailable");
    return URL.createObjectURL(await response.blob());
  },

  // --- Consent + self-service data rights (GDPR) -----------------------------

  getConsent: () => request<ConsentInfo>("/api/consent", { retries: 1 }),

  requestContactCode: (sessionId: string, channel: ContactChannel, destination: string) =>
    request<ContactChallengeResponse>(`/api/verifications/${sessionId}/contact/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel, destination }),
      retries: 1
    }),

  confirmContactCode: (sessionId: string, code: string) =>
    request<VerificationResult>(`/api/verifications/${sessionId}/contact/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
      retries: 1
    }),

  exportMyData: (file: File | Blob) => {
    const body = new FormData();
    body.append("file", file, file instanceof File ? file.name : "self-service.jpg");
    return request<SelfServiceExportResponse>("/api/self-service/export", {
      method: "POST",
      body,
      retries: 1,
      timeoutMs: 90000
    });
  },

  deleteMyData: (file: File | Blob) => {
    const body = new FormData();
    body.append("file", file, file instanceof File ? file.name : "self-service.jpg");
    return request<SelfServiceDeleteResponse>("/api/self-service/delete", {
      method: "POST",
      body,
      retries: 1,
      timeoutMs: 90000
    });
  }
};
