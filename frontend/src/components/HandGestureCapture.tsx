import type { HandsConfig, InputMap, NormalizedLandmarkList, Options, Results, ResultsListener } from "@mediapipe/hands";
import { Camera, CameraOff, Check, Hand, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Challenge } from "../lib/api";
import { cameraErrorMessage, cameraUnavailableMessage } from "../lib/camera";

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
  fingers: FingerState;
};

type FingerState = {
  thumb: boolean;
  index: boolean;
  middle: boolean;
  ring: boolean;
  pinky: boolean;
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
  gesture: null,
  fingers: {
    thumb: false,
    index: false,
    middle: false,
    ring: false,
    pinky: false
  }
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
      const supportMessage = cameraUnavailableMessage();
      if (supportMessage) {
        setError(supportMessage);
        setCameraReady(false);
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      streamRef.current = stream;
      setCameraReady(true);
      setFullscreen(true);
    } catch (error) {
      setError(cameraErrorMessage(error, "Camera permission is required for the gesture challenge."));
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
          // Lite landmark model (0) instead of full (1): ~3 MB smaller first
          // load and faster per-frame inference, accurate enough for the
          // finger-count / palm / fist style gesture challenge.
          modelComplexity: 0,
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
        <button className="primary-button wide" type="button" onClick={startCamera} disabled={!currentChallenge}>
          <Camera size={18} />
          Open full-screen camera
        </button>
        {!modelReady && !error && (
          <p className="gesture-loading-note" aria-live="polite">
            Preparing the hand detector… you can open the camera now; detection starts in a moment.
          </p>
        )}
        {error && <p className="form-error" aria-live="polite">{error}</p>}
      </div>

      <div className="gesture-list" aria-label="Hand gesture challenges">
        {challenges.map((challenge) => {
          const isCurrent = currentChallenge?.id === challenge.id;
          return (
            <div className={`gesture-card ${challenge.passed ? "passed" : ""} ${isCurrent ? "current" : ""}`} key={challenge.id}>
              <span>
                <GestureVisual className="gesture-card-visual" challengeId={challenge.id} />
                {challenge.passed ? <Check size={16} /> : challenge.prompt}
              </span>
              <small>{challenge.passed ? "Completed" : isCurrent ? challenge.instruction : "Waiting for previous gesture"}</small>
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
            <GestureVisual className="gesture-target-visual" challengeId={currentChallenge?.id} />
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
              <span>{modelReady ? fullscreenInstruction(metric, handInsideTarget, gestureMatched, currentChallenge?.instruction) : "Loading hand model"}</span>
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
    gesture,
    fingers
  };
}

function extendedFingers(landmarks: NormalizedLandmarkList): FingerState {
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
  fingers: FingerState,
  fingerCount: number
) {
  const thumbIndexDistance = distance(landmarks[4], landmarks[8]);
  const palmWidth = Math.max(distance(landmarks[5], landmarks[17]), 0.001);

  // All fingertips gathered on the thumb tip; must run before the OK check
  // because the pinched pose also brings thumb and index together.
  const pinched =
    fingerCount >= 2 &&
    [8, 12, 16, 20].every((tip) => distance(landmarks[tip], landmarks[4]) < palmWidth * 0.55);
  if (pinched) return "pinched_fingers";

  const ok = thumbIndexDistance < palmWidth * 0.38;
  if (ok) return "ok";

  const crossed =
    fingers.index && fingers.middle && !fingers.ring && !fingers.pinky &&
    distance(landmarks[8], landmarks[12]) < palmWidth * 0.3;
  if (crossed) return "crossed_fingers";

  const lShape = fingers.thumb && fingers.index && !fingers.middle && !fingers.ring && !fingers.pinky;
  if (lShape) return "l_shape";

  const thumbOnly = fingers.thumb && !fingers.index && !fingers.middle && !fingers.ring && !fingers.pinky;
  const thumbUp = thumbOnly && landmarks[4].y < landmarks[0].y - 0.03;
  if (thumbUp) return "thumb_up";

  const thumbDown = fingers.thumb && !fingers.index && !fingers.middle && !fingers.ring && !fingers.pinky && landmarks[4].y > landmarks[0].y + 0.05;
  if (thumbDown) return "thumb_down";

  const love = fingers.thumb && fingers.index && !fingers.middle && !fingers.ring && fingers.pinky;
  if (love) return "i_love_you";

  const callMe = fingers.thumb && !fingers.index && !fingers.middle && !fingers.ring && fingers.pinky;
  if (callMe) return "call_me";

  const rockOn = !fingers.thumb && fingers.index && !fingers.middle && !fingers.ring && fingers.pinky;
  if (rockOn) return "rock_on";

  if (fingerCount >= 1 && fingerCount <= 5) return String(fingerCount);
  if (fingerCount === 0) return "fist";
  return null;
}

function matchesGesture(challengeId: string, metric: GestureMetric) {
  if (["one", "point"].includes(challengeId)) return metric.fingerCount === 1;
  if (["two", "peace", "victory"].includes(challengeId)) return metric.fingerCount === 2;
  if (challengeId === "three") return metric.fingerCount === 3;
  if (challengeId === "four") return metric.fingerCount === 4;
  if (["five", "open_palm", "high_five", "stop"].includes(challengeId)) return metric.fingerCount >= 4;
  if (challengeId === "fist") return metric.fingerCount === 0 || metric.gesture === "fist";
  if (["ok", "pinch", "small_ok"].includes(challengeId)) return metric.gesture === "ok";
  if (challengeId === "thumb_up") return metric.gesture === "thumb_up" || (metric.fingers.thumb && metric.fingerCount <= 1);
  if (challengeId === "thumb_down") return metric.gesture === "thumb_down" || (metric.fingers.thumb && metric.fingerCount <= 1);
  if (challengeId === "rock_on") return metric.gesture === "rock_on" || metric.gesture === "i_love_you" || (metric.fingers.index && metric.fingers.pinky);
  if (challengeId === "call_me") return metric.gesture === "call_me" || (metric.fingers.thumb && metric.fingers.pinky);
  if (challengeId === "l_shape") {
    return metric.gesture === "l_shape" || (metric.fingers.thumb && metric.fingers.index && !metric.fingers.middle && !metric.fingers.ring && !metric.fingers.pinky);
  }
  if (challengeId === "pinched_fingers") return metric.gesture === "pinched_fingers";
  if (challengeId === "crossed_fingers") return metric.gesture === "crossed_fingers";
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

function fullscreenInstruction(metric: GestureMetric, inside: boolean, matched: boolean, instruction?: string) {
  if (matched) return "Matched. Passing gesture...";
  if (!metric.handPresent) return "Show your hand inside the circle.";
  if (!inside) return "Move your hand into the circle.";
  return instruction ?? "Gesture detected in circle. Adjust fingers to match the prompt.";
}

function gestureVisual(challengeId?: string) {
  if (challengeId === "one") return "1️⃣";
  if (challengeId === "two") return "2️⃣";
  if (challengeId === "three") return "3️⃣";
  if (challengeId === "four") return "4️⃣";
  if (challengeId === "five") return "5️⃣";
  if (challengeId === "point") return "☝️";
  if (challengeId === "peace") return "✌️";
  if (challengeId === "victory") return "✌️";
  if (challengeId === "open_palm") return "✋";
  if (challengeId === "high_five") return "🖐️";
  if (challengeId === "stop") return "✋";
  if (challengeId === "fist") return "✊";
  if (challengeId === "thumb_up") return "👍";
  if (challengeId === "ok") return "👌";
  if (challengeId === "pinch") return "👌";
  if (challengeId === "small_ok") return "👌";
  if (challengeId === "rock_on") return "🤘";
  if (challengeId === "call_me") return "🤙";
  if (challengeId === "thumb_down") return "👎";
  if (challengeId === "i_love_you") return "🤟";
  if (challengeId === "l_shape") return "L";
  if (challengeId === "pinched_fingers") return "🤌";
  if (challengeId === "crossed_fingers") return "🤞";
  return "✓";
}

// Renders the gesture reference image from /gestures/<id>.png (drop your generated
// PNGs into frontend/public/gestures/). Falls back to the emoji automatically if an
// image is missing, so nothing breaks while images are still being added.
function GestureVisual({ challengeId, className }: { challengeId?: string; className: string }) {
  const [errored, setErrored] = useState(false);
  useEffect(() => setErrored(false), [challengeId]);
  if (!challengeId || errored) {
    return (
      <span className={className} aria-hidden="true">
        {gestureVisual(challengeId)}
      </span>
    );
  }
  return (
    <img
      className={className}
      src={`/gestures/${challengeId}.png`}
      alt=""
      aria-hidden="true"
      onError={() => setErrored(true)}
    />
  );
}
