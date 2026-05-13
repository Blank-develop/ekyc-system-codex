import type { FaceMeshConfig, InputMap, NormalizedLandmarkList, Options, Results, ResultsListener } from "@mediapipe/face_mesh";
import { Camera, CameraOff, Check, ScanFace } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Challenge } from "../lib/api";

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
};

interface ActiveLivenessCaptureProps {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean) => void;
}

const emptyMetric: LivenessMetric = {
  blink: false,
  mouthOpen: false,
  turnLeft: false,
  turnRight: false,
  facePresent: false,
  yaw: 0,
  eyeRatio: 0,
  mouthRatio: 0
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

const FACE_MESH_FALLBACK_HELP = "Hard refresh the page once; if it still fails, check that this device can load the local MediaPipe assets or cdn.jsdelivr.net.";

function faceMeshLoadMessage(error: unknown) {
  const detail = error instanceof Error ? error.message : "unknown error";
  return `Active liveness model could not be loaded. ${FACE_MESH_FALLBACK_HELP} (${detail})`;
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
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<LivenessMetric>(emptyMetric);

  const currentChallenge = useMemo(() => challenges.find((challenge) => !challenge.passed), [challenges]);

  const startCamera = async () => {
    let stream: MediaStream | null = null;
    try {
      setError(null);
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
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      const message = error instanceof DOMException && error.name === "NotAllowedError"
        ? "Camera permission is required for active liveness."
        : faceMeshLoadMessage(error);
      setError(message);
      setCameraReady(false);
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
    setMetric(emptyMetric);
    modelFailedRef.current = false;
  };

  useEffect(() => () => stopCamera(), []);

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
    if (!matchesChallenge(currentChallenge.id, metric)) return;
    if (completionLockRef.current === currentChallenge.id) return;

    completionLockRef.current = currentChallenge.id;
    const remainingAfterThis = challenges.filter((challenge) => !challenge.passed && challenge.id !== currentChallenge.id).length;
    window.setTimeout(() => {
      onComplete(currentChallenge, remainingAfterThis === 0);
    }, 350);
  }, [challenges, currentChallenge, metric, onComplete]);

  return (
    <div className="active-liveness">
      <div className="liveness-camera camera-frame camera-frame-face">
        <video ref={videoRef} autoPlay playsInline muted />
        <div className="capture-overlay capture-overlay-face" aria-hidden="true" />
        {!cameraReady && (
          <div className="camera-empty">
            <CameraOff size={30} />
            <span>Camera is off</span>
          </div>
        )}
        {cameraReady && (
          <div className="liveness-status-pill">
            <ScanFace size={16} />
            {metric.facePresent ? "Face detected" : "Center your face"}
          </div>
        )}
      </div>

      {error && <p className="form-error" aria-live="polite">{error}</p>}

      <div className="liveness-actions">
        <button className="secondary-button" type="button" onClick={cameraReady ? stopCamera : startCamera}>
          {cameraReady ? <CameraOff size={18} /> : <Camera size={18} />}
          {cameraReady ? "Stop camera" : "Open camera"}
        </button>
      </div>

      <div className="liveness-detection-list" aria-label="Active liveness challenge detection">
        {challenges.map((challenge) => {
          const isCurrent = currentChallenge?.id === challenge.id;
          const isDetected = isCurrent && matchesChallenge(challenge.id, metric);
          return (
            <div
              className={`liveness-detection-card ${challenge.passed ? "passed" : ""} ${isCurrent ? "current" : ""} ${isDetected ? "detected" : ""}`}
              key={challenge.id}
            >
              <span>{challenge.passed ? <Check size={16} /> : challenge.prompt}</span>
              <small>
                {challenge.passed
                  ? "Completed"
                  : isCurrent
                    ? detectionInstruction(challenge.id, modelReady, cameraReady)
                    : "Waiting for previous action"}
              </small>
            </div>
          );
        })}
      </div>
    </div>
  );
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

  return {
    blink: averageEyeRatio < 0.18,
    mouthOpen: mouthRatio > 0.23,
    turnLeft: yaw < -0.08,
    turnRight: yaw > 0.08,
    facePresent: true,
    yaw,
    eyeRatio: averageEyeRatio,
    mouthRatio
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
  if (!cameraReady) return "Open the camera to begin";
  if (!modelReady) return "Loading face model";
  if (challengeId === "blink") return "Blink once to auto-pass";
  if (challengeId === "open_mouth") return "Open your mouth to auto-pass";
  if (challengeId === "turn_left") return "Turn your head left to auto-pass";
  if (challengeId === "turn_right") return "Turn your head right to auto-pass";
  return "Perform the requested action";
}
