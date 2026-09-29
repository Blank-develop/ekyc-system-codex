import type { FaceMeshConfig, InputMap, NormalizedLandmarkList, Options, Results, ResultsListener } from "@mediapipe/face_mesh";
import { Camera, CameraOff, Check, ScanFace, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Challenge } from "../lib/api";
import { challengePrompt } from "../lib/lao";
import { L } from "../lib/i18n";
import { cameraErrorMessage, cameraUnavailableMessage } from "../lib/camera";
import { analyzeVideoLighting, type LightingStatus } from "../lib/lighting";

type FaceMeshInstance = {
  close: () => Promise<void>;
  initialize: () => Promise<void>;
  onResults: (listener: ResultsListener) => void;
  send: (inputs: InputMap) => Promise<void>;
  setOptions: (options: Options) => void;
};

declare global {
  interface Window {
    FaceMesh?: new (config?: FaceMeshConfig) => FaceMeshInstance;
    createMediapipeSolutionsPackedAssets?: unknown;
    createMediapipeSolutionsWasm?: unknown;
  }
}

type LivenessMetric = {
  blink: boolean;
  mouthOpen: boolean;
  turnLeft: boolean;
  turnRight: boolean;
  facePresent: boolean;
  yaw: number;
  eyeRatio: number;
  mouthRatio: number;
  faceWidthRatio: number;
  faceHeightRatio: number;
  faceTooSmall: boolean;
};

interface ActiveLivenessCaptureProps {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean, evidence: Blob[]) => Promise<boolean | string>;
}

const emptyMetric: LivenessMetric = {
  blink: false,
  mouthOpen: false,
  turnLeft: false,
  turnRight: false,
  facePresent: false,
  yaw: 0,
  eyeRatio: 0,
  mouthRatio: 0,
  faceWidthRatio: 0,
  faceHeightRatio: 0,
  faceTooSmall: false
};

const LOCAL_FACE_MESH_SOURCE = {
  name: "local",
  scriptUrl: "/vendor/mediapipe/face_mesh/face_mesh.js",
  assetBaseUrl: "/vendor/mediapipe/face_mesh"
};

const CDN_FACE_MESH_SOURCE = {
  name: "jsdelivr",
  scriptUrl: "https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/face_mesh.js",
  assetBaseUrl: "https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh"
};

const FACE_MESH_SOURCES = [LOCAL_FACE_MESH_SOURCE, CDN_FACE_MESH_SOURCE];
const FACE_MESH_SCRIPT_TIMEOUT_MS = 8000;
type FaceMeshSource = typeof FACE_MESH_SOURCES[number];
let sharedFaceMeshPromise: Promise<FaceMeshInstance> | null = null;

function preferredFaceMeshSources() {
  const isLocalhost = ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  return isLocalhost ? FACE_MESH_SOURCES : [CDN_FACE_MESH_SOURCE, LOCAL_FACE_MESH_SOURCE];
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string) {
  return new Promise<T>((resolve, reject) => {
    const timeout = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    promise
      .then((value) => resolve(value))
      .catch((error) => reject(error))
      .finally(() => window.clearTimeout(timeout));
  });
}

const faceMeshFallbackHelp = () => L("ລອງໂຫຼດໜ້າໃໝ່ອີກຄັ້ງ; ຖ້າຍັງບໍ່ໄດ້ ໃຫ້ກວດວ່າອຸປະກອນນີ້ສາມາດໂຫຼດໄຟລ໌ MediaPipe ຫຼື cdn.jsdelivr.net ໄດ້.", "Hard refresh the page once; if it still fails, check that this device can load the local MediaPipe assets or cdn.jsdelivr.net.");
const ACTIVE_LIVENESS_EVIDENCE_FRAME_COUNT = 3;
const ACTIVE_LIVENESS_EVIDENCE_INTERVAL_MS = 140;

