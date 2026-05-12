import { Camera, CameraOff, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface CameraCaptureProps {
  label: string;
  overlay?: "document" | "face" | "hand";
  onCapture: (blob: Blob) => void;
  disabled?: boolean;
}

export function CameraCapture({ label, overlay = "face", onCapture, disabled = false }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startCamera = async () => {
    if (disabled) return;
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
      setError("Camera permission is required for this verification step.");
      setCameraReady(false);
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraReady(false);
  };

  const capture = () => {
    if (disabled) return;
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) onCapture(blob);
    }, "image/jpeg", 0.92);
  };

  useEffect(() => {
    return () => stopCamera();
  }, []);

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
      </div>
      {error && <p className="form-error" aria-live="polite">{error}</p>}
      <div className="camera-actions">
        <button className="secondary-button" type="button" onClick={cameraReady ? stopCamera : startCamera} disabled={disabled}>
          {cameraReady ? <CameraOff size={18} /> : <Camera size={18} />}
          {cameraReady ? "Stop camera" : "Open camera"}
        </button>
        <button className="primary-button" type="button" onClick={capture} disabled={disabled || !cameraReady}>
          <RefreshCw size={18} />
          Capture
        </button>
      </div>
    </section>
  );
}
