export type Decision = "pending" | "passed" | "rejected";
export type ChallengeType = "active_liveness" | "hand_gesture";
export type UploadStatus = "pending" | "passed" | "rejected";

export interface Challenge {
  id: string;
  type: ChallengeType;
  prompt: string;
  instruction: string;
  passed: boolean;
}

export interface FraudSignal {
  code: string;
  label: string;
  severity: "low" | "medium" | "high";
  score: number;
}

export interface OcrResult {
  document_type: "passport";
  full_name: string | null;
  passport_number: string | null;
  nationality: string | null;
  date_of_birth: string | null;
  expiry_date: string | null;
  confidence: number;
  mrz_text: string | null;
  mrz_valid: boolean | null;
  mrz_check_digits_valid: boolean | null;
  extracted_fields: Record<string, string>;
}

export interface VerificationResult {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  decision: Decision;
  reason_codes: string[];
  document: {
    status: UploadStatus;
    image_quality_score: number;
    fraud_risk_score: number;
    document_likeness_score: number;
    recapture_risk_score: number;
    tamper_risk_score: number;
    ocr: OcrResult;
    signals: FraudSignal[];
    checks: Record<string, string | number | boolean | null>;
  };
  biometric: {
    active_liveness_passed: boolean;
    hand_challenge_passed: boolean;
    passive_liveness_passed: boolean;
    face_match_score: number;
    passive_liveness_risk: number;
    selfie_quality_score: number;
    selfie_checks: Record<string, string | number | boolean | null>;
    selfie_signals: FraudSignal[];
  };
  active_challenges: Challenge[];
  hand_challenges: Challenge[];
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
}

export interface FaceEnrollmentResponse {
  enrolled: boolean;
  profile: UserProfile;
}

export interface UserProfileListResponse {
  profiles: UserProfile[];
}

export interface DeleteProfileResponse {
  deleted: boolean;
  deleted_count: number;
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

export type ReactNativeImage = {
  uri: string;
  name?: string;
  type?: string;
};

export type UploadImage = Blob | File | ReactNativeImage;

export type EkycClientOptions = {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  defaultTimeoutMs?: number;
  defaultRetries?: number;
};

export type RequestOptions = {
  retries?: number;
  timeoutMs?: number;
};

export class EkycApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(readableErrorDetail(detail) || `eKYC request failed with status ${status}.`);
    this.name = "EkycApiError";
    this.status = status;
    this.detail = detail;
  }
}

const RETRY_DELAYS_MS = [900, 2200];

export class EkycClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly defaultTimeoutMs: number;
  private readonly defaultRetries: number;

  constructor(options: EkycClientOptions) {
    if (!options.baseUrl.trim()) {
      throw new Error("EkycClient requires a backend baseUrl.");
    }
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? 45000;
    this.defaultRetries = options.defaultRetries ?? 1;
  }

  createVerification(userId: string, options?: RequestOptions) {
    return this.request<VerificationResult>("/api/verifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId })
    }, { retries: 2, ...options });
  }

  getVerification(sessionId: string, options?: RequestOptions) {
    return this.request<VerificationResult>(`/api/verifications/${sessionId}`, undefined, options);
  }

  uploadDocument(sessionId: string, image: UploadImage, options?: RequestOptions & { ocrText?: string }) {
    const body = createUploadBody(image, "passport-capture.jpg");
    if (options?.ocrText) {
      body.append("ocr_text", options.ocrText);
    }
    return this.request<VerificationResult>(`/api/verifications/${sessionId}/document`, {
      method: "POST",
      body
    }, { retries: 2, timeoutMs: 90000, ...options });
  }

  completeChallenge(sessionId: string, challengeId: string, passed = true, options?: RequestOptions) {
    return this.request<VerificationResult>(`/api/verifications/${sessionId}/challenge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: challengeId, passed })
    }, { retries: 2, ...options });
  }

  analyzeSelfie(sessionId: string, image: UploadImage, options?: RequestOptions) {
    return this.request<VerificationResult>(`/api/verifications/${sessionId}/selfie`, {
      method: "POST",
      body: createUploadBody(image, "selfie-capture.jpg")
    }, { retries: 2, timeoutMs: 90000, ...options });
  }

  enrollFace(sessionId: string, options?: RequestOptions) {
    return this.request<FaceEnrollmentResponse>(`/api/verifications/${sessionId}/enroll-face`, {
      method: "POST"
    }, { retries: 2, timeoutMs: 60000, ...options });
  }

  faceLogin(image: UploadImage, options?: RequestOptions) {
    return this.request<FaceLoginResponse>("/api/face-login", {
      method: "POST",
      body: createUploadBody(image, "face-login.jpg")
    }, { retries: 2, timeoutMs: 90000, ...options });
  }

  listProfiles(options?: RequestOptions) {
    return this.request<UserProfileListResponse>("/api/profiles", undefined, options);
  }

  deleteProfile(userId: string, options?: RequestOptions) {
    return this.request<DeleteProfileResponse>(`/api/profiles/${encodeURIComponent(userId)}`, {
      method: "DELETE"
    }, options);
  }

  deleteProfiles(options?: RequestOptions) {
    return this.request<DeleteProfileResponse>("/api/profiles", {
      method: "DELETE"
    }, options);
  }

  private async request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
    const retries = options.retries ?? this.defaultRetries;
    const timeoutMs = options.timeoutMs ?? this.defaultTimeoutMs;
    let lastError: unknown;

    for (let attempt = 0; attempt <= retries; attempt += 1) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          ...init,
          signal: controller.signal
        });
        clearTimeout(timeout);
        if (!response.ok) {
          throw new EkycApiError(response.status, await parseErrorBody(response));
        }
        return response.json() as Promise<T>;
      } catch (error) {
        clearTimeout(timeout);
        lastError = error;
        if (!isRetryableNetworkError(error) || attempt >= retries) break;
        await delay(RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]);
      }
    }

    throw normalizeNetworkError(lastError);
  }
}

function createUploadBody(image: UploadImage, fallbackName: string) {
  const body = new FormData();
  if (isReactNativeImage(image)) {
    body.append("file", {
      uri: image.uri,
      name: image.name ?? fallbackName,
      type: image.type ?? guessMimeType(image.name ?? fallbackName)
    } as unknown as Blob);
    return body;
  }
  const name = image instanceof File ? image.name : fallbackName;
  body.append("file", image, name);
  return body;
}

function isReactNativeImage(image: UploadImage): image is ReactNativeImage {
  return typeof image === "object" && image !== null && "uri" in image;
}

function guessMimeType(name: string) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  return "image/jpeg";
}

async function parseErrorBody(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function readableErrorDetail(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) {
    const value = (detail as { detail?: unknown }).detail;
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  return "";
}

function isRetryableNetworkError(error: unknown) {
  return error instanceof TypeError || (error instanceof DOMException && error.name === "AbortError");
}

function normalizeNetworkError(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return new Error("The eKYC backend took too long to respond. The service may be waking up; try again.");
  }
  if (error instanceof TypeError) {
    return new Error("Could not reach the eKYC backend. Check the device network and backend URL.");
  }
  return error instanceof Error ? error : new Error("Something went wrong.");
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
