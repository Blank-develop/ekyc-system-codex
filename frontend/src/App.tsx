import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Camera,
  Check,
  ChevronRight,
  Download,
  FileImage,
  Fingerprint,
  Hand,
  KeyRound,
  Landmark,
  LockKeyhole,
  ReceiptText,
  Send,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserPlus,
  Upload,
  X
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import logoUrl from "./assets/logo.png";
import { ActiveLivenessCapture } from "./components/ActiveLivenessCapture";
import { CameraCapture } from "./components/CameraCapture";
import { HandGestureCapture } from "./components/HandGestureCapture";
import { api, Challenge, DocumentType, FaceLoginResponse, UserProfile, VerificationResult } from "./lib/api";
import { optimizeImageForUpload } from "./lib/image";

type StepKey = "document" | "liveness" | "gesture" | "selfie" | "result";
type Screen = "intro" | "verify" | "face-login" | "payment" | "manage-data";
type ManageResult =
  | { kind: "export-ok"; message: string }
  | { kind: "delete-ok"; message: string }
  | { kind: "error"; message: string }
  | null;
type DocumentNotice = {
  type: "success" | "failure";
  title: string;
  message: string;
  codes: string[];
} | null;
type SelfieNotice = DocumentNotice;
type EnrollmentNotice = (NonNullable<DocumentNotice> & { profile?: UserProfile }) | null;
const FACE_MATCH_PASS_THRESHOLD = 0.68;
const documentLabels: Record<DocumentType, { title: string; short: string; upload: string }> = {
  passport: {
    title: "Passport",
    short: "Passport",
    upload: "passport"
  },
  lao_id_card: {
    title: "Lao ID card",
    short: "Lao ID",
    upload: "Lao ID card"
  }
};

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
  if (codes.includes("SELFIE_BURST_FACE_TOO_SMALL") || codes.includes("SELFIE_FACE_TOO_SMALL")) {
    return "You are a bit too far from the camera. Move your face closer until it fills the yellow circle, then capture again.";
  }
  if (codes.includes("FACE_MATCH_LOW")) {
    return `Face match is below the acceptance threshold (${Math.round(matchScore * 100)}%). Try a front-facing selfie with the same person as the document.`;
  }
  if (codes.includes("PASSPORT_FACE_REFERENCE_MISSING")) {
    return "Document portrait could not be used as a face reference. Re-upload a clearer document image.";
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
  if (step === "liveness") return "Upload an accepted identity document first.";
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
  const [documentType, setDocumentType] = useState<DocumentType>("passport");
  const [documentNotice, setDocumentNotice] = useState<DocumentNotice>(null);
  const [selfieBusy, setSelfieBusy] = useState(false);
  const [selfieNotice, setSelfieNotice] = useState<SelfieNotice>(null);
  const [enrollBusy, setEnrollBusy] = useState(false);
  const [enrollmentNotice, setEnrollmentNotice] = useState<EnrollmentNotice>(null);
  const [faceLoginBusy, setFaceLoginBusy] = useState(false);
  const [faceLoginResult, setFaceLoginResult] = useState<FaceLoginResponse | null>(null);
  const [manageBusy, setManageBusy] = useState(false);
  const [manageResult, setManageResult] = useState<ManageResult>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("Starting verification session");
  const [toast, setToast] = useState<{ id: number; kind: "success" | "error" | "info"; title: string; message?: string } | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  const showToast = useCallback((kind: "success" | "error" | "info", title: string, message?: string) => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast({ id: Date.now(), kind, title, message });
    // Stay visible long enough to read, then fade. Errors linger a bit longer.
    const duration = kind === "error" ? 8000 : 6000;
    toastTimerRef.current = window.setTimeout(() => setToast(null), duration);
  }, []);

  const dismissToast = useCallback(() => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast(null);
  }, []);

  useEffect(() => {
    if (error) showToast("error", "Something needs attention", error);
  }, [error, showToast]);

  useEffect(() => {
    if (documentNotice) showToast(documentNotice.type === "success" ? "success" : "error", documentNotice.title, documentNotice.message);
  }, [documentNotice, showToast]);

  useEffect(() => {
    if (selfieNotice) showToast(selfieNotice.type === "success" ? "success" : "error", selfieNotice.title, selfieNotice.message);
  }, [selfieNotice, showToast]);

  useEffect(() => {
    if (enrollmentNotice) showToast(enrollmentNotice.type === "success" ? "success" : "error", enrollmentNotice.title, enrollmentNotice.message);
  }, [enrollmentNotice, showToast]);

  useEffect(() => {
    if (result?.decision === "passed") showToast("success", "Verification passed", "All checks passed — you're verified.");
    else if (result?.decision === "rejected") showToast("error", "Verification rejected", "One or more checks failed. See the reason codes below.");
  }, [result?.decision, showToast]);

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
        setStatusMessage(`${documentLabels[documentType].title} rejected. Please upload a clearer or valid document image.`);
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
          title: `${documentLabels[documentType].title} accepted`,
          message: documentType === "passport" ? "Document quality, OCR/MRZ, and fraud checks passed." : "Document quality, OCR fields, and fraud checks passed.",
          codes: ["DOCUMENT_PASSED"]
        });
        setActiveStep("document");
        window.setTimeout(() => {
          setActiveStep("liveness");
        }, 900);
      } else {
        const codes = nextResult.document.signals.map((signal) => signal.code);
        setActiveStep("document");
        setStatusMessage(`${documentLabels[documentType].title} rejected. Please upload a clearer or valid document image.`);
        setDocumentNotice({
          type: "failure",
          title: `${documentLabels[documentType].title} rejected`,
          message: `Please upload a clearer, valid ${documentLabels[documentType].upload} image and try again.`,
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
        file,
        documentType
      ),
      `${documentLabels[documentType].title} analyzed`
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
          maxWidth: 2200,
          quality: 0.95,
          filename: `${documentType}-capture-optimized.jpg`
        }),
        documentType
      ),
      `${documentLabels[documentType].title} capture analyzed`
    );
  };

  const completeChallenge = (challenge: Challenge, next?: StepKey) => {
    if (!sessionId) return;
    sync(() => api.completeChallenge(sessionId, challenge.id, challenge.nonce), `${challenge.prompt} confirmed`, next);
  };

  const verifyActiveChallenge = async (challenge: Challenge, allDone: boolean, evidence: Blob | Blob[]) => {
    if (!sessionId) return false;
    setBusy(true);
    setError(null);
    try {
      const optimizedEvidence = Array.isArray(evidence)
        ? await Promise.all(evidence.map((frame, index) => optimizeImageForUpload(frame, {
            maxWidth: 900,
            quality: 0.84,
            filename: `${challenge.id}-active-liveness-${index + 1}.jpg`
          })))
        : await optimizeImageForUpload(evidence, {
            maxWidth: 900,
            quality: 0.84,
            filename: `${challenge.id}-active-liveness.jpg`
          });
      const nextResult = await api.verifyActiveLiveness(sessionId, challenge.id, optimizedEvidence);
      setResult(nextResult);
      const accepted = nextResult.active_challenges.find((item) => item.id === challenge.id)?.passed === true;
      if (accepted) {
        setStatusMessage(`${challenge.prompt} confirmed with live-face check`);
        if (allDone && canAccessStep("gesture", nextResult)) {
          setActiveStep("gesture");
        }
        return true;
      }

      const codes = nextResult.biometric.active_liveness_signals.map((signal) => signal.code);
      if (codes.includes("ACTIVE_LIVENESS_REPLAY_DETECTED")) {
        setStatusMessage("Active liveness needs a clean live-face retry.");
        setError("Screen or replay detected. Keep the same session, remove the screen, and repeat the action with your real face directly in front of the camera.");
      } else {
        setStatusMessage("Active liveness rejected. Please use your real face directly in front of the camera.");
        setError(codes.length ? `Active liveness rejected: ${codes.join(", ")}` : "Active liveness rejected. Try again.");
      }
      return false;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Active liveness could not be verified.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const analyzeSelfie = async (capture: Blob | Blob[]) => {
    if (!sessionId) return;
    try {
      setSelfieBusy(true);
      setSelfieNotice(null);
      setBusy(true);
      setError(null);
      const optimizedCapture = Array.isArray(capture)
        ? await Promise.all(capture.map((blob, index) => optimizeImageForUpload(blob, {
            maxWidth: 900,
            quality: 0.82,
            filename: `selfie-burst-${index + 1}-optimized.jpg`
          })))
        : await optimizeImageForUpload(capture, {
            maxWidth: 900,
            quality: 0.84,
            filename: "selfie-capture-optimized.jpg"
          });
      const nextResult = await api.analyzeSelfie(sessionId, optimizedCapture);
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

  const exportMyData = async (blob: Blob) => {
    try {
      setManageBusy(true);
      setManageResult(null);
      const res = await api.exportMyData(blob);
      if (res.verified && res.profile) {
        const json = new Blob([JSON.stringify(res.profile, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(json);
        const link = document.createElement("a");
        link.href = url;
        link.download = `kyron-my-data-${res.profile.user_id}.json`;
        link.click();
        URL.revokeObjectURL(url);
        setManageResult({ kind: "export-ok", message: "Face verified — your data has been downloaded as a JSON file." });
      } else {
        setManageResult({ kind: "error", message: `Could not verify your face${res.reason_codes.length ? ` (${res.reason_codes.join(", ")})` : ""}.` });
      }
    } catch (err) {
      setManageResult({ kind: "error", message: err instanceof Error ? err.message : "Export failed." });
    } finally {
      setManageBusy(false);
    }
  };

  const deleteMyData = async (blob: Blob) => {
    try {
      setManageBusy(true);
      setManageResult(null);
      const res = await api.deleteMyData(blob);
      if (res.verified && res.deleted) {
        setManageResult({ kind: "delete-ok", message: "Face verified — your enrolled data has been permanently deleted." });
      } else if (res.verified) {
        setManageResult({ kind: "error", message: "Verified, but no enrolled data was found to delete." });
      } else {
        setManageResult({ kind: "error", message: `Could not verify your face${res.reason_codes.length ? ` (${res.reason_codes.join(", ")})` : ""}.` });
      }
    } catch (err) {
      setManageResult({ kind: "error", message: err instanceof Error ? err.message : "Deletion failed." });
    } finally {
      setManageBusy(false);
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

  if (screen === "manage-data") {
    return (
      <ManageDataScreen
        busy={manageBusy}
        result={manageResult}
        onExport={exportMyData}
        onDelete={deleteMyData}
        onBack={() => setScreen("intro")}
      />
    );
  }

  if (screen === "payment") {
    return (
      <PaymentScreen
        onBack={() => setScreen("intro")}
        onSignup={() => {
          if (!normalizedUserId) setUserId(createDemoUserId());
          setScreen("verify");
        }}
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
      <StatusToast toast={toast} onClose={dismissToast} />
      <aside className="sidebar">
        <div className="brand">
          <img src={logoUrl} alt="Kyron" />
        </div>
        <div className="assurance-card">
          <ShieldCheck size={22} />
          <div>
            <span>NIST IAL2-aligned</span>
            <strong>{documentLabels[documentType].title} proofing</strong>
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
                <span>{step.key === "document" ? documentLabels[documentType].short : step.label}</span>
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
            <h1>Kyron secure eKYC</h1>
            {result?.user_id && <span className="user-id-pill">User ID: {result.user_id}</span>}
          </div>
          <div className={`decision-pill decision-${result?.decision ?? "pending"}`}>
            {result?.decision ?? "pending"}
          </div>
        </header>

        <DemoWarning compact />

        <div className="progress-track" aria-label="Verification progress">
          <span style={{ width: `${progress * 100}%` }} />
        </div>

        <div className="content-grid">
          <section className="work-panel">
            <div className="panel-header">
              <span>{statusMessage}</span>
              {busy && <span className="loading-dot" aria-live="polite">Processing</span>}
            </div>
            {documentBusy && <DocumentUploadOverlay documentType={documentType} />}
            {activeStep === "document" && documentNotice && <DocumentAnalysisNotice notice={documentNotice} />}
            {error && (
              <div className="alert" role="alert">
                <ShieldAlert size={18} />
                <span>{error}</span>
              </div>
            )}
            {activeStep === "document" && (
              <DocumentStep
                documentType={documentType}
                onDocumentTypeChange={setDocumentType}
                disabled={!sessionReady || documentBusy}
                onUpload={uploadDocument}
                onCapture={captureDocument}
              />
            )}
            {activeStep === "liveness" && (
              <ActiveLivenessStep
                challenges={result?.active_challenges ?? []}
                onComplete={verifyActiveChallenge}
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

function DocumentUploadOverlay({ documentType }: { documentType: DocumentType }) {
  const label = documentLabels[documentType];
  return (
    <div className="document-upload-overlay" role="status" aria-live="polite" aria-label={`Analyzing ${label.upload} document`}>
      <div className="scanner-card">
        <div className="scanner-frame">
          <FileImage size={38} />
          <span className="scanner-line" />
        </div>
        <div>
          <strong>Analyzing {label.upload}</strong>
          <p>{documentType === "passport" ? "Checking OCR, MRZ, document quality, and fraud signals." : "Checking OCR fields, document quality, and fraud signals."}</p>
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
        <div className="intro-copy">
          <p className="eyebrow">Secure identity verification</p>
          <h1 id="intro-title">Verify once. Pay and sign in by face.</h1>
          <p className="intro-description">
            Kyron combines passport proofing, live face checks, gesture challenges,
            face matching, and clear risk decisions in one IAL2-aligned workflow.
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
              <button className="primary-button intro-start" type="button" onClick={openNewUserForm}>
                <UserPlus size={18} />
                New user signup
              </button>
              <button className="secondary-button intro-start" type="button" onClick={onFaceLogin}>
                <KeyRound size={18} />
                Login
              </button>
            </div>
          )}
        </div>

        <div className="intro-visual" aria-hidden="true">
          <div className="intro-ekyc-animation">
            <div className="ekyc-orbit-ring" />
            <div className="ekyc-orbit-ring secondary" />
            <div className="ekyc-logo-card">
              <img src={logoUrl} alt="" />
              <span>Kyron secure access</span>
            </div>
            <div className="ekyc-document-card">
              <div className="ekyc-photo" />
              <div className="ekyc-lines">
                <span />
                <span />
                <span />
              </div>
              <div className="ekyc-mrz" />
              <span className="ekyc-scan-line" />
            </div>
            <div className="ekyc-face-card">
              <Fingerprint size={34} />
              <span />
            </div>
            <div className="ekyc-status-chip">
              <ShieldCheck size={16} />
              Verified
            </div>
            <div className="ekyc-step-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          </div>
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
            <img src={logoUrl} alt="Kyron" />
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

function ManageDataScreen({
  busy,
  result,
  onExport,
  onDelete,
  onBack
}: {
  busy: boolean;
  result: ManageResult;
  onExport: (blob: Blob) => void;
  onDelete: (blob: Blob) => void;
  onBack: () => void;
}) {
  const [action, setAction] = useState<"export" | "delete" | null>(null);
  const handleCapture = (blob: Blob) => {
    if (action === "export") onExport(blob);
    else if (action === "delete") onDelete(blob);
  };
  const ok = result?.kind === "export-ok" || result?.kind === "delete-ok";
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="manage-title">
        <button className="secondary-button back-button" type="button" onClick={onBack}>
          <ArrowLeft size={18} />
          Back
        </button>
        <div className="login-copy">
          <div className="intro-brand-inline">
            <img src={logoUrl} alt="Kyron" />
          </div>
          <p className="eyebrow">Your data rights</p>
          <h1 id="manage-title">Manage my data</h1>
          <p>
            Verify with a live selfie to export a copy of your enrolled data, or
            permanently delete it. Your face proves it&rsquo;s you — no one else can
            access your record.
          </p>

          {!action && (
            <div className="intro-actions">
              <button className="primary-button intro-start" type="button" onClick={() => setAction("export")}>
                <Download size={18} />
                Export my data
              </button>
              <button className="secondary-button intro-start" type="button" onClick={() => setAction("delete")}>
                <Trash2 size={18} />
                Delete my data
              </button>
            </div>
          )}

          {action && (
            <>
              <div className={`manage-action-banner manage-action-${action}`}>
                {action === "export" ? <Download size={16} /> : <ShieldAlert size={16} />}
                <span>
                  {action === "export"
                    ? "Capture a live selfie to download your data."
                    : "Capture a live selfie to permanently delete your data. This cannot be undone."}
                </span>
              </div>
              <button className="text-action-button" type="button" onClick={() => setAction(null)}>
                Choose a different action
              </button>
            </>
          )}

          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
              {action === "delete" ? "Verifying and deleting" : "Verifying and exporting"}
            </div>
          )}

          {result && (
            <div className={`document-notice document-notice-${ok ? "success" : "failure"}`} role="status">
              {ok ? <UserCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>
                  {result.kind === "export-ok"
                    ? "Data exported"
                    : result.kind === "delete-ok"
                      ? "Data deleted"
                      : "Not verified"}
                </strong>
                <p>{result.message}</p>
              </div>
            </div>
          )}
        </div>
        {action && (
          <CameraCapture
            label={action === "export" ? "Selfie to export your data" : "Selfie to delete your data"}
            overlay="face"
            onCapture={handleCapture}
            maxCaptureWidth={720}
            jpegQuality={0.84}
          />
        )}
      </section>
    </main>
  );
}

function PaymentScreen({ onBack, onSignup }: { onBack: () => void; onSignup: () => void }) {
  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("LAK");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [authResult, setAuthResult] = useState<FaceLoginResponse | null>(null);
  const [transferId, setTransferId] = useState<string | null>(null);
  const numericAmount = Number(amount);
  const canAuthorize = recipient.trim().length >= 2 && Number.isFinite(numericAmount) && numericAmount > 0 && !busy;
  const approved = authResult?.decision === "passed" && Boolean(transferId);

  const authorizeTransfer = async (blob: Blob) => {
    if (!canAuthorize) return;
    try {
      setBusy(true);
      setAuthResult(null);
      setTransferId(null);
      const optimized = await optimizeImageForUpload(blob, {
        maxWidth: 720,
        quality: 0.84,
        filename: "face-pay-login.jpg"
      });
      const response = await api.faceLogin(optimized);
      setAuthResult(response);
      if (response.decision === "passed") {
        setTransferId(`LP-${Date.now().toString(36).toUpperCase()}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="payment-shell">
      <section className="payment-panel" aria-labelledby="payment-title">
        <button className="secondary-button back-button" type="button" onClick={onBack}>
          <ArrowLeft size={18} />
          Back
        </button>
        <div className="payment-copy">
          <div className="payment-brand">
            <img src={logoUrl} alt="Kyron" />
            <span>Face Pay</span>
          </div>
          <p className="eyebrow">Bank transfer authorization</p>
          <h1 id="payment-title">Transfer with Face ID</h1>
          <p className="payment-note">Demo mode: no real money moves. Each transfer requires an enrolled live Face ID.</p>

          <div className="payment-card" aria-label="Transfer details">
            <label>
              <span>Recipient</span>
              <input value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="Account name or number" />
            </label>
            <div className="payment-amount-grid">
              <label>
                <span>Amount</span>
                <input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0" />
              </label>
              <label>
                <span>Currency</span>
                <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
                  <option>LAK</option>
                  <option>USD</option>
                  <option>THB</option>
                </select>
              </label>
            </div>
            <label>
              <span>Note</span>
              <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional" />
            </label>
          </div>

          <div className="payment-security-row">
            <div><LockKeyhole size={18} /><span>Face ID required</span></div>
            <div><Landmark size={18} /><span>Verified profile only</span></div>
            <div><ReceiptText size={18} /><span>Result receipt</span></div>
          </div>

          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
              Authorizing transfer
            </div>
          )}

          {authResult && (
            <div className={`document-notice document-notice-${approved ? "success" : "failure"}`} role="status">
              {approved ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>{approved ? "Transfer authorized" : "Transfer blocked"}</strong>
                <p>
                  {approved
                    ? `${currency} ${numericAmount.toLocaleString()} to ${recipient.trim()} was approved by Face ID.`
                    : "Face ID authorization did not pass. Ask the user to complete signup or try again."}
                </p>
                <div className="document-notice-codes">
                  {(authResult.reason_codes.length ? authResult.reason_codes : [transferId ?? "FACE_PAY_APPROVED"]).slice(0, 4).map((code) => (
                    <code key={code}>{code}</code>
                  ))}
                </div>
              </div>
            </div>
          )}

          {authResult?.profile && <ProfileSummary profile={authResult.profile} />}

          <button className="text-action-button" type="button" onClick={onSignup}>
            <UserPlus size={16} />
            New user signup
          </button>
        </div>

        <div className="payment-auth">
          <div className="payment-auth-header">
            <Send size={20} />
            <div>
              <strong>{canAuthorize ? "Scan Face ID to transfer" : "Enter transfer details"}</strong>
              <span>{canAuthorize ? "Live face authorization is required." : "Recipient and amount are required first."}</span>
            </div>
          </div>
          <CameraCapture
            label="Face Pay authorization"
            overlay="face"
            onCapture={authorizeTransfer}
            disabled={!canAuthorize}
            maxCaptureWidth={720}
            jpegQuality={0.84}
          />
        </div>
      </section>
    </main>
  );
}

function StatusToast({
  toast,
  onClose
}: {
  toast: { id: number; kind: "success" | "error" | "info"; title: string; message?: string } | null;
  onClose: () => void;
}) {
  if (!toast) return null;
  const Icon = toast.kind === "success" ? ShieldCheck : toast.kind === "error" ? ShieldAlert : BadgeCheck;
  return (
    <div className={`status-toast status-toast-${toast.kind}`} role="status" aria-live="assertive" key={toast.id}>
      <Icon size={20} className="status-toast-icon" aria-hidden="true" />
      <div className="status-toast-body">
        <strong>{toast.title}</strong>
        {toast.message && <span>{toast.message}</span>}
      </div>
      <button className="status-toast-close" type="button" onClick={onClose} aria-label="Dismiss notification">
        <X size={18} />
      </button>
    </div>
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
  onComplete: (challenge: Challenge, allDone: boolean, evidence: Blob[]) => Promise<boolean>;
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
  documentType,
  onDocumentTypeChange,
  disabled,
  onUpload,
  onCapture
}: {
  documentType: DocumentType;
  onDocumentTypeChange: (documentType: DocumentType) => void;
  disabled: boolean;
  onUpload: (event: ChangeEvent<HTMLInputElement>) => void;
  onCapture: (blob: Blob) => void;
}) {
  const label = documentLabels[documentType];
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Step 1</p>
        <h2>Capture {label.upload} evidence</h2>
        <p>Upload a clear {label.upload} image or capture one with the camera. The backend checks image quality, document-shaped evidence, OCR fields, and fraud-risk signals.</p>
        <div className="document-type-switch" aria-label="Document type">
          {(["passport", "lao_id_card"] as DocumentType[]).map((type) => (
            <button
              className={documentType === type ? "active" : ""}
              key={type}
              type="button"
              onClick={() => onDocumentTypeChange(type)}
              disabled={disabled}
            >
              {documentLabels[type].title}
            </button>
          ))}
        </div>
        {disabled && (
          <div className="session-waiting" role="status" aria-live="polite">
            <span />
            Connecting verification session
          </div>
        )}
        <label className={`upload-drop ${disabled ? "disabled" : ""}`} htmlFor={disabled ? undefined : "passport-upload"} aria-disabled={disabled}>
          <Upload size={24} />
          <span>Upload {label.upload} image</span>
          <small>{disabled ? "Wait until the session is ready" : "JPG, PNG, or WebP"}</small>
          <input id="passport-upload" type="file" accept="image/*" onChange={onUpload} disabled={disabled} />
        </label>
      </div>
      <CameraCapture
        label={`${label.title} camera capture`}
        overlay="document"
        facingMode="environment"
        onCapture={onCapture}
        disabled={disabled}
        maxCaptureWidth={2200}
        jpegQuality={0.95}
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
  onCapture: (capture: Blob | Blob[]) => void;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">Step 4</p>
        <h2>Selfie face match</h2>
        <p>Open the camera and move close so your face fills the yellow circle, then capture a short live burst for passive liveness and face-match scoring.</p>
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
        onCaptureFrames={onCapture}
        maxCaptureWidth={900}
        jpegQuality={0.84}
        burstCount={10}
        burstIntervalMs={250}
        captureLabel="Capture live burst"
        hint="Move close so your face fills the yellow circle before capturing."
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
    ["Document No.", profile.passport_number],
    ["Document expiry", profile.passport_expiry]
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
  const isLaoId = ocr.document_type === "lao_id_card";
  const rows = [
    ["Name", ocr.full_name],
    [isLaoId ? "ID No." : "Passport No.", ocr.id_number ?? ocr.document_number ?? ocr.passport_number],
    ["Nationality", ocr.nationality],
    ["Date of birth", ocr.date_of_birth],
    ["Expiry", ocr.expiry_date],
    [isLaoId ? "OCR confidence" : "MRZ valid", isLaoId ? `${Math.round(ocr.confidence * 100)}%` : ocr.mrz_valid === null ? null : ocr.mrz_valid ? "Yes" : "No"]
  ].filter(([, value]) => value);

  if (!rows.length) return null;

  return (
    <section className={`ocr-summary ${compact ? "compact" : ""}`} aria-label={`${documentLabels[ocr.document_type].title} OCR result`}>
      <h3>{documentLabels[ocr.document_type].title} OCR</h3>
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
