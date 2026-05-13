import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Camera,
  Check,
  ChevronRight,
  FileImage,
  Fingerprint,
  Hand,
  KeyRound,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  UserPlus,
  Upload
} from "lucide-react";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import logoUrl from "./assets/logo.png";
import { ActiveLivenessCapture } from "./components/ActiveLivenessCapture";
import { CameraCapture } from "./components/CameraCapture";
import { HandGestureCapture } from "./components/HandGestureCapture";
import { api, Challenge, FaceLoginResponse, UserProfile, VerificationResult } from "./lib/api";
import { optimizeImageForUpload } from "./lib/image";

type StepKey = "document" | "liveness" | "gesture" | "selfie" | "result";
type Screen = "intro" | "verify" | "face-login";
type DocumentNotice = {
  type: "success" | "failure";
  title: string;
  message: string;
  codes: string[];
} | null;
type SelfieNotice = DocumentNotice;
type EnrollmentNotice = (NonNullable<DocumentNotice> & { profile?: UserProfile }) | null;
const FACE_MATCH_PASS_THRESHOLD = 0.68;

const steps: Array<{ key: StepKey; label: string; icon: typeof FileImage }> = [
  { key: "document", label: "Passport", icon: FileImage },
  { key: "liveness", label: "Face liveness", icon: Fingerprint },
  { key: "gesture", label: "Gesture", icon: Hand },
  { key: "selfie", label: "Selfie", icon: Camera },
  { key: "result", label: "Result", icon: BadgeCheck }
];

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;

const createDemoUserId = () => {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const suffix = Math.random().toString(36).slice(2, 8);
  return `user-${date}-${suffix}`;
};

const selfieFailureMessage = (codes: string[], matchScore: number) => {
  if (codes.includes("FACE_MATCH_LOW")) {
    return `Face match is below the acceptance threshold (${Math.round(matchScore * 100)}%). Try a front-facing selfie with the same person as the passport.`;
  }
  if (codes.includes("PASSPORT_FACE_REFERENCE_MISSING")) {
    return "Passport portrait could not be used as a face reference. Re-upload a clearer passport image.";
  }
  if (codes.some((code) => code.includes("SPOOF") || code.includes("SCREEN"))) {
    return "Possible screen or photo replay detected. Capture a live selfie directly from the camera.";
  }
  if (codes.includes("SELFIE_LOW_RESOLUTION") || codes.includes("SELFIE_BLUR_DETECTED")) {
    return "Selfie is too blurry or low resolution. Move closer and capture again.";
  }
  if (codes.includes("FACE_NOT_CENTERED") || codes.includes("FACE_CENTER_WEAK")) {
    return "Please center your face in the oval and try again.";
  }
  return "Please capture a clearer live selfie and try again.";
};

const canAccessStep = (step: StepKey, result: VerificationResult | null) => {
  if (step === "document") return true;
  if (!result || result.document.status !== "passed") return false;
  if (step === "liveness") return true;
  if (!result.biometric.active_liveness_passed) return false;
  if (step === "gesture") return true;
  if (!result.biometric.hand_challenge_passed) return false;
  if (step === "selfie") return true;
  if (!result.biometric.passive_liveness_passed) return false;
  return step === "result";
};

const isStepComplete = (step: StepKey, result: VerificationResult | null) => {
  if (!result) return false;
  if (step === "document") return result.document.status === "passed";
  if (step === "liveness") return result.biometric.active_liveness_passed;
  if (step === "gesture") return result.biometric.hand_challenge_passed;
  if (step === "selfie") return result.biometric.passive_liveness_passed;
  return result.decision !== "pending";
};

const firstBlockedReason = (step: StepKey) => {
  if (step === "liveness") return "Upload an accepted passport first.";
  if (step === "gesture") return "Complete active face liveness first.";
  if (step === "selfie") return "Complete the hand gesture challenge first.";
  if (step === "result") return "Complete selfie and passive liveness first.";
  return "";
};

