import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Camera,
  Check,
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
import { KyronWordmark } from "./components/KyronMark";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { ActiveLivenessCapture } from "./components/ActiveLivenessCapture";
import { CameraCapture } from "./components/CameraCapture";
import { HandGestureCapture } from "./components/HandGestureCapture";
import { api, Challenge, DocumentType, FaceLoginResponse, UserProfile, VerificationResult } from "./lib/api";
import { optimizeImageForUpload } from "./lib/image";
import { challengePrompt, statusLabel } from "./lib/lao";
import { L } from "./lib/i18n";

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
  get passport() {
    return {
      title: L("ໜັງສືຜ່ານແດນ", "Passport"),
      short: L("ໜັງສືຜ່ານແດນ", "Passport"),
      upload: L("ໜັງສືຜ່ານແດນ", "passport")
    };
  },
  get lao_id_card() {
    return {
      title: L("ບັດປະຈຳຕົວລາວ", "Lao ID card"),
      short: L("ບັດປະຈຳຕົວ", "Lao ID"),
      upload: L("ບັດປະຈຳຕົວລາວ", "Lao ID card")
    };
  }
};

const steps: Array<{ key: StepKey; label: string; icon: typeof FileImage }> = [
  { key: "document", get label() { return L("ໜັງສືຜ່ານແດນ", "Passport"); }, icon: FileImage },
  { key: "liveness", get label() { return L("ກວດໃບໜ້າຈິງ", "Face liveness"); }, icon: Fingerprint },
  { key: "gesture", get label() { return L("ທ່າທາງມື", "Gesture"); }, icon: Hand },
  { key: "selfie", get label() { return L("ເຊວຟີ", "Selfie"); }, icon: Camera },
  { key: "result", get label() { return L("ຜົນລັບ", "Result"); }, icon: BadgeCheck }
];

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;

const createDemoUserId = () => {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const suffix = Math.random().toString(36).slice(2, 8);
  return `user-${date}-${suffix}`;
};

