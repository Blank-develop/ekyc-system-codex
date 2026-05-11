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

export function ActiveLivenessCapture({ challenges, onComplete }: ActiveLivenessCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const faceMeshRef = useRef<FaceMeshInstance | null>(null);
  const rafRef = useRef<number | null>(null);
  const processingRef = useRef(false);
  const completionLockRef = useRef<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [modelReady, setModelReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<LivenessMetric>(emptyMetric);

  const currentChallenge = useMemo(() => challenges.find((challenge) => !challenge.passed), [challenges]);

  const startCamera = async () => {
    try {
      setError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setCameraReady(true);
    } catch {
      setError("Camera permission is required for active liveness.");
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
  };

  useEffect(() => {
    let disposed = false;

    loadFaceMeshScript()
      .then(() => {
        if (disposed || !window.FaceMesh) return;
        const faceMesh = new window.FaceMesh({
          locateFile: (file) => `/vendor/mediapipe/face_mesh/${file}`
        });
        faceMesh.setOptions({
          maxNumFaces: 1,
          refineLandmarks: true,
          selfieMode: true,
          minDetectionConfidence: 0.65,
          minTrackingConfidence: 0.65
        });
        faceMesh.onResults((results: Results) => {
          const landmarks = results.multiFaceLandmarks?.[0];
          const nextMetric = landmarks ? readLivenessMetric(landmarks) : emptyMetric;
          setMetric(nextMetric);
        });
        faceMeshRef.current = faceMesh;
        return faceMesh.initialize();
      })
      .then(() => {
        if (!disposed) setModelReady(true);
      })
      .catch(() => {
        if (!disposed) setError("Active liveness model could not be loaded.");
      });

    return () => {
      disposed = true;
      stopCamera();
      faceMeshRef.current?.close();
    };
  }, []);

  useEffect(() => {
    completionLockRef.current = null;
  }, [currentChallenge?.id]);

  useEffect(() => {
    if (!cameraReady || !modelReady) return;

    const processFrame = async () => {
      const video = videoRef.current;
      const faceMesh = faceMeshRef.current;
      if (video && faceMesh && video.readyState >= 2 && !processingRef.current) {
        processingRef.current = true;
        try {
          await faceMesh.send({ image: video });
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

function loadFaceMeshScript() {
  if (window.FaceMesh) return Promise.resolve();
  const existing = document.querySelector<HTMLScriptElement>("script[data-mediapipe-face-mesh]");
  if (existing) {
    return new Promise<void>((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("FaceMesh script failed")), { once: true });
    });
  }
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/mediapipe/face_mesh/face_mesh.js";
    script.async = true;
    script.dataset.mediapipeFaceMesh = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("FaceMesh script failed"));
    document.head.appendChild(script);
  });
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
  if (!modelReady) return "Loading face model";
  if (!cameraReady) return "Open the camera to begin";
  if (challengeId === "blink") return "Blink once to auto-pass";
  if (challengeId === "open_mouth") return "Open your mouth to auto-pass";
  if (challengeId === "turn_left") return "Turn your head left to auto-pass";
  if (challengeId === "turn_right") return "Turn your head right to auto-pass";
  return "Perform the requested action";
}
