export function cameraUnavailableMessage() {
  const host = window.location.hostname;
  const isLocalhost = host === "localhost" || host === "127.0.0.1" || host === "::1";
  if (!window.isSecureContext && !isLocalhost) {
    return "Camera is blocked on this network URL. Open the app with HTTPS, or use localhost on the same device.";
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return "This browser does not expose camera access here. Use HTTPS and a modern browser, then allow camera permission.";
  }
  return null;
}

export function cameraErrorMessage(error: unknown, fallback: string) {
  const supportMessage = cameraUnavailableMessage();
  if (supportMessage) return supportMessage;
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "PermissionDeniedError") {
      return "Camera permission was denied. Allow camera access in the browser settings and try again.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "No camera was found on this device.";
    }
    if (error.name === "NotReadableError" || error.name === "TrackStartError") {
      return "The camera is already in use by another app or browser tab.";
    }
  }
  return fallback;
}