const selfieFailureMessage = (codes: string[], matchScore: number) => {
  if (codes.includes("SELFIE_BURST_FACE_TOO_SMALL") || codes.includes("SELFIE_FACE_TOO_SMALL")) {
    return L("ທ່ານຢູ່ໄກກ້ອງເກີນໄປ. ເລື່ອນໃບໜ້າເຂົ້າມາໃກ້ຈົນເຕັມວົງມົນສີເຫຼືອງ ແລ້ວຖ່າຍໃໝ່.", "You are a bit too far from the camera. Move your face closer until it fills the yellow circle, then capture again.");
  }
  if (codes.includes("FACE_MATCH_LOW")) {
    return L(`ຄະແນນການທຽບໃບໜ້າຕ່ຳກວ່າເກນທີ່ຍອມຮັບ (${Math.round(matchScore * 100)}%). ກະລຸນາຖ່າຍເຊວຟີໜ້າຊື່ ໂດຍເປັນຄົນດຽວກັບໃນເອກະສານ.`, `Face match is below the acceptance threshold (${Math.round(matchScore * 100)}%). Try a front-facing selfie with the same person as the document.`);
  }
  if (codes.includes("PASSPORT_FACE_REFERENCE_MISSING")) {
    return L("ບໍ່ສາມາດໃຊ້ຮູບໃບໜ້າໃນເອກະສານເພື່ອທຽບໄດ້. ກະລຸນາອັບໂຫຼດຮູບເອກະສານທີ່ຊັດເຈນກວ່າເກົ່າ.", "Document portrait could not be used as a face reference. Re-upload a clearer document image.");
  }
  // Lighting is the most common cause of a false "spoof" for genuine users, so
  // give actionable guidance before the generic replay message.
  if (codes.includes("SELFIE_LIGHTING_TOO_BRIGHT")) {
    return L("ແສງສະຫວ່າງເກີນໄປ ຫຼື ມີແສງຢູ່ທາງຫຼັງທ່ານ. ຍ້າຍອອກຫ່າງຈາກປ່ອງຢ້ຽມ ຫຼື ໄຟທີ່ຢູ່ທາງຫຼັງ, ຫັນໜ້າເຂົ້າຫາແສງອ່ອນໆທີ່ສະໝ່ຳສະເໝີ, ຫຼີກລ່ຽງແສງສະທ້ອນຈາກແວ່ນຕາ ແລ້ວຖ່າຍໃໝ່.", "Your lighting looks too bright or you're backlit. Move away from the bright window or light behind you, face a soft even light, remove glare from glasses, then capture again.");
  }
  if (codes.some((code) => code.includes("SPOOF") || code.includes("SCREEN"))) {
    return L("ບໍ່ສາມາດຢືນຢັນວ່າເປັນໃບໜ້າຈິງໄດ້. ຖ້າທ່ານໃຊ້ກ້ອງແທ້ ສ່ວນຫຼາຍແມ່ນຍ້ອນແສງ ຫຼື ພື້ນຫຼັງ — ຫຼີກລ່ຽງປ່ອງຢ້ຽມ ຫຼື ໄຟສະຫວ່າງທາງຫຼັງ, ຍ້າຍໄປບ່ອນທີ່ມີແສງສະໝ່ຳສະເໝີ, ຫຼີກລ່ຽງແສງສະທ້ອນຈາກແວ່ນຕາ, ຖືກ້ອງໃຫ້ນິ່ງ ແລ້ວຖ່າຍໃໝ່.", "We couldn't confirm a live face. If you're using your real camera, this is usually lighting or background — avoid a bright window/light behind you, move to an evenly lit spot, remove glare from glasses, hold steady, and capture again.");
  }
  if (codes.includes("SELFIE_LOW_RESOLUTION") || codes.includes("SELFIE_BLUR_DETECTED")) {
    return L("ຮູບເຊວຟີມົວ ຫຼື ຄວາມລະອຽດຕ່ຳເກີນໄປ. ເຂົ້າມາໃກ້ກ້ອງ ແລ້ວຖ່າຍໃໝ່.", "Selfie is too blurry or low resolution. Move closer and capture again.");
  }
  if (codes.includes("FACE_NOT_CENTERED") || codes.includes("FACE_CENTER_WEAK")) {
    return L("ກະລຸນາໃຫ້ໃບໜ້າຢູ່ກາງວົງມົນ ແລ້ວລອງໃໝ່.", "Please center your face in the oval and try again.");
  }
  return L("ກະລຸນາຖ່າຍເຊວຟີທີ່ຊັດເຈນກວ່າເກົ່າ ແລ້ວລອງໃໝ່.", "Please capture a clearer live selfie and try again.");
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
  if (step === "liveness") return L("ກະລຸນາອັບໂຫຼດເອກະສານຢັ້ງຢືນຕົວຕົນທີ່ຜ່ານການກວດກ່ອນ.", "Upload an accepted identity document first.");
  if (step === "gesture") return L("ກະລຸນາເຮັດຂັ້ນຕອນກວດໃບໜ້າຈິງໃຫ້ສຳເລັດກ່ອນ.", "Complete active face liveness first.");
  if (step === "selfie") return L("ກະລຸນາເຮັດຂັ້ນຕອນທ່າທາງມືໃຫ້ສຳເລັດກ່ອນ.", "Complete the hand gesture challenge first.");
  if (step === "result") return L("ກະລຸນາຖ່າຍເຊວຟີໃຫ້ສຳເລັດກ່ອນ.", "Complete selfie and passive liveness first.");
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
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
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
    if (error) showToast("error", L("ມີບາງຢ່າງຕ້ອງກວດສອບ", "Something needs attention"), error);
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
    if (result?.decision === "passed") showToast("success", L("ຢັ້ງຢືນຜ່ານແລ້ວ", "Verification passed"), L("ຜ່ານການກວດທຸກຂັ້ນຕອນ — ຢັ້ງຢືນຕົວຕົນສຳເລັດ.", "All checks passed — you're verified."));
    else if (result?.decision === "rejected") showToast("error", L("ການຢັ້ງຢືນບໍ່ຜ່ານ", "Verification rejected"), L("ມີການກວດບາງຂັ້ນຕອນບໍ່ຜ່ານ. ເບິ່ງລະຫັດເຫດຜົນຂ້າງລຸ່ມ.", "One or more checks failed. See the reason codes below."));
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

  const sync = async (task: () => Promise<VerificationResult>, message: string, next?: StepKey): Promise<boolean> => {
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
        setStatusMessage(L(`${documentLabels[documentType].title} ບໍ່ຜ່ານ. ກະລຸນາອັບໂຫຼດຮູບເອກະສານທີ່ຊັດເຈນ ແລະ ຖືກຕ້ອງ.`, `${documentLabels[documentType].title} rejected. Please upload a clearer or valid document image.`));
      }
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : L("ເກີດຂໍ້ຜິດພາດ.", "Something went wrong."));
      return false;
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
      if (nextResult.watchlist_blocked) {
        // Highest-severity outcome: a government watchlist match. Halt here — do
        // not advance to liveness — and let the blocking banner take over.
        setStatusMessage(L("ກົງກັບບັນຊີເຝົ້າລະວັງ — ຢຸດການຢັ້ງຢືນ. ກະລຸນາສົ່ງຕໍ່ໃຫ້ເຈົ້າໜ້າທີ່.", "Watchlist match — verification halted. Refer to an officer."));
        setActiveStep("document");
        return;
      }
      if (nextResult.document.status === "passed") {
        setStatusMessage(successMessage);
        setDocumentNotice({
          type: "success",
          title: L(`${documentLabels[documentType].title} ຜ່ານການກວດ`, `${documentLabels[documentType].title} accepted`),
          message: documentType === "passport" ? L("ຜ່ານການກວດຄຸນນະພາບເອກະສານ, OCR/MRZ ແລະ ການປອມແປງ.", "Document quality, OCR/MRZ, and fraud checks passed.") : L("ຜ່ານການກວດຄຸນນະພາບເອກະສານ, ຂໍ້ມູນ OCR ແລະ ການປອມແປງ.", "Document quality, OCR fields, and fraud checks passed."),
          codes: ["DOCUMENT_PASSED"]
        });
        setActiveStep("document");
        window.setTimeout(() => {
          setActiveStep("liveness");
        }, 900);
      } else {
        const codes = nextResult.document.signals.map((signal) => signal.code);
        const mrzRetakeRequired = codes.includes("MRZ_NOT_CONFIDENT") || codes.includes("MRZ_NOT_READ");
        const rejectionMessage = codes.includes("DOCUMENT_MIRRORED")
          ? L("ເອກະສານເບິ່ງຄືຖືກກັບດ້ານ — ຕົວໜັງສືອ່ານປີ້ນ. ຖ້າທ່ານໃຊ້ກ້ອງໜ້າ (ເຊວຟີ) ຮູບຈະຖືກກັບດ້ານ: ກະລຸນາໃຊ້ກ້ອງຫຼັງ ຫຼື ຫັນໜ້າທີ່ມີຮູບເຂົ້າຫາກ້ອງ ແລ້ວຖ່າຍໃໝ່.", "The document looks mirrored or reversed — its text reads backwards. If you used a front (selfie) camera, it flips the image: use the rear camera or hold the photo page facing the camera, then retake.")
          : mrzRetakeRequired
            ? L("ບໍ່ສາມາດກວດສອບ MRZ ໄດ້. ກະລຸນາຖ່າຍຮູບໜັງສືຜ່ານແດນໃໝ່ ໃຫ້ເຫັນແຖວ MRZ ທັງສອງແຖວຄົບ ແລະ ຊັດເຈນ ໂດຍມີຊ່ອງວ່າງລຸ່ມໜ້າເອກະສານ.", "The MRZ could not be validated. Retake the passport photo with both MRZ lines fully visible, sharp, and with space below the page.")
            : L(`ກະລຸນາອັບໂຫຼດຮູບ${documentLabels[documentType].upload}ທີ່ຊັດເຈນ ແລະ ຖືກຕ້ອງ ແລ້ວລອງໃໝ່.`, `Please upload a clearer, valid ${documentLabels[documentType].upload} image and try again.`);
        setActiveStep("document");
        setStatusMessage(L(`${documentLabels[documentType].title} ບໍ່ຜ່ານ. ${rejectionMessage}`, `${documentLabels[documentType].title} rejected. ${rejectionMessage}`));
        setDocumentNotice({
          type: "failure",
          title: L(`${documentLabels[documentType].title} ບໍ່ຜ່ານ`, `${documentLabels[documentType].title} rejected`),
          message: rejectionMessage,
          codes: codes.length ? codes : ["DOCUMENT_REJECTED"]
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : L("ເກີດຂໍ້ຜິດພາດ.", "Something went wrong."));
      setDocumentNotice({
        type: "failure",
        title: L("ອັບໂຫຼດບໍ່ສຳເລັດ", "Upload failed"),
        message: L("ບໍ່ສາມາດວິເຄາະເອກະສານໄດ້. ກະລຸນາລອງໃໝ່.", "The document could not be analyzed. Please try again."),
        codes: ["DOCUMENT_UPLOAD_FAILED"]
      });
    } finally {
      setBusy(false);
      setDocumentBusy(false);
    }
  };

  useEffect(() => {
    if (screen === "verify" && !result && normalizedUserId) {
      sync(() => api.createSession(normalizedUserId), L("ພ້ອມເລີ່ມການຢັ້ງຢືນ", "Session ready"));
    }
  }, [screen, result, normalizedUserId]);

  const uploadDocument = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!sessionId) {
      setError(L("ກຳລັງເຊື່ອມຕໍ່ການຢັ້ງຢືນ. ກະລຸນາລໍຖ້າຈັກໜ້ອຍ ແລ້ວອັບໂຫຼດອີກຄັ້ງ.", "Verification session is still connecting. Please wait a moment and upload again."));
      event.target.value = "";
      return;
    }
    uploadAndAnalyzeDocument(
      async () => api.uploadDocument(
        sessionId,
        file,
        documentType
      ),
      L(`ວິເຄາະ${documentLabels[documentType].title}ແລ້ວ`, `${documentLabels[documentType].title} analyzed`)
    ).finally(() => {
      event.target.value = "";
    });
  };

  const captureDocument = (blob: Blob) => {
    if (!sessionId) {
      setError(L("ກຳລັງເຊື່ອມຕໍ່ການຢັ້ງຢືນ. ກະລຸນາລໍຖ້າຈັກໜ້ອຍ ແລ້ວຖ່າຍອີກຄັ້ງ.", "Verification session is still connecting. Please wait a moment and capture again."));
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
      L(`ວິເຄາະຮູບ${documentLabels[documentType].title}ແລ້ວ`, `${documentLabels[documentType].title} capture analyzed`)
    );
  };

  const completeChallenge = async (challenge: Challenge, next?: StepKey, frames?: Blob[]): Promise<boolean> => {
    if (!sessionId) return false;
    // The gesture step can now be rejected (e.g. the face in the gesture frames
    // does not match the document portrait), so the caller needs the outcome to
    // release its retry lock instead of leaving the user stuck.
    return sync(
      () => api.completeChallenge(sessionId, challenge.id, challenge.nonce, true, frames),
      L(`${challengePrompt(challenge)} — ຢືນຢັນແລ້ວ`, `${challenge.prompt} confirmed`),
      next
    );
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
        setStatusMessage(L(`${challengePrompt(challenge)} — ຜ່ານການກວດໃບໜ້າຈິງ`, `${challenge.prompt} confirmed with live-face check`));
        if (allDone && canAccessStep("gesture", nextResult)) {
          setActiveStep("gesture");
        }
        return true;
      }

      const codes = nextResult.biometric.active_liveness_signals.map((signal) => signal.code);
      if (codes.includes("ACTIVE_LIVENESS_FACE_TOO_SMALL")) {
        const guidance = L("ໃບໜ້າຂອງທ່ານຢູ່ໄກກ້ອງເກີນໄປ. ເຂົ້າມາໃກ້ຈົນໃບໜ້າກວມປະມານໜຶ່ງສ່ວນສາມຂອງໜ້າຈໍ, ໃຫ້ເຫັນໃບໜ້າທັງໝົດ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "Your face is too far from the camera. Move closer until your face fills about one-third of the screen, keep your full face visible, then repeat the action.");
        setStatusMessage(L("ເຂົ້າມາໃກ້ກ້ອງອີກໜ້ອຍໜຶ່ງ.", "Move closer for a clearer live-face check."));
        setError(guidance);
        return guidance;
      }
      if (codes.includes("ACTIVE_LIVENESS_FACE_NOT_FOUND")) {
        const guidance = L("ບໍ່ສາມາດກວດພົບໃບໜ້າໄດ້ຊັດເຈນ. ໃຫ້ໃບໜ້າຢູ່ກາງ, ເຂົ້າມາໃກ້ອີກໜ້ອຍ, ເອົາສິ່ງທີ່ບັງອອກ ແລ້ວລອງໃໝ່.", "We could not clearly detect your face. Center your full face, move slightly closer, remove any obstruction, and try again.");
        setStatusMessage(L("ໃຫ້ໃບໜ້າຢູ່ກາງ ແລ້ວລອງໃໝ່.", "Center your face and retry."));
        setError(guidance);
        return guidance;
      }
      if (codes.includes("ACTIVE_LIVENESS_FACE_CONFIDENCE_LOW")) {
        const guidance = L("ໃບໜ້າບໍ່ຊັດພໍທີ່ຈະກວດສອບ. ເຂົ້າມາໃກ້, ເຊັດເລນກ້ອງ, ຫັນໜ້າເຂົ້າຫາແສງອ່ອນໆ ແລະ ຢູ່ນິ່ງໆຂະນະເຮັດທ່າ.", "Your face was not clear enough to verify. Move closer, clean the camera lens, face soft even light, and hold still while repeating the action.");
        setStatusMessage(L("ປັບໃຫ້ໃບໜ້າຊັດເຈນ ແລ້ວລອງໃໝ່.", "Improve face clarity and retry."));
        setError(guidance);
        return guidance;
      }
      if (codes.includes("ACTIVE_LIVENESS_MULTIPLE_FACES")) {
        const guidance = L("ກວດພົບໃບໜ້າຫຼາຍກວ່າໜຶ່ງຄົນ. ໃຫ້ມີພຽງແຕ່ທ່ານຢູ່ໃນກ້ອງ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "More than one face was detected. Make sure only you are visible, then repeat the action.");
        setStatusMessage(L("ໃຫ້ມີໃບໜ້າພຽງຄົນດຽວ.", "Only one face can be visible."));
        setError(guidance);
        return guidance;
      }
      // Checked after the quality codes above: a blurry or tiny face produces a
      // weak embedding, so quality guidance is the more useful message. Only
      // when the face was captured clearly do we report an identity mismatch.
      if (codes.includes("ACTIVE_LIVENESS_FACE_MISMATCH")) {
        const guidance = L("ໃບໜ້ານີ້ບໍ່ກົງກັບຮູບໃນເອກະສານທີ່ອັບໂຫຼດ. ຕ້ອງເປັນຄົນດຽວກັນທຸກຂັ້ນຕອນ — ກວດໃຫ້ແນ່ໃຈວ່າອັບໂຫຼດເອກະສານຂອງທ່ານເອງ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "This face does not match the portrait in the uploaded document. The same person must complete every step — check that you uploaded your own document, then repeat the action.");
        setStatusMessage(L("ໃບໜ້າບໍ່ກົງກັບຮູບໃນເອກະສານ.", "Face does not match the document portrait."));
        setError(guidance);
        return guidance;
      }
      if (codes.includes("ACTIVE_LIVENESS_REPLAY_DETECTED")) {
        const guidance = L("ການກວດພົບສັນຍານຄ້າຍໜ້າຈໍ ຫຼື ວິດີໂອທີ່ບັນທຶກໄວ້. ຖ້ານີ້ແມ່ນໃບໜ້າຈິງຂອງທ່ານ, ເຂົ້າມາໃກ້, ຫຼີກລ່ຽງປ່ອງຢ້ຽມ ຫຼື ແສງສະທ້ອນຈາກໜ້າຈໍ, ໃຊ້ແສງອ່ອນໆທີ່ສະໝ່ຳສະເໝີ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "The live-face check found screen-like or replay signals. If this is your real face, move closer, avoid a bright window or screen reflection, use soft even lighting, and repeat the action.");
        setStatusMessage(L("ກະລຸນາລອງກວດໃບໜ້າຈິງໃໝ່.", "Active liveness needs a clean live-face retry."));
        setError(guidance);
        return guidance;
      } else {
        const guidance = L("ການກວດໃບໜ້າຈິງບໍ່ຊັດເຈນພໍ. ເຂົ້າມາໃກ້, ໃຫ້ໃບໜ້າຢູ່ກາງ, ໃຊ້ແສງທີ່ສະໝ່ຳສະເໝີ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "Live-face verification was not clear enough. Move closer, center your full face, use even lighting, and repeat the action.");
        setStatusMessage(L("ກະລຸນາລອງໃໝ່ໃຫ້ຊັດເຈນກວ່າເກົ່າ.", "Active liveness needs a clearer retry."));
        setError(guidance);
        return guidance;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : L("ບໍ່ສາມາດກວດໃບໜ້າຈິງໄດ້.", "Active liveness could not be verified."));
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
        setStatusMessage(L("ວິເຄາະເຊວຟີແລ້ວ", "Selfie and passive liveness analyzed"));
        setSelfieNotice({
          type: "success",
          title: L("ເຊວຟີຜ່ານແລ້ວ", "Selfie accepted"),
          message: L("ຜ່ານການກວດຄຸນນະພາບເຊວຟີ ແລະ ໃບໜ້າຈິງ.", "Selfie quality and passive liveness checks passed."),
          codes: ["SELFIE_PASSED"]
        });
        window.setTimeout(() => setActiveStep("result"), 700);
      } else {
        const codes = nextResult.biometric.selfie_signals.map((signal) => signal.code);
        const message = selfieFailureMessage(codes, nextResult.biometric.face_match_score);
        setStatusMessage(L(`ເຊວຟີບໍ່ຜ່ານ. ${message}`, `Selfie rejected. ${message}`));
        setSelfieNotice({
          type: "failure",
          title: L("ເຊວຟີບໍ່ຜ່ານ", "Selfie rejected"),
          message,
          codes: codes.length ? codes : ["SELFIE_REJECTED"]
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : L("ເກີດຂໍ້ຜິດພາດ.", "Something went wrong."));
      setSelfieNotice({
        type: "failure",
        title: L("ອັບໂຫຼດເຊວຟີບໍ່ສຳເລັດ", "Selfie upload failed"),
        message: L("ບໍ່ສາມາດວິເຄາະເຊວຟີໄດ້. ກະລຸນາລອງໃໝ່.", "The selfie could not be analyzed. Please try again."),
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
        title: L("ລົງທະບຽນ Face ID ແລ້ວ", "Face ID enrolled"),
        message: L("ໂປຣໄຟລ໌ນີ້ສາມາດເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າໄດ້ແລ້ວ.", "This verified profile can now use returning face login."),
        codes: ["FACE_ID_ENROLLED"],
        profile: response.profile
      });
    } catch (err) {
      setEnrollmentNotice({
        type: "failure",
        title: L("ລົງທະບຽນໃບໜ້າບໍ່ສຳເລັດ", "Face enrollment failed"),
        message: err instanceof Error ? err.message : L("ບໍ່ສາມາດລົງທະບຽນ Face ID ໄດ້.", "The face ID could not be enrolled."),
        codes: ["FACE_ID_ENROLLMENT_FAILED"]
      });
    } finally {
      setEnrollBusy(false);
    }
  };

  const faceLogin = async (capture: Blob | Blob[]) => {
    try {
      setFaceLoginBusy(true);
      setFaceLoginResult(null);
      const response = await api.faceLogin(capture);
      setFaceLoginResult(response);
    } catch (err) {
      setFaceLoginResult({
        decision: "rejected",
        matched: false,
        match_score: 0,
        passive_liveness_risk: 1,
        reason_codes: ["FACE_LOGIN_FAILED"],
        profile: null,
        checks: { error: err instanceof Error ? err.message : L("ເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າບໍ່ສຳເລັດ.", "Face login failed.") },
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
        setManageResult({ kind: "export-ok", message: L("ຢືນຢັນໃບໜ້າແລ້ວ — ດາວໂຫຼດຂໍ້ມູນຂອງທ່ານເປັນໄຟລ໌ JSON ແລ້ວ.", "Face verified — your data has been downloaded as a JSON file.") });
      } else {
        setManageResult({ kind: "error", message: `${L("ບໍ່ສາມາດຢືນຢັນໃບໜ້າຂອງທ່ານໄດ້", "Could not verify your face")}${res.reason_codes.length ? ` (${res.reason_codes.join(", ")})` : ""}.` });
      }
    } catch (err) {
      setManageResult({ kind: "error", message: err instanceof Error ? err.message : L("ສົ່ງອອກຂໍ້ມູນບໍ່ສຳເລັດ.", "Export failed.") });
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
        setManageResult({ kind: "delete-ok", message: L("ຢືນຢັນໃບໜ້າແລ້ວ — ລຶບຂໍ້ມູນຂອງທ່ານຖາວອນແລ້ວ.", "Face verified — your enrolled data has been permanently deleted.") });
      } else if (res.verified) {
        setManageResult({ kind: "error", message: L("ຢືນຢັນແລ້ວ ແຕ່ບໍ່ພົບຂໍ້ມູນທີ່ລົງທະບຽນໄວ້ເພື່ອລຶບ.", "Verified, but no enrolled data was found to delete.") });
      } else {
        setManageResult({ kind: "error", message: `${L("ບໍ່ສາມາດຢືນຢັນໃບໜ້າຂອງທ່ານໄດ້", "Could not verify your face")}${res.reason_codes.length ? ` (${res.reason_codes.join(", ")})` : ""}.` });
      }
    } catch (err) {
      setManageResult({ kind: "error", message: err instanceof Error ? err.message : L("ລຶບຂໍ້ມູນບໍ່ສຳເລັດ.", "Deletion failed.") });
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
        onManageData={() => setScreen("manage-data")}
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
        <button className="kyron-wordmark sidebar-wordmark" type="button" onClick={() => setScreen("intro")} aria-label={L("ກັບໄປໜ້າຫຼັກ Kyron", "Back to Kyron home")}>
          <KyronWordmark />
        </button>
        <div className="assurance-card">
          <ShieldCheck size={22} />
          <div>
            <span>{L("ການຢັ້ງຢືນຂອງທ່ານ", "Your verification")}</span>
            <strong>{L("ຢັ້ງຢືນດ້ວຍ", "")}{documentLabels[documentType].title}{L("", " proofing")}</strong>
          </div>
        </div>
        <nav className="step-list" aria-label={L("ຂັ້ນຕອນການຢັ້ງຢືນ", "Verification steps")}>
          {steps.map((step, index) => {
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
                aria-current={isActive ? "step" : undefined}
              >
                <span className="step-icon">{isDone ? <Check size={15} /> : index + 1}</span>
                <span>{step.key === "document" ? documentLabels[documentType].short : step.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer"><LockKeyhole size={16} /><span>{L("ເຮັດແຕ່ລະຂັ້ນຕອນຕາມລຳດັບ.", "Complete each step in order.")}<br />{L("ຢ່າປິດໜ້າຕ່າງນີ້.", "Keep this window open.")}</span></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{L("ການຢັ້ງຢືນຕົວຕົນ", "Identity verification")}</p>
            <h1>{L("ຢັ້ງຢືນຕົວຕົນຂອງທ່ານ", "Verify your identity")}</h1>
            {result?.user_id && <span className="user-id-pill">{L("ລະຫັດຜູ້ໃຊ້: ", "User ID: ")}{result.user_id}</span>}
          </div>
          <div className="topbar-actions">
            <LanguageSwitch />
            <div className={`decision-pill decision-${result?.decision ?? "pending"}`}>
              {statusLabel(result?.decision ?? "pending")}
            </div>
          </div>
        </header>

        <DemoWarning compact />

        <div className="progress-track" aria-label={L("ຄວາມຄືບໜ້າການຢັ້ງຢືນ", "Verification progress")}>
          <span style={{ width: `${progress * 100}%` }} />
        </div>

        <div className="content-grid">
          <section className="work-panel">
            <div className="panel-header">
              <span>{statusMessage ?? L("ກຳລັງເລີ່ມການຢັ້ງຢືນ", "Starting verification session")}</span>
              {busy && <span className="loading-dot" aria-live="polite">{L("ກຳລັງດຳເນີນການ", "Processing")}</span>}
            </div>
            {documentBusy && <DocumentUploadOverlay documentType={documentType} />}
            {result?.watchlist_blocked ? (
              <WatchlistBlock />
            ) : (
              <>
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
                    onComplete={(challenge, allDone, frames) => completeChallenge(challenge, allDone ? "selfie" : undefined, frames)}
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
              </>
            )}
          </section>

          <aside className="risk-panel">
            <h2>{L("ສະຫຼຸບການຢັ້ງຢືນ", "Verification summary")}</h2>
            <Metric label={L("ຄຸນນະພາບເອກະສານ", "Document quality")} value={result?.document.image_quality_score ?? 0} />
            <Metric label={L("ຄວາມສ່ຽງເອກະສານປອມ", "Document fraud risk")} value={result?.document.fraud_risk_score ?? 0} inverse />
            <Metric label={L("ການທຽບໃບໜ້າ", "Face match")} value={result?.biometric.face_match_score ?? 0} />
            <Metric label={L("ຄວາມສ່ຽງໃບໜ້າປອມ", "Passive risk")} value={result?.biometric.passive_liveness_risk ?? 1} inverse />
            <Metric label={L("ຄຸນນະພາບເຊວຟີ", "Selfie quality")} value={result?.biometric.selfie_quality_score ?? 0} />
            <div className="reason-list">
              <span>{L("ລະຫັດເຫດຜົນ", "Reason codes")}</span>
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
    <div className="document-upload-overlay" role="status" aria-live="polite" aria-label={L(`ກຳລັງວິເຄາະ${label.upload}`, `Analyzing ${label.upload} document`)}>
      <div className="scanner-card">
        <div className="scanner-frame">
          <FileImage size={38} />
          <span className="scanner-line" />
        </div>
        <div>
          <strong>{L("ກຳລັງວິເຄາະ", "Analyzing ")}{label.upload}</strong>
          <p>{documentType === "passport" ? L("ກຳລັງກວດ OCR, MRZ, ຄຸນນະພາບເອກະສານ ແລະ ສັນຍານການປອມແປງ.", "Checking OCR, MRZ, document quality, and fraud signals.") : L("ກຳລັງກວດຂໍ້ມູນ OCR, ຄຸນນະພາບເອກະສານ ແລະ ສັນຍານການປອມແປງ.", "Checking OCR fields, document quality, and fraud signals.")}</p>
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
  userId, onUserIdChange, onGenerateUserId, onStart, onFaceLogin, onManageData
}: {
  userId: string;
  onUserIdChange: (value: string) => void;
  onGenerateUserId: () => void;
  onStart: () => void;
  onFaceLogin: () => void;
  onManageData: () => void;
}) {
  return (
    <main className="welcome-shell">
      <header className="welcome-header">
        <a className="kyron-wordmark" href="#" aria-label={L("ໜ້າຫຼັກ Kyron", "Kyron home")}>
          <KyronWordmark />
        </a>
        <span className="header-product">{L("ການຢັ້ງຢືນຕົວຕົນ", "Identity verification")}</span>
        <LanguageSwitch />
        <a className="operator-link" href="#admin">{L("ສຳລັບເຈົ້າໜ້າທີ່ ", "Operator console ")}<ArrowRight size={15} /></a>
      </header>

      <div className="welcome-layout">
        <section className="welcome-main" aria-labelledby="intro-title">
          <h1 id="intro-title">{L("ຢັ້ງຢືນຕົວຕົນຂອງທ່ານ", "Verify your identity")}</h1>
          <p className="welcome-description">{L("ທ່ານຕ້ອງມີໜັງສືຜ່ານແດນ ຫຼື ບັດປະຈຳຕົວລາວ ແລະ ອຸປະກອນທີ່ມີກ້ອງ. ໃຊ້ເວລາພຽງບໍ່ເທົ່າໃດນາທີ.", "You’ll need your passport or Lao ID card and a device with a camera. It takes a few minutes.")}</p>

          <form className="enrollment-form" onSubmit={(event) => {
            event.preventDefault();
            if (!userId.trim()) onGenerateUserId();
            onStart();
          }}>
            <div className="form-heading"><h2>{L("ເລີ່ມການຢັ້ງຢືນໃໝ່", "Start a new verification")}</h2></div>
            <label className="user-id-field" htmlFor="verification-user-id">
              <span>{L("ລະຫັດອ້າງອີງຜູ້ໃຊ້ ", "User reference ")}<small>{L("ບໍ່ບັງຄັບ", "Optional")}</small></span>
              <input id="verification-user-id" value={userId} onChange={(event) => onUserIdChange(event.target.value)} placeholder={L("ເຊັ່ນ: ລະຫັດລູກຄ້າ", "e.g. customer ID")} autoComplete="off" aria-describedby="reference-hint" />
            </label>
            <p id="reference-hint" className="field-hint">{L("ຖ້າປ່ອຍວ່າງ ລະບົບຈະສ້າງລະຫັດທົດລອງໃຫ້ທ່ານ.", "Leave blank and we’ll create a demo reference for you.")}</p>
            <button className="primary-button welcome-start" type="submit">{L("ເລີ່ມການຢັ້ງຢືນ ", "Begin verification ")}<ArrowRight size={18} /></button>
          </form>
          <div className="returning-user"><div><strong>{L("ເຄີຍຢັ້ງຢືນແລ້ວບໍ?", "Already verified?")}</strong><span>{L("ເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າທີ່ລົງທະບຽນໄວ້.", "Sign in with your enrolled face.")}</span></div><button type="button" onClick={onFaceLogin}>{L("ເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າ ", "Face login ")}<ArrowRight size={16} /></button></div>
          <DemoWarning compact />
        </section>

        <aside className="welcome-guide" aria-label={L("ຂັ້ນຕອນການເຮັດວຽກ", "How it works")}>
          <h2>{L("ຂັ້ນຕອນການເຮັດວຽກ", "How it works")}</h2>
          <p>{L("ຊອກບ່ອນທີ່ມີແສງສະຫວ່າງພຽງພໍ ແລະ ໃຫ້ເຫັນໃບໜ້າ ແລະ ເອກະສານຢ່າງຊັດເຈນ.", "Find a well-lit spot and keep your face and document in view.")}</p>
          <ol className="preparation-list">
            <li><span>1</span><div><strong>{L("ສະແກນເອກະສານ", "Scan your document")}</strong><p>{L("ໜັງສືຜ່ານແດນ ຫຼື ບັດປະຈຳຕົວລາວ ໃຫ້ເຫັນທຸກມຸມ ແລະ ລາຍລະອຽດຄົບຖ້ວນ.", "Passport or Lao ID card, with every corner and detail visible.")}</p></div></li>
            <li><span>2</span><div><strong>{L("ເຮັດຕາມຄຳແນະນຳໃນກ້ອງ", "Follow the camera prompts")}</strong><p>{L("ເຄື່ອນໄຫວຫົວ ແລະ ເຮັດທ່າທາງມືບາງທ່າ ເພື່ອຢືນຢັນວ່າແມ່ນທ່ານແທ້.", "A few head movements and hand gestures confirm you’re present.")}</p></div></li>
            <li><span>3</span><div><strong>{L("ຖ່າຍເຊວຟີ", "Take a selfie")}</strong><p>{L("ລະບົບຈະທຽບກັບຮູບໃນເອກະສານຂອງທ່ານ.", "We compare it with the photo on your document.")}</p></div></li>
          </ol>
          <div className="guide-footnote"><Camera size={16} /><span>{L("ບຣາວເຊີຈະຂໍອະນຸຍາດໃຊ້ກ້ອງ.", "Your browser will ask for camera access.")}</span></div>
        </aside>
      </div>
      <footer className="welcome-footer"><span>{L("© Kyron ບໍລິການຢັ້ງຢືນຕົວຕົນ", "© Kyron identity services")}</span><button type="button" onClick={onManageData}>{L("ຈັດການຂໍ້ມູນຂອງຂ້ອຍ ", "Manage my data ")}<ArrowRight size={14} /></button><span className="demo-label">{L("ລະບົບທົດລອງ", "Demo environment")}</span></footer>
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
  onCapture: (capture: Blob | Blob[]) => void;
  onBack: () => void;
}) {
  const passed = result?.decision === "passed";
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="face-login-title">
        <div className="panel-toolbar">
          <button className="secondary-button back-button" type="button" onClick={onBack}>
            <ArrowLeft size={18} />
  {L("ກັບຄືນ", "Back")}
          </button>
          <LanguageSwitch />
        </div>
        <div className="login-copy">
          <span className="kyron-wordmark"><KyronWordmark /></span>
          <p className="eyebrow">{L("ຜູ້ໃຊ້ເກົ່າ", "Returning user")}</p>
          <h1 id="face-login-title">{L("ເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າ", "Face login")}</h1>
          <p>
{L("ຖ່າຍໃບໜ້າແບບສົດ. ລະບົບຈະກວດວ່າເປັນໃບໜ້າຈິງ, ທຽບກັບ Face ID ທີ່ລົງທະບຽນໄວ້ ແລະ ສະແດງໂປຣໄຟລ໌ທີ່ຢັ້ງຢືນແລ້ວເມື່ອທຽບຜ່ານ.", "Capture a live face. The system checks passive liveness, matches it against enrolled Face IDs, and loads the verified profile when the match passes.")}
          </p>
          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
{L("ກຳລັງກວດໃບໜ້າ", "Checking face login")}
            </div>
          )}
          {result && (
            <div className={`document-notice document-notice-${passed ? "success" : "failure"}`} role="status">
              {passed ? <UserCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>{passed ? L("ເຂົ້າສູ່ລະບົບສຳເລັດ", "Face login passed") : L("ເຂົ້າສູ່ລະບົບບໍ່ຜ່ານ", "Face login rejected")}</strong>
                <p>
                  {passed
                    ? `${L("ຍິນດີຕ້ອນຮັບ", "Welcome")}${result.profile?.first_name ? `, ${result.profile.first_name}` : ""}.`
                    : L("ບໍ່ພົບໃບໜ້າທີ່ກົງກັບຂໍ້ມູນທີ່ຢັ້ງຢືນແລ້ວ.", "No verified live face match was found.")}
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
          label={L("ເຂົ້າສູ່ລະບົບດ້ວຍໃບໜ້າ", "Returning user face login")}
          overlay="face"
          onCapture={onCapture}
          onCaptureFrames={onCapture}
          maxCaptureWidth={720}
          jpegQuality={0.84}
          burstCount={6}
          burstIntervalMs={220}
          captureLabel={L("ຖ່າຍຮູບຕໍ່ເນື່ອງ", "Capture live burst")}
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
        <div className="panel-toolbar">
          <button className="secondary-button back-button" type="button" onClick={onBack}>
            <ArrowLeft size={18} />
  {L("ກັບຄືນ", "Back")}
          </button>
          <LanguageSwitch />
        </div>
        <div className="login-copy">
          <span className="kyron-wordmark"><KyronWordmark /></span>
          <p className="eyebrow">{L("ສິດໃນຂໍ້ມູນຂອງທ່ານ", "Your data rights")}</p>
          <h1 id="manage-title">{L("ຈັດການຂໍ້ມູນຂອງຂ້ອຍ", "Manage my data")}</h1>
          <p>
{L("ຢືນຢັນດ້ວຍເຊວຟີແບບສົດ ເພື່ອສົ່ງອອກສຳເນົາຂໍ້ມູນທີ່ລົງທະບຽນໄວ້ ຫຼື ລຶບຂໍ້ມູນຖາວອນ. ໃບໜ້າຂອງທ່ານຢືນຢັນວ່າແມ່ນທ່ານ — ບໍ່ມີໃຜອື່ນ ເຂົ້າເຖິງຂໍ້ມູນຂອງທ່ານໄດ້.", "Verify with a live selfie to export a copy of your enrolled data, or permanently delete it. Your face proves it’s you — no one else can access your record.")}
          </p>

          {!action && (
            <div className="intro-actions">
              <button className="primary-button intro-start" type="button" onClick={() => setAction("export")}>
                <Download size={18} />
{L("ສົ່ງອອກຂໍ້ມູນ", "Export my data")}
              </button>
              <button className="secondary-button intro-start" type="button" onClick={() => setAction("delete")}>
                <Trash2 size={18} />
{L("ລຶບຂໍ້ມູນ", "Delete my data")}
              </button>
            </div>
          )}

          {action && (
            <>
              <div className={`manage-action-banner manage-action-${action}`}>
                {action === "export" ? <Download size={16} /> : <ShieldAlert size={16} />}
                <span>
                  {action === "export"
                    ? L("ຖ່າຍເຊວຟີແບບສົດເພື່ອດາວໂຫຼດຂໍ້ມູນຂອງທ່ານ.", "Capture a live selfie to download your data.")
                    : L("ຖ່າຍເຊວຟີແບບສົດເພື່ອລຶບຂໍ້ມູນຖາວອນ. ບໍ່ສາມາດກູ້ຄືນໄດ້.", "Capture a live selfie to permanently delete your data. This cannot be undone.")}
                </span>
              </div>
              <button className="text-action-button" type="button" onClick={() => setAction(null)}>
{L("ເລືອກການດຳເນີນການອື່ນ", "Choose a different action")}
              </button>
            </>
          )}

          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
              {action === "delete" ? L("ກຳລັງຢືນຢັນ ແລະ ລຶບ", "Verifying and deleting") : L("ກຳລັງຢືນຢັນ ແລະ ສົ່ງອອກ", "Verifying and exporting")}
            </div>
          )}

          {result && (
            <div className={`document-notice document-notice-${ok ? "success" : "failure"}`} role="status">
              {ok ? <UserCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>
                  {result.kind === "export-ok"
                    ? L("ສົ່ງອອກຂໍ້ມູນແລ້ວ", "Data exported")
                    : result.kind === "delete-ok"
                      ? L("ລຶບຂໍ້ມູນແລ້ວ", "Data deleted")
                      : L("ຢືນຢັນບໍ່ຜ່ານ", "Not verified")}
                </strong>
                <p>{result.message}</p>
              </div>
            </div>
          )}
        </div>
        {action && (
          <CameraCapture
            label={action === "export" ? L("ເຊວຟີເພື່ອສົ່ງອອກຂໍ້ມູນ", "Selfie to export your data") : L("ເຊວຟີເພື່ອລຶບຂໍ້ມູນ", "Selfie to delete your data")}
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
        <div className="panel-toolbar">
          <button className="secondary-button back-button" type="button" onClick={onBack}>
            <ArrowLeft size={18} />
  {L("ກັບຄືນ", "Back")}
          </button>
          <LanguageSwitch />
        </div>
        <div className="payment-copy">
          <span className="kyron-wordmark"><KyronWordmark /></span>
          <p className="eyebrow">{L("ອະນຸມັດການໂອນເງິນ", "Bank transfer authorization")}</p>
          <h1 id="payment-title">{L("ໂອນເງິນດ້ວຍ Face ID", "Transfer with Face ID")}</h1>
          <p className="payment-note">{L("ໂໝດທົດລອງ: ບໍ່ມີການໂອນເງິນແທ້. ທຸກການໂອນຕ້ອງໃຊ້ Face ID ທີ່ລົງທະບຽນແລ້ວ.", "Demo mode: no real money moves. Each transfer requires an enrolled live Face ID.")}</p>

          <div className="payment-card" aria-label={L("ລາຍລະອຽດການໂອນ", "Transfer details")}>
            <label>
              <span>{L("ຜູ້ຮັບ", "Recipient")}</span>
              <input value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder={L("ຊື່ ຫຼື ເລກບັນຊີ", "Account name or number")} />
            </label>
            <div className="payment-amount-grid">
              <label>
                <span>{L("ຈຳນວນເງິນ", "Amount")}</span>
                <input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0" />
              </label>
              <label>
                <span>{L("ສະກຸນເງິນ", "Currency")}</span>
                <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
                  <option>LAK</option>
                  <option>USD</option>
                  <option>THB</option>
                </select>
              </label>
            </div>
            <label>
              <span>{L("ໝາຍເຫດ", "Note")}</span>
              <input value={note} onChange={(event) => setNote(event.target.value)} placeholder={L("ບໍ່ບັງຄັບ", "Optional")} />
            </label>
          </div>

          <div className="payment-security-row">
            <div><LockKeyhole size={18} /><span>{L("ຕ້ອງໃຊ້ Face ID", "Face ID required")}</span></div>
            <div><Landmark size={18} /><span>{L("ສະເພາະໂປຣໄຟລ໌ທີ່ຢັ້ງຢືນແລ້ວ", "Verified profile only")}</span></div>
            <div><ReceiptText size={18} /><span>{L("ໃບຢັ້ງຢືນຜົນ", "Result receipt")}</span></div>
          </div>

          {busy && (
            <div className="selfie-loading" role="status" aria-live="polite">
              <span />
{L("ກຳລັງອະນຸມັດການໂອນ", "Authorizing transfer")}
            </div>
          )}

          {authResult && (
            <div className={`document-notice document-notice-${approved ? "success" : "failure"}`} role="status">
              {approved ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
              <div>
                <strong>{approved ? L("ອະນຸມັດການໂອນແລ້ວ", "Transfer authorized") : L("ການໂອນຖືກລະງັບ", "Transfer blocked")}</strong>
                <p>
                  {approved
                    ? L(`ອະນຸມັດໂອນ ${currency} ${numericAmount.toLocaleString()} ໃຫ້ ${recipient.trim()} ດ້ວຍ Face ID ແລ້ວ.`, `${currency} ${numericAmount.toLocaleString()} to ${recipient.trim()} was approved by Face ID.`)
                    : L("ການອະນຸມັດດ້ວຍ Face ID ບໍ່ຜ່ານ. ໃຫ້ຜູ້ໃຊ້ລົງທະບຽນໃຫ້ສຳເລັດ ຫຼື ລອງໃໝ່.", "Face ID authorization did not pass. Ask the user to complete signup or try again.")}
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
{L("ລົງທະບຽນຜູ້ໃຊ້ໃໝ່", "New user signup")}
          </button>
        </div>

        <div className="payment-auth">
          <div className="payment-auth-header">
            <Send size={20} />
            <div>
              <strong>{canAuthorize ? L("ສະແກນ Face ID ເພື່ອໂອນ", "Scan Face ID to transfer") : L("ປ້ອນລາຍລະອຽດການໂອນ", "Enter transfer details")}</strong>
              <span>{canAuthorize ? L("ຕ້ອງຢືນຢັນດ້ວຍໃບໜ້າແບບສົດ.", "Live face authorization is required.") : L("ກະລຸນາປ້ອນຜູ້ຮັບ ແລະ ຈຳນວນເງິນກ່ອນ.", "Recipient and amount are required first.")}</span>
            </div>
          </div>
          <CameraCapture
            label={L("ອະນຸມັດດ້ວຍ Face Pay", "Face Pay authorization")}
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
      <button className="status-toast-close" type="button" onClick={onClose} aria-label={L("ປິດການແຈ້ງເຕືອນ", "Dismiss notification")}>
        <X size={18} />
      </button>
    </div>
  );
}

function DemoWarning({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`demo-warning ${compact ? "demo-warning-compact" : ""}`} role="note">
      <ShieldAlert size={18} />
      <span>{L("ສຳລັບທົດລອງເທົ່ານັ້ນ. ກະລຸນາໃຊ້ເອກະສານຕົວຢ່າງ ຫຼື ເອກະສານທີ່ປິດບັງຂໍ້ມູນແລ້ວ, ຢ່າໃຊ້ເອກະສານຕົວຕົນແທ້.", "Demo only. Use a sample or redacted document, never a real sensitive identity document.")}</span>
    </div>
  );
}

function ActiveLivenessStep({
  challenges,
  onComplete
}: {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean, evidence: Blob[]) => Promise<boolean | string>;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">{L("ຂັ້ນຕອນທີ 2", "Challenge")}</p>
        <h2>{L("ກວດໃບໜ້າຈິງ", "Active face liveness")}</h2>
        <p>
          {L("ເປີດກ້ອງ ແລະ ເຮັດທ່າຕາມທີ່ສະແດງ. ລະບົບຈະກວດຈັບການເຄື່ອນໄຫວ ແລະ ຂ້າມໄປທ່າຕໍ່ໄປໂດຍອັດຕະໂນມັດເມື່ອຜ່ານ.", "Open the camera and perform the highlighted action. The system detects the correct movement and automatically advances each challenge when it passes.")}
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
  onComplete: (challenge: Challenge, allDone: boolean, frames: Blob[]) => Promise<boolean>;
}) {
  return (
    <div className="step-layout">
      <div className="copy-block">
        <p className="eyebrow">{L("ຂັ້ນຕອນທີ 3", "Challenge")}</p>
        <h2>{L("ທ່າທາງມື", "Hand gesture challenge")}</h2>
        <p>
          {L("ເປີດກ້ອງເຕັມຈໍ ແລະ ວາງມືໄວ້ພາຍໃນວົງມົນສີເຫຼືອງ. ວົງມົນຈະຍ້າຍໄປຕຳແໜ່ງສຸ່ມສຳລັບແຕ່ລະທ່າ ແລະ ຈະຜ່ານອັດຕະໂນມັດເມື່ອກວດພົບທ່າທີ່ຖືກຕ້ອງ.", "Open the full-screen camera and place your hand inside the gold circle. The target moves to a random position for each gesture, and the step auto-passes when the correct sign is detected.")}
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
        <p className="eyebrow">{L("ຂັ້ນຕອນທີ 1", "Step 1")}</p>
        <h2>{L("ຖ່າຍຮູບ", "Capture your ")}{label.upload}{L("ຂອງທ່ານ", "")}</h2>
        <p>{L("ວາງ", "Place your ")}{label.upload}{L("ໄວ້ເທິງພື້ນຮາບ. ໃຫ້ເຫັນທຸກມຸມ ແລະ ຫຼີກລ່ຽງແສງສະທ້ອນ. ທ່ານສາມາດໃຊ້ກ້ອງ ຫຼື ອັບໂຫຼດຮູບທີ່ຊັດເຈນ.", " on a flat surface. Keep all corners visible and avoid glare. You can use your camera or upload a clear image.")}</p>
        <div className="document-type-switch" aria-label={L("ປະເພດເອກະສານ", "Document type")}>
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
{L("ກຳລັງເຊື່ອມຕໍ່ການຢັ້ງຢືນ", "Connecting verification session")}
          </div>
        )}
        <label className={`upload-drop ${disabled ? "disabled" : ""}`} htmlFor={disabled ? undefined : "passport-upload"} aria-disabled={disabled}>
          <Upload size={24} />
          <span>{L("ອັບໂຫຼດຮູບ", "Upload ")}{label.upload}{L("", " image")}</span>
          <small>{disabled ? L("ກະລຸນາລໍຖ້າຈົນກວ່າລະບົບພ້ອມ", "Wait until the session is ready") : L("JPG, PNG ຫຼື WebP", "JPG, PNG, or WebP")}</small>
          <input id="passport-upload" type="file" accept="image/*" onChange={onUpload} disabled={disabled} />
        </label>
      </div>
      <CameraCapture
        label={L(`ຖ່າຍຮູບ${label.title}`, `${label.title} camera capture`)}
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
        <p className="eyebrow">{L("ການທົດສອບ", "Challenge")}</p>
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
                <span>{challengePrompt(challenge)}</span>
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

function WatchlistBlock() {
  return (
    <div className="watchlist-block" role="alert">
      <div className="watchlist-block-badge">
        <ShieldAlert size={40} />
      </div>
      <h2>{L("ຢຸດການຢັ້ງຢືນ", "Verification halted")}</h2>
      <p className="watchlist-block-lead">{L("ບຸກຄົນນີ້ກົງກັບລາຍຊື່ໃນບັນຊີເຝົ້າລະວັງຂອງລັດ.", "This person matches a government watchlist entry.")}</p>
      <p className="watchlist-block-sub">
{L("ປະຕິເສດການເຂົ້າເຖິງ ແລະ ບໍ່ສາມາດດຳເນີນການຕໍ່ໄດ້. ກະລຸນາສົ່ງຜູ້ເດີນທາງໃຫ້ເຈົ້າໜ້າທີ່ ເພື່ອກວດສອບ.", "Access is denied and the session cannot continue. Please refer the traveller to an officer for manual review.")}
      </p>
      <span className="watchlist-block-code">WATCHLIST_MATCH</span>
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
        <p className="eyebrow">{L("ຂັ້ນຕອນທີ 4", "Step 4")}</p>
        <h2>{L("ເຊວຟີ ແລະ ທຽບໃບໜ້າ", "Selfie face match")}</h2>
        <p>{L("ເປີດກ້ອງ ແລະ ເຂົ້າມາໃກ້ຈົນໃບໜ້າເຕັມວົງມົນສີເຫຼືອງ, ຈາກນັ້ນຖ່າຍຮູບຕໍ່ເນື່ອງສັ້ນໆ ເພື່ອກວດໃບໜ້າຈິງ ແລະ ທຽບໃບໜ້າ.", "Open the camera and move close so your face fills the yellow circle, then capture a short live burst for passive liveness and face-match scoring.")}</p>
        {notice && <DocumentAnalysisNotice notice={notice} />}
        {busy && (
          <div className="selfie-loading" role="status" aria-live="polite">
            <span />
{L("ກຳລັງວິເຄາະເຊວຟີ", "Analyzing selfie")}
          </div>
        )}
      </div>
      <CameraCapture
        label={L("ຖ່າຍເຊວຟີ", "Selfie capture")}
        overlay="face"
        onCapture={onCapture}
        onCaptureFrames={onCapture}
        maxCaptureWidth={900}
        jpegQuality={0.84}
        burstCount={10}
        burstIntervalMs={250}
        captureLabel={L("ຖ່າຍຮູບຕໍ່ເນື່ອງ", "Capture live burst")}
        hint={L("ເຂົ້າມາໃກ້ຈົນໃບໜ້າເຕັມວົງມົນສີເຫຼືອງກ່ອນຖ່າຍ.", "Move close so your face fills the yellow circle before capturing.")}
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
      <h2>{passed ? L("ຢັ້ງຢືນຜ່ານ", "Verification passed") : result.decision === "rejected" ? L("ການຢັ້ງຢືນບໍ່ຜ່ານ", "Verification rejected") : L("ລໍຖ້າຜົນການຢັ້ງຢືນ", "Verification pending")}</h2>
      <p>{L("ຜົນສຸດທ້າຍອີງໃສ່ການວິເຄາະເອກະສານ, ການກວດໃບໜ້າຈິງ, ທ່າທາງມື ແລະ ເກນການທຽບໃບໜ້າ.", "Final decision uses document analysis, active liveness, hand gesture checks, passive liveness, and face-match thresholds.")}</p>
      {passed && (
        <button className="primary-button" type="button" onClick={onEnroll} disabled={enrollBusy}>
          <UserCheck size={18} />
          {enrollBusy ? L("ກຳລັງລົງທະບຽນ Face ID", "Enrolling Face ID") : L("ລົງທະບຽນ Face ID", "Enroll Face ID")}
        </button>
      )}
      {enrollmentNotice && <DocumentAnalysisNotice notice={enrollmentNotice} />}
      {enrollmentNotice?.profile && <ProfileSummary profile={enrollmentNotice.profile} />}
      <div className="result-grid">
        <Metric label={L("ຄຸນນະພາບ", "Quality")} value={result.document.image_quality_score} />
        <Metric label={L("ຄວາມສ່ຽງປອມແປງ", "Fraud risk")} value={result.document.fraud_risk_score} inverse />
        <Metric label={L("ການທຽບໃບໜ້າ", "Face match")} value={result.biometric.face_match_score} />
        <Metric label={L("ຄວາມສ່ຽງໃບໜ້າປອມ", "Passive risk")} value={result.biometric.passive_liveness_risk} inverse />
      </div>
      <OcrSummary result={result} />
    </div>
  );
}

function ProfileSummary({ profile }: { profile: UserProfile }) {
  const rows = [
    [L("ລະຫັດຜູ້ໃຊ້", "User ID"), profile.user_id],
    ["Face ID", profile.face_id],
    [L("ຊື່", "First name"), profile.first_name],
    [L("ນາມສະກຸນ", "Last name"), profile.last_name],
    [L("ອາຍຸ", "Age"), profile.age?.toString()],
    [L("ສັນຊາດ", "Nationality"), profile.nationality],
    [L("ເລກເອກະສານ", "Document No."), profile.passport_number],
    [L("ວັນໝົດອາຍຸເອກະສານ", "Document expiry"), profile.passport_expiry]
  ].filter(([, value]) => value);

  return (
    <section className="profile-summary" aria-label={L("ໂປຣໄຟລ໌ທີ່ຢັ້ງຢືນແລ້ວ", "Verified user profile")}>
      <h3>{L("ໂປຣໄຟລ໌ທີ່ຢັ້ງຢືນແລ້ວ", "Verified profile")}</h3>
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
  const mrzFound = result.document.checks.mrz_found;
  const mrzStatus = ocr.mrz_valid === null
    ? null
    : ocr.mrz_valid
      ? L("ຖືກຕ້ອງ", "Valid")
      : mrzFound === false
        ? L("ອ່ານບໍ່ຊັດເຈນ", "Not confidently read")
        : L("ຕົວເລກກວດສອບບໍ່ຖືກ", "Check digits failed");
  const rows = [
    [L("ຊື່ ແລະ ນາມສະກຸນ", "Name"), ocr.full_name],
    [isLaoId ? L("ເລກບັດ", "ID No.") : L("ເລກໜັງສືຜ່ານແດນ", "Passport No."), ocr.id_number ?? ocr.document_number ?? ocr.passport_number],
    [L("ສັນຊາດ", "Nationality"), ocr.nationality],
    [L("ວັນເດືອນປີເກີດ", "Date of birth"), ocr.date_of_birth],
    [L("ວັນໝົດອາຍຸ", "Expiry"), ocr.expiry_date],
    [isLaoId ? L("ຄວາມໝັ້ນໃຈ OCR", "OCR confidence") : L("ສະຖານະ MRZ", "MRZ status"), isLaoId ? `${Math.round(ocr.confidence * 100)}%` : mrzStatus]
  ].filter(([, value]) => value);

  if (!rows.length) return null;

  return (
    <section className={`ocr-summary ${compact ? "compact" : ""}`} aria-label={L(`ຜົນ OCR ${documentLabels[ocr.document_type].title}`, `${documentLabels[ocr.document_type].title} OCR result`)}>
      <h3>{L("ຂໍ້ມູນຈາກ", "")}{documentLabels[ocr.document_type].title}{L("", " OCR")}</h3>
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