function faceMeshLoadMessage(error: unknown) {
  const detail = error instanceof Error ? error.message : "unknown error";
  return L(`ບໍ່ສາມາດໂຫຼດແບບຈຳລອງກວດໃບໜ້າໄດ້. ${faceMeshFallbackHelp()} (${detail})`, `Active liveness model could not be loaded. ${faceMeshFallbackHelp()} (${detail})`);
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function removeFaceMeshScript(source: FaceMeshSource) {
  document.querySelectorAll<HTMLScriptElement>("script[data-mediapipe-face-mesh]").forEach((script) => {
    if (script.src === source.scriptUrl || script.getAttribute("src") === source.scriptUrl) {
      script.remove();
    }
  });
}

function resetFaceMeshGlobals(source: FaceMeshSource) {
  delete window.FaceMesh;
  delete window.createMediapipeSolutionsPackedAssets;
  delete window.createMediapipeSolutionsWasm;
  removeFaceMeshScript(source);
}

export function ActiveLivenessCapture({ challenges, onComplete }: ActiveLivenessCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const faceMeshRef = useRef<FaceMeshInstance | null>(null);
  const rafRef = useRef<number | null>(null);
  const processingRef = useRef(false);
  const completionLockRef = useRef<string | null>(null);
  const modelFailedRef = useRef(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [modelReady, setModelReady] = useState(false);
  const [verifyingChallengeId, setVerifyingChallengeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<LivenessMetric>(emptyMetric);
  const [fullscreen, setFullscreen] = useState(false);
  const [lightingStatus, setLightingStatus] = useState<LightingStatus | null>(null);

  const currentChallenge = useMemo(() => challenges.find((challenge) => !challenge.passed), [challenges]);

  const startCamera = async () => {
    let stream: MediaStream | null = null;
    try {
      setError(null);
      const supportMessage = cameraUnavailableMessage();
      if (supportMessage) {
        setError(supportMessage);
        setCameraReady(false);
        return;
      }
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      const faceMesh = await getSharedFaceMesh();
      modelFailedRef.current = false;
      faceMesh.onResults((results: Results) => {
        const landmarks = results.multiFaceLandmarks?.[0];
        const nextMetric = landmarks ? readLivenessMetric(landmarks) : emptyMetric;
        setMetric(nextMetric);
      });
      faceMeshRef.current = faceMesh;
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setModelReady(true);
      setCameraReady(true);
      setFullscreen(true);
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      setError(cameraErrorMessage(error, faceMeshLoadMessage(error)));
      setCameraReady(false);
      setFullscreen(false);
    }
  };

  const stopCamera = () => {
    if (rafRef.current) {
      window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraReady(false);
    setFullscreen(false);
    setMetric(emptyMetric);
    setLightingStatus(null);
    modelFailedRef.current = false;
  };

  useEffect(() => () => stopCamera(), []);

  useEffect(() => {
    if (cameraReady && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraReady, fullscreen]);

  useEffect(() => {
    if (!cameraReady) return;

    const interval = window.setInterval(() => {
      setLightingStatus(analyzeVideoLighting(videoRef.current));
    }, 450);

    return () => window.clearInterval(interval);
  }, [cameraReady]);

  useEffect(() => {
    completionLockRef.current = null;
  }, [currentChallenge?.id]);

  useEffect(() => {
    if (!cameraReady || !modelReady) return;

    const processFrame = async () => {
      const video = videoRef.current;
      const faceMesh = faceMeshRef.current;
      if (video && faceMesh && video.readyState >= 2 && !processingRef.current && !modelFailedRef.current) {
        processingRef.current = true;
        try {
          await faceMesh.send({ image: video });
        } catch (error) {
          modelFailedRef.current = true;
          resetSharedFaceMesh(faceMesh);
          faceMeshRef.current = null;
          console.warn("[active-liveness] FaceMesh frame failed", error);
          setError(faceMeshLoadMessage(error));
          setModelReady(false);
        } finally {
          processingRef.current = false;
        }
      }
      rafRef.current = window.requestAnimationFrame(processFrame);
    };

    rafRef.current = window.requestAnimationFrame(processFrame);
    return () => {
      if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
    };
  }, [cameraReady, modelReady]);

  useEffect(() => {
    if (!currentChallenge || !metric.facePresent) return;
    if (metric.faceTooSmall) return;
    if (!matchesChallenge(currentChallenge.id, metric)) return;
    if (completionLockRef.current === currentChallenge.id) return;

    completionLockRef.current = currentChallenge.id;
    const remainingAfterThis = challenges.filter((challenge) => !challenge.passed && challenge.id !== currentChallenge.id).length;
    setVerifyingChallengeId(currentChallenge.id);
    window.setTimeout(async () => {
      const evidence = await captureEvidenceBurst(
        videoRef.current,
        ACTIVE_LIVENESS_EVIDENCE_FRAME_COUNT,
        ACTIVE_LIVENESS_EVIDENCE_INTERVAL_MS
      );
      if (evidence.length === 0) {
        completionLockRef.current = null;
        setVerifyingChallengeId(null);
        setError(L("ບໍ່ສາມາດຖ່າຍຮູບຫຼັກຖານໄດ້. ໃຫ້ເຫັນໃບໜ້າ ແລ້ວລອງໃໝ່.", "Could not capture active liveness evidence. Keep your face visible and try again."));
        return;
      }
      try {
        const accepted = await onComplete(currentChallenge, remainingAfterThis === 0, evidence);
        setVerifyingChallengeId(null);
        if (accepted !== true) {
          completionLockRef.current = null;
          setError(typeof accepted === "string" ? accepted : L("ການກວດໃບໜ້າຈິງບໍ່ຜ່ານ. ເຂົ້າມາໃກ້, ໃຊ້ແສງທີ່ສະໝ່ຳສະເໝີ ແລ້ວເຮັດທ່າອີກຄັ້ງ.", "Live-face verification failed. Move closer, use even lighting, and try the action again."));
        }
      } catch (error) {
        setVerifyingChallengeId(null);
        completionLockRef.current = null;
        setError(error instanceof Error ? error.message : L("ບໍ່ສາມາດກວດໃບໜ້າຈິງໄດ້. ກະລຸນາລອງໃໝ່.", "Active liveness could not be verified. Try again."));
      }
    }, 350);
  }, [challenges, currentChallenge, metric, onComplete]);

  const renderCompactActions = (fullscreenMode = false) => (
    <div
      className={`liveness-mobile-action-strip${fullscreenMode ? " active-liveness-fullscreen-actions" : ""}`}
      aria-label={L("ທ່າກວດໃບໜ້າຈິງ", "Active liveness actions")}
    >
      {challenges.map((challenge) => {
        const isCurrent = currentChallenge?.id === challenge.id;
        const isDetected = isCurrent && matchesChallenge(challenge.id, metric);
        return (
          <div
            className={`liveness-detection-card ${challenge.passed ? "passed" : ""} ${isCurrent ? "current" : ""} ${isDetected ? "detected" : ""}`}
            key={challenge.id}
          >
            <span>{challenge.passed ? <Check size={15} /> : challengePrompt(challenge)}</span>
            <small>
              {challenge.passed
                ? L("ສຳເລັດ", "Done")
                : isCurrent
                  ? verifyingChallengeId === challenge.id
                    ? L("ກຳລັງກວດ", "Checking")
                    : shortDetectionInstruction(challenge.id, modelReady, cameraReady)
                  : L("ຖັດໄປ", "Next")}
            </small>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="active-liveness">
      {!fullscreen && <div className="liveness-camera camera-frame camera-frame-face">
        <video ref={videoRef} autoPlay playsInline muted />
        <div className="capture-overlay capture-overlay-face" aria-hidden="true" />
        {!cameraReady && (
          <div className="camera-empty">
            <CameraOff size={30} />
            <span>{L("ກ້ອງປິດຢູ່", "Camera is off")}</span>
          </div>
        )}
        {cameraReady && (
          <div className="liveness-status-pill">
            <ScanFace size={16} />
            {metric.facePresent ? L("ກວດພົບໃບໜ້າ", "Face detected") : L("ໃຫ້ໃບໜ້າຢູ່ກາງ", "Center your face")}
          </div>
        )}
        {cameraReady && !verifyingChallengeId && lightingStatus?.level === "warning" && (
          <div className="camera-lighting-warning" role="status" aria-live="polite">
            {lightingStatus.message}
          </div>
        )}
        {renderCompactActions()}
      </div>}

      {fullscreen && (
        <div className="active-liveness-fullscreen" role="dialog" aria-modal="true" aria-label={L("ກວດໃບໜ້າຈິງແບບເຕັມຈໍ", "Full-screen active liveness challenge")}>
          <video ref={videoRef} autoPlay playsInline muted />
          <div className="active-liveness-topbar">
            <div>
              <strong>{challengePrompt(currentChallenge) ?? L("ກວດໃບໜ້າຈິງສຳເລັດ", "Active liveness complete")}</strong>
              <span>
                {currentChallenge
                  ? verifyingChallengeId === currentChallenge.id
                    ? L("ກຳລັງກວດຮູບຕໍ່ເນື່ອງ", "Checking live burst for screen replay")
                    : detectionInstruction(currentChallenge.id, modelReady, cameraReady)
                  : L("ເຮັດຄົບທຸກທ່າແລ້ວ", "All actions completed")}
              </span>
            </div>
            <button className="icon-button" type="button" onClick={stopCamera} aria-label={L("ປິດກ້ອງ", "Close active liveness camera")}>
              <X size={22} />
            </button>
          </div>
          {cameraReady && (
            <div className="liveness-status-pill active-liveness-fullscreen-status">
              <ScanFace size={16} />
              {metric.facePresent ? metric.faceTooSmall ? L("ເຂົ້າມາໃກ້ອີກ", "Move closer") : L("ໃບໜ້າພ້ອມແລ້ວ", "Face ready") : L("ໃຫ້ໃບໜ້າຢູ່ກາງ", "Center your face")}
            </div>
          )}
          {verifyingChallengeId && (
            <div className="selfie-loading active-liveness-fullscreen-verifying" role="status" aria-live="polite">
              <span />
{L("ກຳລັງກວດໃບໜ້າຈິງ", "Verifying live face")}
            </div>
          )}
          {error && <p className="form-error active-liveness-fullscreen-error" aria-live="polite">{error}</p>}
          {!verifyingChallengeId && lightingStatus?.level === "warning" && (
            <div className="camera-lighting-warning active-liveness-fullscreen-lighting" role="status" aria-live="polite">
              {lightingStatus.message}
            </div>
          )}
          {!verifyingChallengeId && metric.facePresent && metric.faceTooSmall && (
            <div className="camera-distance-warning" role="status" aria-live="polite">
              {L("ເຂົ້າມາໃກ້ກ້ອງ. ໃຫ້ເຫັນໃບໜ້າທັງໝົດ ແລະ ໃຫ້ໃບໜ້າກວມປະມານໜຶ່ງສ່ວນສາມຂອງໜ້າຈໍ ກ່ອນເຮັດທ່າ.", "Move closer to the camera. Keep your full face visible and let it fill about one-third of the screen before performing the action.")}
            </div>
          )}
          {renderCompactActions(true)}
        </div>
      )}

      {error && <p className="form-error" aria-live="polite">{error}</p>}

      <div className="liveness-actions">
        <button className="secondary-button" type="button" onClick={cameraReady ? stopCamera : startCamera}>
          {cameraReady ? <CameraOff size={18} /> : <Camera size={18} />}
          {cameraReady ? L("ປິດກ້ອງ", "Stop camera") : L("ເປີດກ້ອງ", "Open camera")}
        </button>
      </div>
      {verifyingChallengeId && (
        <div className="selfie-loading active-liveness-verifying" role="status" aria-live="polite">
          <span />
{L("ກຳລັງກວດໃບໜ້າຈິງ", "Verifying live face")}
        </div>
      )}

      <div className="liveness-detection-list" aria-label={L("ການກວດຈັບທ່າ", "Active liveness challenge detection")}>
        {challenges.map((challenge) => {
          const isCurrent = currentChallenge?.id === challenge.id;
          const isDetected = isCurrent && matchesChallenge(challenge.id, metric);
          return (
            <div
              className={`liveness-detection-card ${challenge.passed ? "passed" : ""} ${isCurrent ? "current" : ""} ${isDetected ? "detected" : ""}`}
              key={challenge.id}
            >
              <span>{challenge.passed ? <Check size={16} /> : challengePrompt(challenge)}</span>
              <small>
                {challenge.passed
                  ? L("ສຳເລັດແລ້ວ", "Completed")
                  : isCurrent
                    ? verifyingChallengeId === challenge.id
                      ? L("ກຳລັງກວດຮູບຕໍ່ເນື່ອງ", "Checking live burst for screen replay")
                      : detectionInstruction(challenge.id, modelReady, cameraReady)
                    : L("ລໍຖ້າທ່າກ່ອນໜ້າ", "Waiting for previous action")}
              </small>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function captureEvidenceFrame(video: HTMLVideoElement | null) {
  if (!video || video.videoWidth === 0 || video.videoHeight === 0) return Promise.resolve<Blob | null>(null);
  const maxWidth = 900;
  const scale = Math.min(1, maxWidth / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const context = canvas.getContext("2d");
  if (!context) return Promise.resolve<Blob | null>(null);
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise<Blob | null>((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.84);
  });
}

async function captureEvidenceBurst(video: HTMLVideoElement | null, count: number, intervalMs: number) {
  const frames: Blob[] = [];
  for (let index = 0; index < count; index += 1) {
    const frame = await captureEvidenceFrame(video);
    if (frame) frames.push(frame);
    if (index < count - 1) {
      await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    }
  }
  return frames;
}

function getSharedFaceMesh() {
  if (!sharedFaceMeshPromise) {
    sharedFaceMeshPromise = createFaceMesh().catch((error) => {
      sharedFaceMeshPromise = null;
      throw error;
    });
  }
  return sharedFaceMeshPromise;
}

function resetSharedFaceMesh(faceMesh?: FaceMeshInstance | null) {
  sharedFaceMeshPromise = null;
  faceMesh?.close().catch(() => undefined);
  FACE_MESH_SOURCES.forEach((source) => resetFaceMeshGlobals(source));
}

async function createFaceMesh() {
  const sourceErrors: string[] = [];
  for (const source of preferredFaceMeshSources()) {
    try {
      await loadFaceMeshScript(source);
      if (!window.FaceMesh) throw new Error("FaceMesh global missing");
      const faceMesh = new window.FaceMesh({
        locateFile: (file) => `${source.assetBaseUrl}/${file}`
      });
      faceMesh.setOptions({
        maxNumFaces: 1,
        refineLandmarks: true,
        selfieMode: true,
        minDetectionConfidence: 0.65,
        minTrackingConfidence: 0.65
      });
      return faceMesh;
    } catch (error) {
      sourceErrors.push(`${source.name}: ${describeError(error)}`);
      console.warn("[active-liveness] FaceMesh source failed", source.name, error);
      resetFaceMeshGlobals(source);
    }
  }
  throw new Error(sourceErrors.join(" | ") || "FaceMesh failed to initialize");
}

function loadFaceMeshScript(source: FaceMeshSource) {
  if (window.FaceMesh) return Promise.resolve();
  const existing = Array.from(document.querySelectorAll<HTMLScriptElement>("script[data-mediapipe-face-mesh]")).find(
    (script) => script.src === source.scriptUrl || script.getAttribute("src") === source.scriptUrl
  );
  if (existing) {
    return withTimeout(new Promise<void>((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("FaceMesh script failed")), { once: true });
    }), FACE_MESH_SCRIPT_TIMEOUT_MS, `${source.name} FaceMesh script load timed out`);
  }
  return withTimeout(new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = source.scriptUrl;
    script.async = true;
    script.dataset.mediapipeFaceMesh = "true";
    script.dataset.mediapipeFaceMeshSource = source.name;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`${source.name} FaceMesh script failed`));
    document.head.appendChild(script);
  }), FACE_MESH_SCRIPT_TIMEOUT_MS, `${source.name} FaceMesh script load timed out`);
}

function readLivenessMetric(landmarks: NormalizedLandmarkList): LivenessMetric {
  const leftEye = eyeRatio(landmarks, 33, 133, 159, 145);
  const rightEye = eyeRatio(landmarks, 362, 263, 386, 374);
  const averageEyeRatio = (leftEye + rightEye) / 2;
  const mouthRatio = distance(landmarks[13], landmarks[14]) / Math.max(distance(landmarks[61], landmarks[291]), 0.001);
  const faceWidth = Math.max(distance(landmarks[234], landmarks[454]), 0.001);
  const faceCenterX = (landmarks[234].x + landmarks[454].x) / 2;
  const yaw = (landmarks[1].x - faceCenterX) / faceWidth;
  const xs = landmarks.map((landmark) => landmark.x);
  const ys = landmarks.map((landmark) => landmark.y);
  const faceWidthRatio = Math.max(...xs) - Math.min(...xs);
  const faceHeightRatio = Math.max(...ys) - Math.min(...ys);
  const faceTooSmall = faceWidthRatio < 0.24 || faceHeightRatio < 0.3;

  return {
    blink: averageEyeRatio < 0.18,
    mouthOpen: mouthRatio > 0.23,
    // Lowered from ±0.08 so a smaller, more natural head turn registers as
    // quickly as a blink or open mouth (0.08 needed a large ~15-20 deg turn).
    turnLeft: yaw < -0.05,
    turnRight: yaw > 0.05,
    facePresent: true,
    yaw,
    eyeRatio: averageEyeRatio,
    mouthRatio,
    faceWidthRatio,
    faceHeightRatio,
    faceTooSmall
  };
}

function eyeRatio(landmarks: NormalizedLandmarkList, left: number, right: number, top: number, bottom: number) {
  return distance(landmarks[top], landmarks[bottom]) / Math.max(distance(landmarks[left], landmarks[right]), 0.001);
}

function distance(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function matchesChallenge(challengeId: string, metric: LivenessMetric) {
  if (challengeId === "blink") return metric.blink;
  if (challengeId === "open_mouth") return metric.mouthOpen;
  if (challengeId === "turn_left") return metric.turnLeft;
  if (challengeId === "turn_right") return metric.turnRight;
  return false;
}

function detectionInstruction(challengeId: string, modelReady: boolean, cameraReady: boolean) {
  if (!cameraReady) return L("ເປີດກ້ອງເພື່ອເລີ່ມ", "Open the camera to begin");
  if (!modelReady) return L("ກຳລັງໂຫຼດແບບຈຳລອງໃບໜ້າ", "Loading face model");
  if (challengeId === "blink") return L("ກະພິບຕາເພື່ອຜ່ານອັດຕະໂນມັດ", "Blink once to auto-pass");
  if (challengeId === "open_mouth") return L("ອ້າປາກເພື່ອຜ່ານອັດຕະໂນມັດ", "Open your mouth to auto-pass");
  if (challengeId === "turn_left") return L("ຫັນຫົວໄປຊ້າຍເພື່ອຜ່ານອັດຕະໂນມັດ", "Turn your head left to auto-pass");
  if (challengeId === "turn_right") return L("ຫັນຫົວໄປຂວາເພື່ອຜ່ານອັດຕະໂນມັດ", "Turn your head right to auto-pass");
  return L("ເຮັດທ່າຕາມທີ່ກຳນົດ", "Perform the requested action");
}

function shortDetectionInstruction(challengeId: string, modelReady: boolean, cameraReady: boolean) {
  if (!cameraReady) return L("ເປີດກ້ອງ", "Open camera");
  if (!modelReady) return L("ກຳລັງໂຫຼດ", "Loading");
  if (challengeId === "blink") return L("ກະພິບຕາ", "Blink");
  if (challengeId === "open_mouth") return L("ອ້າປາກ", "Open mouth");
  if (challengeId === "turn_left") return L("ຫັນຊ້າຍ", "Turn left");
  if (challengeId === "turn_right") return L("ຫັນຂວາ", "Turn right");
  return L("ເຮັດທ່າ", "Do action");
}
