import { L } from "./i18n";

export function cameraUnavailableMessage() {
  const host = window.location.hostname;
  const isLocalhost = host === "localhost" || host === "127.0.0.1" || host === "::1";
  if (!window.isSecureContext && !isLocalhost) {
    return L("ກ້ອງຖືກບລັອກໃນທີ່ຢູ່ນີ້. ກະລຸນາເປີດແອັບດ້ວຍ HTTPS ຫຼື ໃຊ້ localhost ໃນອຸປະກອນດຽວກັນ.", "Camera is blocked on this network URL. Open the app with HTTPS, or use localhost on the same device.");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return L("ບຣາວເຊີນີ້ບໍ່ອະນຸຍາດໃຫ້ໃຊ້ກ້ອງ. ກະລຸນາໃຊ້ HTTPS ແລະ ບຣາວເຊີລຸ້ນໃໝ່ ແລ້ວອະນຸຍາດໃຊ້ກ້ອງ.", "This browser does not expose camera access here. Use HTTPS and a modern browser, then allow camera permission.");
  }
  return null;
}

export function cameraErrorMessage(error: unknown, fallback: string) {
  const supportMessage = cameraUnavailableMessage();
  if (supportMessage) return supportMessage;
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "PermissionDeniedError") {
      return L("ການອະນຸຍາດໃຊ້ກ້ອງຖືກປະຕິເສດ. ກະລຸນາອະນຸຍາດໃນການຕັ້ງຄ່າບຣາວເຊີ ແລ້ວລອງໃໝ່.", "Camera permission was denied. Allow camera access in the browser settings and try again.");
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return L("ບໍ່ພົບກ້ອງໃນອຸປະກອນນີ້.", "No camera was found on this device.");
    }
    if (error.name === "NotReadableError" || error.name === "TrackStartError") {
      return L("ກ້ອງກຳລັງຖືກໃຊ້ໂດຍແອັບ ຫຼື ແຖບອື່ນ.", "The camera is already in use by another app or browser tab.");
    }
  }
  return fallback;
}