export function App() {
  const [screen, setScreen] = useState<Screen>("intro");
  const [userId, setUserId] = useState("");
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [activeStep, setActiveStep] = useState<StepKey>("document");
  const [busy, setBusy] = useState(false);
  const [documentBusy, setDocumentBusy] = useState(false);
  const [documentNotice, setDocumentNotice] = useState<DocumentNotice>(null);
  const [selfieBusy, setSelfieBusy] = useState(false);
  const [selfieNotice, setSelfieNotice] = useState<SelfieNotice>(null);
  const [enrollBusy, setEnrollBusy] = useState(false);
  const [enrollmentNotice, setEnrollmentNotice] = useState<EnrollmentNotice>(null);
  const [faceLoginBusy, setFaceLoginBusy] = useState(false);
  const [faceLoginResult, setFaceLoginResult] = useState<FaceLoginResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("Starting verification session");

  const sessionId = result?.session_id;
  const normalizedUserId = userId.trim();
  const sessionReady = Boolean(sessionId);

  const progress = useMemo(() => {
    if (!result) return 0;
    const completed = [
      result.document.status === "passed",
      result.biometric.active_liveness_passed,
      result.biometric.hand_challenge_passed,
      result.biometric.passive_liveness_passed,
      result.decision !== "pending"
    ].filter(Boolean).length;
    return completed / 5;
  }, [result]);

  const sync = async (task: () => Promise<VerificationResult>, message: string, next?: StepKey) => {
    try {
      setBusy(true);
      setError(null);
      const nextResult = await task();
      setResult(nextResult);
      setStatusMessage(message);
      if (next && canAccessStep(next, nextResult)) {
        setActiveStep(next);
      } else if (next && nextResult.document.status === "rejected") {
        setActiveStep("document");
        setStatusMessage("Passport rejected. Please upload a clearer or valid passport image.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const uploadAndAnalyzeDocument = async (task: () => Promise<VerificationResult>, successMessage: string) => {
    try {
      setDocumentBusy(true);
      setDocumentNotice(null);
      setBusy(true);
      setError(null);
      const nextResult = await task();
      setResult(nextResult);
      if (nextResult.document.status === "passed") {
        setStatusMessage(successMessage);
        setDocumentNotice({
          type: "success",
          title: "Passport accepted",
          message: "Document quality, OCR/MRZ, and fraud checks passed.",
          codes: ["DOCUMENT_PASSED"]
        });
        setActiveStep("document");
        window.setTimeout(() => {
          setActiveStep("liveness");
        }, 900);
      } else {
        const codes = nextResult.document.signals.map((signal) => signal.code);
        setActiveStep("document");
        setStatusMessage("Passport rejected. Please upload a clearer or valid passport image.");
        setDocumentNotice({
          type: "failure",
          title: "Passport rejected",
          message: "Please upload a clearer, valid passport image and try again.",
          codes: codes.length ? codes : ["DOCUMENT_REJECTED"]
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setDocumentNotice({
        type: "failure",
        title: "Upload failed",
        message: "The document could not be analyzed. Please try again.",
        codes: ["DOCUMENT_UPLOAD_FAILED"]
      });
    } finally {
      setBusy(false);
      setDocumentBusy(false);
    }
  };

  useEffect(() => {
    if (screen === "verify" && !result && normalizedUserId) {
      sync(() => api.createSession(normalizedUserId), "Session ready");
    }
  }, [screen, result, normalizedUserId]);

  const uploadDocument = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!sessionId) {
      setError("Verification session is still connecting. Please wait a moment and upload again.");
      event.target.value = "";
      return;
    }
    uploadAndAnalyzeDocument(
      async () => api.uploadDocument(
        sessionId,
        await optimizeImageForUpload(file, {
          maxWidth: 1600,
          quality: 0.88,
          filename: file.name.replace(/\.[^.]+$/, "") + "-optimized.jpg"
        })
      ),
      "Passport analyzed"
    ).finally(() => {
      event.target.value = "";
    });
  };

  const captureDocument = (blob: Blob) => {
    if (!sessionId) {
      setError("Verification session is still connecting. Please wait a moment and capture again.");
      return;
    }
    uploadAndAnalyzeDocument(
      async () => api.uploadDocument(
        sessionId,
        await optimizeImageForUpload(blob, {
          maxWidth: 1600,
          quality: 0.88,
          filename: "passport-capture-optimized.jpg"
        })
      ),
      "Passport capture analyzed"
    );
  };

  const completeChallenge = (challenge: Challenge, next?: StepKey) => {
    if (!sessionId) return;
    sync(() => api.completeChallenge(sessionId, challenge.id), `${challenge.prompt} confirmed`, next);
  };

  const analyzeSelfie = async (blob: Blob) => {
    if (!sessionId) return;
    try {
      setSelfieBusy(true);
      setSelfieNotice(null);
      setBusy(true);
      setError(null);
      const optimizedBlob = await optimizeImageForUpload(blob, {
        maxWidth: 900,
        quality: 0.84,
        filename: "selfie-capture-optimized.jpg"
      });
      const nextResult = await api.analyzeSelfie(sessionId, optimizedBlob);
      setResult(nextResult);
      if (nextResult.biometric.passive_liveness_passed && nextResult.biometric.face_match_score >= FACE_MATCH_PASS_THRESHOLD) {
        setStatusMessage("Selfie and passive liveness analyzed");
        setSelfieNotice({
          type: "success",
          title: "Selfie accepted",
          message: "Selfie quality and passive liveness checks passed.",
          codes: ["SELFIE_PASSED"]
        });
        window.setTimeout(() => setActiveStep("result"), 700);
      } else {
        const codes = nextResult.biometric.selfie_signals.map((signal) => signal.code);
        const message = selfieFailureMessage(codes, nextResult.biometric.face_match_score);
        setStatusMessage(`Selfie rejected. ${message}`);
        setSelfieNotice({
          type: "failure",
          title: "Selfie rejected",
          message,
          codes: codes.length ? codes : ["SELFIE_REJECTED"]
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setSelfieNotice({
        type: "failure",
        title: "Selfie upload failed",
        message: "The selfie could not be analyzed. Please try again.",
        codes: ["SELFIE_UPLOAD_FAILED"]
      });
    } finally {
      setBusy(false);
      setSelfieBusy(false);
    }
  };

  const enrollFace = async () => {
    if (!sessionId) return;
    try {
      setEnrollBusy(true);
      setEnrollmentNotice(null);
      const response = await api.enrollFace(sessionId);
      setEnrollmentNotice({
        type: "success",
        title: "Face ID enrolled",
        message: "This verified profile can now use returning face login.",
        codes: ["FACE_ID_ENROLLED"],
        profile: response.profile
      });
    } catch (err) {
      setEnrollmentNotice({
        type: "failure",
        title: "Face enrollment failed",
        message: err instanceof Error ? err.message : "The face ID could not be enrolled.",
        codes: ["FACE_ID_ENROLLMENT_FAILED"]
      });
    } finally {
      setEnrollBusy(false);
    }
  };

  const faceLogin = async (blob: Blob) => {
    try {
      setFaceLoginBusy(true);
      setFaceLoginResult(null);
      const response = await api.faceLogin(blob);
      setFaceLoginResult(response);
    } catch (err) {
      setFaceLoginResult({
        decision: "rejected",
        matched: false,
        match_score: 0,
        passive_liveness_risk: 1,
        reason_codes: ["FACE_LOGIN_FAILED"],
        profile: null,
        checks: { error: err instanceof Error ? err.message : "Face login failed." },
        signals: []
      });
    } finally {
      setFaceLoginBusy(false);
    }
  };

  const goToStep = (step: StepKey) => {
    if (canAccessStep(step, result)) {
      setActiveStep(step);
      setError(null);
      return;
    }
    setError(firstBlockedReason(step));
  };

  if (screen === "intro") {
    return (
      <IntroScreen
        userId={userId}
        onUserIdChange={setUserId}
        onStart={() => setScreen("verify")}
        onGenerateUserId={() => setUserId(createDemoUserId())}
        onFaceLogin={() => setScreen("face-login")}
      />
    );
  }

  if (screen === "face-login") {
    return (
      <FaceLoginScreen
        busy={faceLoginBusy}
        result={faceLoginResult}
        onCapture={faceLogin}
        onBack={() => setScreen("intro")}
      />
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img src={logoUrl} alt="LALIGENCE" />
        </div>
        <div className="assurance-card">
          <ShieldCheck size={22} />
          <div>
            <span>NIST IAL2-aligned</span>
            <strong>Passport proofing</strong>
          </div>
        </div>
        <nav className="step-list" aria-label="Verification steps">
          {steps.map((step, index) => {
            const Icon = step.icon;
            const isActive = activeStep === step.key;
            const isDone = isStepComplete(step.key, result);
            const isLocked = !canAccessStep(step.key, result);
            return (
              <button
                className={`step-button ${isActive ? "active" : ""} ${isDone ? "done" : ""} ${isLocked ? "locked" : ""}`}
                key={step.key}
                type="button"
                onClick={() => goToStep(step.key)}
                disabled={isLocked}
                title={isLocked ? firstBlockedReason(step.key) : step.label}
                aria-disabled={isLocked}
              >
                <span className="step-icon">{isDone ? <Check size={17} /> : <Icon size={17} />}</span>
                <span>{step.label}</span>
                <ChevronRight size={16} />
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Identity verification</p>
            <h1>Secure passport eKYC</h1>
            {result?.user_id && <span className="user-id-pill">User ID: {result.user_id}</span>}
          </div>
          <div className={`decision-pill decision-${result?.decision ?? "pending"}`}>
            {result?.decision ?? "pending"}
          </div>
        </header>

        <DemoWarning />

        <div className="progress-track" aria-label="Verification progress">
          <span style={{ width: `${progress * 100}%` }} />
        </div>

        <div className="content-grid">
          <section className="work-panel">
            <div className="panel-header">
              <span>{statusMessage}</span>
              {busy && <span className="loading-dot" aria-live="polite">Processing</span>}
            </div>
            {documentBusy && <DocumentUploadOverlay />}
            {activeStep === "document" && documentNotice && <DocumentAnalysisNotice notice={documentNotice} />}
            {error && <div className="alert" role="alert"><ShieldAlert size={18} />{error}</div>}
            {activeStep === "document" && (
              <DocumentStep
                disabled={!sessionReady || documentBusy}
                onUpload={uploadDocument}
                onCapture={captureDocument}
              />
            )}
            {activeStep === "liveness" && (
              <ActiveLivenessStep
                challenges={result?.active_challenges ?? []}
                onComplete={(challenge, allDone) => completeChallenge(challenge, allDone ? "gesture" : undefined)}
              />
            )}
            {activeStep === "gesture" && (
              <HandGestureStep
                challenges={result?.hand_challenges ?? []}
                onComplete={(challenge, allDone) => completeChallenge(challenge, allDone ? "selfie" : undefined)}
              />
            )}
            {activeStep === "selfie" && <SelfieStep busy={selfieBusy} notice={selfieNotice} onCapture={analyzeSelfie} />}
            {activeStep === "result" && result && (
              <ResultStep
                result={result}
                enrollBusy={enrollBusy}
                enrollmentNotice={enrollmentNotice}
                onEnroll={enrollFace}
              />
            )}
          </section>

          <aside className="risk-panel">
            <h2>Live decision</h2>
            <Metric label="Document quality" value={result?.document.image_quality_score ?? 0} />
            <Metric label="Document fraud risk" value={result?.document.fraud_risk_score ?? 0} inverse />
            <Metric label="Face match" value={result?.biometric.face_match_score ?? 0} />
            <Metric label="Passive risk" value={result?.biometric.passive_liveness_risk ?? 1} inverse />
            <Metric label="Selfie quality" value={result?.biometric.selfie_quality_score ?? 0} />
            <div className="reason-list">
              <span>Reason codes</span>
              {(result?.reason_codes.length ? result.reason_codes : ["SESSION_IN_PROGRESS"]).map((reason) => (
                <code key={reason}>{reason}</code>
              ))}
            </div>
            {result && <OcrSummary result={result} compact />}
          </aside>
        </div>
      </section>
    </main>
  );
}

function DocumentUploadOverlay() {
  return (
    <div className="document-upload-overlay" role="status" aria-live="polite" aria-label="Analyzing passport document">
      <div className="scanner-card">
        <div className="scanner-frame">
          <FileImage size={38} />
          <span className="scanner-line" />
        </div>
        <div>
          <strong>Analyzing passport</strong>
          <p>Checking OCR, MRZ, document quality, and fraud signals.</p>
        </div>
      </div>
    </div>
  );
}

function DocumentAnalysisNotice({ notice }: { notice: NonNullable<DocumentNotice> }) {
  const Icon = notice.type === "success" ? ShieldCheck : ShieldAlert;
  return (
    <div className={`document-notice document-notice-${notice.type}`} role="status" aria-live="polite">
      <Icon size={20} />
      <div>
        <strong>{notice.title}</strong>
        <p>{notice.message}</p>
        <div className="document-notice-codes">
          {notice.codes.slice(0, 4).map((code) => (
            <code key={code}>{code}</code>
          ))}
        </div>
      </div>
    </div>
  );
}

function IntroScreen({
  userId,
  onUserIdChange,
  onGenerateUserId,
  onStart,
  onFaceLogin
}: {
  userId: string;
  onUserIdChange: (value: string) => void;
  onGenerateUserId: () => void;
  onStart: () => void;
  onFaceLogin: () => void;
}) {
  const [showNewUserForm, setShowNewUserForm] = useState(false);
  const canStart = userId.trim().length > 0;
  const openNewUserForm = () => {
    if (!canStart) {
      onGenerateUserId();
    }
    setShowNewUserForm(true);
  };

  return (
    <main className="intro-shell">
      <section className="intro-stage" aria-labelledby="intro-title">
        <div className="intro-visual" aria-hidden="true">
          <div className="intro-orbit">
            <span />
            <span />
            <span />
            <div className="intro-logo-mark">
              <img src={logoUrl} alt="" />
            </div>
          </div>
          <div className="intro-preview">
            <div className="preview-passport">
              <div className="preview-passport-photo" />
              <div className="preview-lines">
                <span />
                <span />
                <span />
                <span />
              </div>
              <div className="preview-mrz" />
              <i />
            </div>
            <div className="preview-selfie">
              <div className="preview-face" />
              <span />
            </div>
          </div>
        </div>

        <div className="intro-copy">
          <div className="intro-brand-inline">
            <img src={logoUrl} alt="LALIGENCE" />
          </div>
          <p className="eyebrow">Secure identity verification</p>
          <h1 id="intro-title">Passport eKYC with liveness and fraud checks</h1>
          <p className="intro-description">
            LALIGENCE helps verify passport evidence, guide live face and hand challenges,
            compare a selfie, and return clear risk signals for an IAL2-aligned workflow.
          </p>
          <DemoWarning compact />
          {showNewUserForm ? (
            <div className="new-user-panel">
              <label className="user-id-field">
                <span>New user ID</span>
                <input
                  value={userId}
                  onChange={(event) => onUserIdChange(event.target.value)}
                  placeholder="example: user-001"
                  autoComplete="username"
                />
              </label>
              <div className="intro-actions">
                <button className="primary-button intro-start" type="button" onClick={onStart} disabled={!canStart}>
                  Start verification
                  <ArrowRight size={18} />
                </button>
                <button className="secondary-button intro-start" type="button" onClick={onGenerateUserId}>
                  <UserPlus size={18} />
                  New user ID
                </button>
              </div>
              <button className="text-action-button" type="button" onClick={() => setShowNewUserForm(false)}>
                <KeyRound size={16} />
                Use face login instead
              </button>
            </div>
          ) : (
            <div className="intro-actions">
              <button className="primary-button intro-start" type="button" onClick={onFaceLogin}>
                <KeyRound size={18} />
                Face login
              </button>
              <button className="secondary-button intro-start" type="button" onClick={openNewUserForm}>
                <UserPlus size={18} />
                New user verification
              </button>
            </div>
          )}
        </div>

        <div className="intro-capabilities" aria-label="Application capabilities">
          <div>
            <FileImage size={20} />
            <span>Passport proofing</span>
          </div>
          <div>
            <Fingerprint size={20} />
            <span>Face liveness</span>
          </div>
          <div>
            <Hand size={20} />
            <span>Gesture challenge</span>
          </div>
          <div>
            <ShieldCheck size={20} />
            <span>Risk decision</span>
          </div>
        </div>
      </section>
    </main>
  );
}

function FaceLoginScreen({
  busy,
  result,
  onCapture,
  onBack
}: {
  busy: boolean;
  result: FaceLoginResponse | null;
  onCapture: (blob: Blob) => void;
  onBack: () => void;
}) {
  const passed = result?.decision === "passed";
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="face-login-title">
        <button className="secondary-button back-button" type="button" onClick={onBack}>
          <ArrowLeft size={18} />
          Back
        </button>
        <div className="login-copy">
          <div className="intro-brand-inline">
            <img src={logoUrl} alt="LALIGENCE" />
          </div>
          <p className="eyebrow">Returning user</p>
          <h1 id="face-login-title">Face login</h1>
          <p>
            Capture a live face. The system checks passive liveness, matches it against
            enrolled Face IDs, and loads the verified profile when the match passes.
          </p>
          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
              Checking face login
            </div>
          )}
          {result && (
            <div className={`document-notice document-notice-${passed ? "success" : "failure"}`} role="status">
              {passed ? <UserCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>{passed ? "Face login passed" : "Face login rejected"}</strong>
                <p>
                  {passed
                    ? `Welcome${result.profile?.first_name ? `, ${result.profile.first_name}` : ""}.`
                    : "No verified live face match was found."}
                </p>
                <div className="document-notice-codes">
                  {(result.reason_codes.length ? result.reason_codes : ["FACE_LOGIN_PASSED"]).slice(0, 4).map((code) => (
                    <code key={code}>{code}</code>
                  ))}
                </div>
              </div>
            </div>
          )}
          {result?.profile && <ProfileSummary profile={result.profile} />}
        </div>
        <CameraCapture
          label="Returning user face login"
          overlay="face"
          onCapture={onCapture}
          maxCaptureWidth={720}
          jpegQuality={0.84}
        />
      </section>
    </main>
  );
}

function DemoWarning({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`demo-warning ${compact ? "demo-warning-compact" : ""}`} role="note">
      <ShieldAlert size={18} />
      <span>Public demo: use sample or redacted documents only. Do not upload sensitive real identity documents.</span>
    </div>
  );
}

function ActiveLivenessStep({
  challenges,
  onComplete
}: {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Challenge</p>
        <h2>Active face liveness</h2>
        <p>
          Open the camera and perform the highlighted action. The system detects the correct movement
          and automatically advances each challenge when it passes.
        </p>
      </div>
      <ActiveLivenessCapture challenges={challenges} onComplete={onComplete} />
    </div>
  );
}

function HandGestureStep({
  challenges,
  onComplete
}: {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Challenge</p>
        <h2>Hand gesture challenge</h2>
        <p>
          Open the full-screen camera and place your hand inside the gold circle. The target moves to
          a random position for each gesture, and the step auto-passes when the correct sign is detected.
        </p>
      </div>
      <HandGestureCapture challenges={challenges} onComplete={onComplete} />
    </div>
  );
}

function DocumentStep({
  disabled,
  onUpload,
  onCapture
}: {
  disabled: boolean;
  onUpload: (event: ChangeEvent<HTMLInputElement>) => void;
  onCapture: (blob: Blob) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Step 1</p>
        <h2>Capture passport evidence</h2>
        <p>Upload a clear passport image or capture one with the camera. The backend checks image quality, document-shaped evidence, file type, and fraud-risk signals.</p>
        {disabled && (
          <div className="session-waiting" role="status" aria-live="polite">
            <span />
            Connecting verification session
          </div>
        )}
        <label className={`upload-drop ${disabled ? "disabled" : ""}`} htmlFor={disabled ? undefined : "passport-upload"} aria-disabled={disabled}>
          <Upload size={24} />
          <span>Upload passport image</span>
          <small>{disabled ? "Wait until the session is ready" : "JPG, PNG, or WebP"}</small>
          <input id="passport-upload" type="file" accept="image/*" onChange={onUpload} disabled={disabled} />
        </label>
      </div>
      <CameraCapture
        label="Passport camera capture"
        overlay="document"
        onCapture={onCapture}
        disabled={disabled}
        maxCaptureWidth={1600}
        jpegQuality={0.88}
      />
    </div>
  );
}

function ChallengeStep({
  title,
  description,
  overlay,
  challenges,
  onComplete
}: {
  title: string;
  description: string;
  overlay: "face" | "hand";
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Challenge</p>
        <h2>{title}</h2>
        <p>{description}</p>
        <div className="challenge-list">
          {challenges.map((challenge) => {
            const remainingAfterThis = challenges.filter((item) => !item.passed && item.id !== challenge.id).length;
            return (
              <button
                className={`challenge-card ${challenge.passed ? "passed" : ""}`}
                key={challenge.id}
                type="button"
                onClick={() => onComplete(challenge, remainingAfterThis === 0)}
                disabled={challenge.passed}
              >
                <span>{challenge.prompt}</span>
                <small>{challenge.instruction}</small>
              </button>
            );
          })}
        </div>
      </div>
      <CameraCapture label={title} overlay={overlay} onCapture={() => undefined} />
    </div>
  );
}

function SelfieStep({
  busy,
  notice,
  onCapture
}: {
  busy: boolean;
  notice: SelfieNotice;
  onCapture: (blob: Blob) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Step 4</p>
        <h2>Selfie face match</h2>
        <p>Open the camera, center your face in the oval, and capture a live selfie for passive liveness and face-match scoring.</p>
        {notice && <DocumentAnalysisNotice notice={notice} />}
        {busy && (
          <div className="selfie-loading" role="status" aria-live="polite">
            <span />
            Analyzing selfie
          </div>
        )}
      </div>
      <CameraCapture
        label="Selfie capture"
        overlay="face"
        onCapture={onCapture}
        maxCaptureWidth={900}
        jpegQuality={0.84}
      />
    </div>
  );
}

function ResultStep({
  result,
  enrollBusy,
  enrollmentNotice,
  onEnroll
}: {
  result: VerificationResult;
  enrollBusy: boolean;
  enrollmentNotice: EnrollmentNotice;
  onEnroll: () => void;
}) {
  const passed = result.decision === "passed";
  return (
    <div className="result-state">
      {passed ? <ShieldCheck size={42} /> : <ShieldAlert size={42} />}
      <h2>{passed ? "Verification passed" : result.decision === "rejected" ? "Verification rejected" : "Verification pending"}</h2>
      <p>Final decision uses document analysis, active liveness, hand gesture checks, passive liveness, and face-match thresholds.</p>
      {passed && (
        <button className="primary-button" type="button" onClick={onEnroll} disabled={enrollBusy}>
          <UserCheck size={18} />
          {enrollBusy ? "Enrolling Face ID" : "Enroll Face ID"}
        </button>
      )}
      {enrollmentNotice && <DocumentAnalysisNotice notice={enrollmentNotice} />}
      {enrollmentNotice?.profile && <ProfileSummary profile={enrollmentNotice.profile} />}
      <div className="result-grid">
        <Metric label="Quality" value={result.document.image_quality_score} />
        <Metric label="Fraud risk" value={result.document.fraud_risk_score} inverse />
        <Metric label="Face match" value={result.biometric.face_match_score} />
        <Metric label="Passive risk" value={result.biometric.passive_liveness_risk} inverse />
      </div>
      <OcrSummary result={result} />
    </div>
  );
}

function ProfileSummary({ profile }: { profile: UserProfile }) {
  const rows = [
    ["User ID", profile.user_id],
    ["Face ID", profile.face_id],
    ["First name", profile.first_name],
    ["Last name", profile.last_name],
    ["Age", profile.age?.toString()],
    ["Nationality", profile.nationality],
    ["Passport No.", profile.passport_number],
    ["Passport expiry", profile.passport_expiry]
  ].filter(([, value]) => value);

  return (
    <section className="profile-summary" aria-label="Verified user profile">
      <h3>Verified profile</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function OcrSummary({ result, compact = false }: { result: VerificationResult; compact?: boolean }) {
  const ocr = result.document.ocr;
  const rows = [
    ["Name", ocr.full_name],
    ["Passport No.", ocr.passport_number],
    ["Nationality", ocr.nationality],
    ["Date of birth", ocr.date_of_birth],
    ["Expiry", ocr.expiry_date],
    ["MRZ valid", ocr.mrz_valid === null ? null : ocr.mrz_valid ? "Yes" : "No"]
  ].filter(([, value]) => value);

  if (!rows.length) return null;

  return (
    <section className={`ocr-summary ${compact ? "compact" : ""}`} aria-label="Passport OCR result">
      <h3>Passport OCR</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Metric({ label, value, inverse = false }: { label: string; value: number; inverse?: boolean }) {
  const display = formatPercent(value);
  const healthy = inverse ? value <= 0.34 : value >= 0.75;
  return (
    <div className="metric">
      <div>
        <span>{label}</span>
        <strong className={healthy ? "good" : "watch"}>{display}</strong>
      </div>
      <div className="meter"><span style={{ width: display }} /></div>
    </div>
  );
}
