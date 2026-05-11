import type { HandsConfig, InputMap, NormalizedLandmarkList, Options, Results, ResultsListener } from "@mediapipe/hands";
import { Camera, CameraOff, Check, Hand, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Challenge } from "../lib/api";

type HandsInstance = {
  close: () => Promise<void>;
  initialize: () => Promise<void>;
  onResults: (listener: ResultsListener) => void;
  send: (inputs: InputMap) => Promise<void>;
  setOptions: (options: Options) => void;
};

declare global {
  interface Window {
    Hands?: new (config?: HandsConfig) => HandsInstance;
  }
}

type Target = {
  left: number;
  top: number;
  size: number;
};

type GestureMetric = {
  handPresent: boolean;
  centerX: number;
  centerY: number;
  fingerCount: number;
  gesture: string | null;
};

interface HandGestureCaptureProps {
  challenges: Challenge[];
  onComplete: (challenge: Challenge, allDone: boolean) => void;
}

const emptyMetric: GestureMetric = {
  handPresent: false,
  centerX: 0,
  centerY: 0,
  fingerCount: 0,
  gesture: null
};

export function HandGestureCapture({ challenges, onComplete }: HandGestureCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const handsRef = useRef<HandsInstance | null>(null);
  const rafRef = useRef<number | null>(null);
  const processingRef = useRef(false);
  const completionLockRef = useRef<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [modelReady, setModelReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<GestureMetric>(emptyMetric);
  const [target, setTarget] = useState<Target>(() => randomTarget());
  const [holdProgress, setHoldProgress] = useState(0);

  const currentChallenge = useMemo(() => challenges.find((challenge) => !challenge.passed), [challenges]);
  const handInsideTarget = metric.handPresent && isInsideTarget(metric, target);
  const gestureMatched = Boolean(currentChallenge && handInsideTarget && matchesGesture(currentChallenge.id, metric));

  const startCamera = async () => {
    try {
      setError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      streamRef.current = stream;
      setCameraReady(true);
      setFullscreen(true);
    } catch {
      setError("Camera permission is required for the gesture challenge.");
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
    setFullscreen(false);
    setMetric(emptyMetric);
  };

  useEffect(() => {
    let disposed = false;

    loadHandsScript()
      .then(() => {
        if (disposed || !window.Hands) return;
        const hands = new window.Hands({
          locateFile: (file) => `/vendor/mediapipe/hands/${file}`
        });
        hands.setOptions({
          maxNumHands: 1,
          modelComplexity: 1,
          selfieMode: true,
          minDetectionConfidence: 0.68,
          minTrackingConfidence: 0.68
        });
        hands.onResults((results: Results) => {
          const landmarks = results.multiHandLandmarks?.[0];
          setMetric(landmarks ? readGestureMetric(landmarks) : emptyMetric);
        });
        handsRef.current = hands;
        return hands.initialize();
      })
      .then(() => {
        if (!disposed) setModelReady(true);
      })
      .catch(() => {
        if (!disposed) setError("Hand gesture model could not be loaded.");
      });

    return () => {
      disposed = true;
      stopCamera();
      handsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (fullscreen && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [fullscreen, cameraReady]);

  useEffect(() => {
    completionLockRef.current = null;
    setTarget(randomTarget());
    setHoldProgress(0);
  }, [currentChallenge?.id]);

  useEffect(() => {
    if (!cameraReady || !modelReady) return;

    const processFrame = async () => {
      const video = videoRef.current;
      const hands = handsRef.current;
      if (video && hands && video.readyState >= 2 && !processingRef.current) {
        processingRef.current = true;
        try {
          await hands.send({ image: video });
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
    if (!currentChallenge) {
      setHoldProgress(0);
      return;
    }
    if (!gestureMatched) {
      setHoldProgress(0);
      return;
    }
    if (completionLockRef.current === currentChallenge.id) return;

    const interval = window.setInterval(() => {
      setHoldProgress((current) => {
        const next = Math.min(current + 12, 100);
        if (next >= 100 && completionLockRef.current !== currentChallenge.id) {
          completionLockRef.current = currentChallenge.id;
          const remainingAfterThis = challenges.filter((challenge) => !challenge.passed && challenge.id !== currentChallenge.id).length;
          window.setTimeout(() => {
            onComplete(currentChallenge, remainingAfterThis === 0);
            if (remainingAfterThis === 0) {
              stopCamera();
            }
          }, 180);
        }
        return next;
      });
    }, 55);

    return () => window.clearInterval(interval);
  }, [challenges, currentChallenge, gestureMatched, onComplete]);

  return (
    <div className="gesture-capture">
      <div className="gesture-instructions">
        <button className="primary-button wide" type="button" onClick={startCamera} disabled={!modelReady || !currentChallenge}>
          <Camera size={18} />
          Open full-screen camera
        </button>
        {error && <p className="form-error" aria-live="polite">{error}</p>}
      </div>

      <div className="gesture-list" aria-label="Hand gesture challenges">
        {challenges.map((challenge) => {
          const isCurrent = currentChallenge?.id === challenge.id;
          return (
            <div className={`gesture-card ${challenge.passed ? "passed" : ""} ${isCurrent ? "current" : ""}`} key={challenge.id}>
              <span>{challenge.passed ? <Check size={16} /> : challenge.prompt}</span>
              <small>{challenge.passed ? "Completed" : isCurrent ? "Perform this gesture inside the circle" : "Waiting for previous gesture"}</small>
            </div>
          );
        })}
      </div>

      {fullscreen && (
        <div className="gesture-fullscreen" role="dialog" aria-modal="true" aria-label="Full-screen hand gesture challenge">
          <video ref={videoRef} autoPlay playsInline muted />
          <div
            className={`gesture-target ${gestureMatched ? "matched" : handInsideTarget ? "inside" : ""}`}
            style={{
              left: `${target.left}%`,
              top: `${target.top}%`,
              width: `${target.size}vmin`,
              height: `${target.size}vmin`
            }}
            aria-hidden="true"
          >
            <span className="gesture-target-visual">{gestureVisual(currentChallenge?.id)}</span>
            {gestureMatched && (
              <svg className="gesture-progress-ring" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="47" />
                <circle cx="50" cy="50" r="47" style={{ strokeDasharray: `${holdProgress * 2.95} 295` }} />
              </svg>
            )}
          </div>
          <div className="gesture-topbar">
            <div>
              <strong>{currentChallenge?.prompt ?? "Gesture complete"}</strong>
              <span>{modelReady ? fullscreenInstruction(metric, handInsideTarget, gestureMatched) : "Loading hand model"}</span>
            </div>
            <button className="icon-button" type="button" onClick={stopCamera} aria-label="Close gesture camera">
              <X size={22} />
            </button>
          </div>
          <div className="gesture-debug-pill">
            <Hand size={16} />
            {currentChallenge ? `${currentChallenge.prompt} | ${metric.handPresent ? `${metric.gesture ?? `${metric.fingerCount} fingers`} detected` : "Show your hand"}` : "Gesture complete"}
          </div>
        </div>
      )}
    </div>
  );
}

function loadHandsScript() {
  if (window.Hands) return Promise.resolve();
  const existing = document.querySelector<HTMLScriptElement>("script[data-mediapipe-hands]");
  if (existing) {
    return new Promise<void>((resolve, reject) => {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Hands script failed")), { once: true });
    });
  }
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/mediapipe/hands/hands.js";
    script.async = true;
    script.dataset.mediapipeHands = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Hands script failed"));
    document.head.appendChild(script);
  });
}

function randomTarget(): Target {
  const size = 40;
  const margin = size / 2 + 6;
  return {
    left: margin + Math.random() * (100 - margin * 2),
    top: margin + Math.random() * (100 - margin * 2),
    size
  };
}

function readGestureMetric(landmarks: NormalizedLandmarkList): GestureMetric {
  const center = landmarks.reduce(
    (acc, landmark) => ({ x: acc.x + landmark.x, y: acc.y + landmark.y }),
    { x: 0, y: 0 }
  );
  const centerX = center.x / landmarks.length;
  const centerY = center.y / landmarks.length;
  const fingers = extendedFingers(landmarks);
  const fingerCount = Object.values(fingers).filter(Boolean).length;
  const gesture = classifyGesture(landmarks, fingers, fingerCount);

  return {
    handPresent: true,
    centerX,
    centerY,
    fingerCount,
    gesture
  };
}

function extendedFingers(landmarks: NormalizedLandmarkList) {
  const palmWidth = distance(landmarks[5], landmarks[17]);
  return {
    thumb: distance(landmarks[4], landmarks[9]) > palmWidth * 0.72,
    index: landmarks[8].y < landmarks[6].y - 0.02,
    middle: landmarks[12].y < landmarks[10].y - 0.02,
    ring: landmarks[16].y < landmarks[14].y - 0.02,
    pinky: landmarks[20].y < landmarks[18].y - 0.02
  };
}

function classifyGesture(
  landmarks: NormalizedLandmarkList,
  fingers: { thumb: boolean; index: boolean; middle: boolean; ring: boolean; pinky: boolean },
  fingerCount: number
) {
  const thumbIndexDistance = distance(landmarks[4], landmarks[8]);
  const palmWidth = Math.max(distance(landmarks[5], landmarks[17]), 0.001);
  const ok = thumbIndexDistance < palmWidth * 0.34 && fingers.middle && fingers.ring && fingers.pinky;
  if (ok) return "ok";

  const thumbDown = fingers.thumb && !fingers.index && !fingers.middle && !fingers.ring && !fingers.pinky && landmarks[4].y > landmarks[0].y + 0.05;
  if (thumbDown) return "thumb_down";

  const love = fingers.thumb && fingers.index && !fingers.middle && !fingers.ring && fingers.pinky;
  if (love) return "i_love_you";

  if (fingerCount >= 1 && fingerCount <= 5) return String(fingerCount);
  return null;
}

function matchesGesture(challengeId: string, metric: GestureMetric) {
  if (challengeId === "one") return metric.fingerCount === 1;
  if (challengeId === "two") return metric.fingerCount === 2;
  if (challengeId === "three") return metric.fingerCount === 3;
  if (challengeId === "four") return metric.fingerCount === 4;
  if (challengeId === "five") return metric.fingerCount === 5;
  return metric.gesture === challengeId;
}

function isInsideTarget(metric: GestureMetric, target: Target) {
  const targetX = target.left / 100;
  const targetY = target.top / 100;
  const radius = target.size / 200;
  return Math.hypot(metric.centerX - targetX, metric.centerY - targetY) <= radius;
}

function distance(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function fullscreenInstruction(metric: GestureMetric, inside: boolean, matched: boolean) {
  if (matched) return "Matched. Passing gesture...";
  if (!metric.handPresent) return "Show your hand inside the circle.";
  if (!inside) return "Move your hand into the circle.";
  return "Gesture detected in circle. Adjust fingers to match the prompt.";
}

function gestureVisual(challengeId?: string) {
  if (challengeId === "one") return "1️⃣";
  if (challengeId === "two") return "2️⃣";
  if (challengeId === "three") return "3️⃣";
  if (challengeId === "four") return "4️⃣";
  if (challengeId === "five") return "5️⃣";
  if (challengeId === "ok") return "👌";
  if (challengeId === "thumb_down") return "👎";
  if (challengeId === "i_love_you") return "🤟";
  return "✓";
}
