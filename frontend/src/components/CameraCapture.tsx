import { Camera, CameraOff, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cameraErrorMessage, cameraUnavailableMessage } from "../lib/camera";
import { analyzeVideoLighting, type LightingStatus } from "../lib/lighting";

interface CameraCaptureProps {
  label: string;
  overlay?: "document" | "face" | "hand";
  facingMode?: "user" | "environment";
  onCapture: (blob: Blob) => void;
  onCaptureFrames?: (blobs: Blob[]) => void;
  disabled?: boolean;
  maxCaptureWidth?: number;
  jpegQuality?: number;
  burstCount?: number;
  burstIntervalMs?: number;
  captureLabel?: string;
  hint?: string;
}

export function CameraCapture({
  label,
  overlay = "face",
  facingMode = "user",
  onCapture,
  onCaptureFrames,
  disabled = false,
  maxCaptureWidth,
  jpegQuality = 0.92,
  burstCount = 1,
  burstIntervalMs = 250,
  captureLabel = "Capture",
  hint
}: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [burstProgress, setBurstProgress] = useState(0);
  const [lightingStatus, setLightingStatus] = useState<LightingStatus | null>(null);
  const [lightingOverride, setLightingOverride] = useState(false);

  const startCamera = async () => {
    if (disabled) return;
    try {
      setError(null);
      const supportMessage = cameraUnavailableMessage();
      if (supportMessage) {
        setError(supportMessage);
        setCameraReady(false);
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facingMode }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setCameraReady(true);
    } catch (error) {
      setError(cameraErrorMessage(error, "Camera permission is required for this verification step."));
      setCameraReady(false);
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraReady(false);
    setLightingStatus(null);
    setLightingOverride(false);
  };

  const captureFrame = () => new Promise<Blob | null>((resolve) => {
    const video = videoRef.current;
    if (!video) {
      resolve(null);
      return;
    }
    const canvas = document.createElement("canvas");
    const sourceWidth = video.videoWidth || 1280;
    const sourceHeight = video.videoHeight || 720;
    const scale = maxCaptureWidth && sourceWidth > maxCaptureWidth ? maxCaptureWidth / sourceWidth : 1;
    canvas.width = Math.round(sourceWidth * scale);
    canvas.height = Math.round(sourceHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) {
      resolve(null);
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      resolve(blob);
    }, "image/jpeg", jpegQuality);
  });

  const capture = async () => {
    if (disabled || capturing) return;
    if (burstCount > 1 && onCaptureFrames) {
      setCapturing(true);
      setBurstProgress(0);
      const frames: Blob[] = [];
      for (let index = 0; index < burstCount; index += 1) {
        if (index > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, burstIntervalMs));
        }
        const blob = await captureFrame();
        if (blob) frames.push(blob);
        setBurstProgress(index + 1);
      }
      setCapturing(false);
      setBurstProgress(0);
      if (frames.length) onCaptureFrames(frames);
      return;
    }
    const blob = await captureFrame();
    if (blob) onCapture(blob);
  };

  useEffect(() => {
    return () => stopCamera();
  }, []);

  useEffect(() => {
    if (!cameraReady) return;

    const interval = window.setInterval(() => {
      const status = analyzeVideoLighting(videoRef.current);
      setLightingStatus(status);
      // Once lighting recovers, re-arm the gate so a later bad spell blocks again.
      if (status && status.level === "good") setLightingOverride(false);
    }, 450);

    return () => window.clearInterval(interval);
  }, [cameraReady]);

  const lightingBlocked = cameraReady && !capturing && lightingStatus?.level === "warning" && !lightingOverride;

  return (
    <section className="camera-shell" aria-label={label}>
      <div className={`camera-frame camera-frame-${overlay}`}>
        <video ref={videoRef} autoPlay playsInline muted />
        <div className={`capture-overlay capture-overlay-${overlay}`} aria-hidden="true" />
        {!cameraReady && (
          <div className="camera-empty">
            <CameraOff size={30} />
            <span>Camera is off</span>
          </div>
        )}
        {cameraReady && !capturing && lightingStatus?.level === "warning" && (
          <div className="camera-lighting-warning" role="status" aria-live="polite">
            {lightingStatus.message}
          </div>
        )}
      </div>
      {error && <p className="form-error" aria-live="polite">{error}</p>}
      <div className="camera-actions">
        <button className="secondary-button" type="button" onClick={cameraReady ? stopCamera : startCamera} disabled={disabled}>
          {cameraReady ? <CameraOff size={18} /> : <Camera size={18} />}
          {cameraReady ? "Stop camera" : "Open camera"}
        </button>
        <button className="primary-button" type="button" onClick={capture} disabled={disabled || !cameraReady || capturing || lightingBlocked}>
          <RefreshCw size={18} />
          {capturing ? `Capturing ${burstProgress}/${burstCount}` : lightingBlocked ? "Fix lighting to capture" : captureLabel}
        </button>
      </div>
      {lightingBlocked && (
        <button className="camera-capture-anyway" type="button" onClick={() => setLightingOverride(true)}>
          Capture anyway
        </button>
      )}
      {capturing && (
        <div className="camera-burst-status" role="status" aria-live="polite">
          Keep your face live and steady while Kyron captures a short burst.
        </div>
      )}
      {hint && cameraReady && !capturing && (
        <div className="camera-hint" role="note">
          {lightingStatus?.level === "warning" ? lightingStatus.message : hint}
        </div>
      )}
    </section>
  );
}
