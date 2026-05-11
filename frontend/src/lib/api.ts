export type Decision = "pending" | "passed" | "rejected";
export type ChallengeType = "active_liveness" | "hand_gesture";

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

export interface VerificationResult {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  decision: Decision;
  reason_codes: string[];
  document: {
    status: "pending" | "passed" | "rejected";
    image_quality_score: number;
    fraud_risk_score: number;
    document_likeness_score: number;
    recapture_risk_score: number;
    tamper_risk_score: number;
    ocr: {
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
    };
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

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
};

export const api = {
  createSession: (userId: string) =>
    request<VerificationResult>("/api/verifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId })
    }),

  uploadDocument: (sessionId: string, file: File | Blob) => {
    const body = new FormData();
    body.append("file", file, file instanceof File ? file.name : "passport-capture.jpg");
    return request<VerificationResult>(`/api/verifications/${sessionId}/document`, {
      method: "POST",
      body
    });
  },

  completeChallenge: (sessionId: string, challengeId: string, passed = true) =>
    request<VerificationResult>(`/api/verifications/${sessionId}/challenge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: challengeId, passed })
    }),

  analyzeSelfie: (sessionId: string, file: File | Blob) => {
    const body = new FormData();
    body.append("file", file, file instanceof File ? file.name : "selfie-capture.jpg");
    return request<VerificationResult>(`/api/verifications/${sessionId}/selfie`, {
      method: "POST",
      body
    });
  },

  enrollFace: (sessionId: string) =>
    request<FaceEnrollmentResponse>(`/api/verifications/${sessionId}/enroll-face`, {
      method: "POST"
    }),

  faceLogin: (file: File | Blob) => {
    const body = new FormData();
    body.append("file", file, file instanceof File ? file.name : "face-login.jpg");
    return request<FaceLoginResponse>("/api/face-login", {
      method: "POST",
      body
    });
  }
};
