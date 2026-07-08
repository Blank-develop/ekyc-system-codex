export type LightingStatus = {
  level: "good" | "warning";
  message: string;
};

const LIGHTING_SAMPLE_SIZE = 96;

export function analyzeVideoLighting(video: HTMLVideoElement | null): LightingStatus | null {
  if (!video || video.readyState < 2 || video.videoWidth === 0 || video.videoHeight === 0) return null;

  const canvas = document.createElement("canvas");
  const scale = Math.min(
    1,
    LIGHTING_SAMPLE_SIZE / Math.max(video.videoWidth, video.videoHeight)
  );
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;

  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;
  let overexposedPixels = 0;
  let underexposedPixels = 0;
  const pixelCount = data.length / 4;

  for (let index = 0; index < data.length; index += 4) {
    const luminance = (0.2126 * data[index] + 0.7152 * data[index + 1] + 0.0722 * data[index + 2]) / 255;
    luminanceTotal += luminance;
    luminanceSquaredTotal += luminance * luminance;
    if (luminance > 0.92) overexposedPixels += 1;
    if (luminance < 0.08) underexposedPixels += 1;
  }

  const mean = luminanceTotal / Math.max(pixelCount, 1);
  const variance = luminanceSquaredTotal / Math.max(pixelCount, 1) - mean * mean;
  const contrast = Math.sqrt(Math.max(variance, 0));
  const overexposedRatio = overexposedPixels / Math.max(pixelCount, 1);
  const underexposedRatio = underexposedPixels / Math.max(pixelCount, 1);

  if (mean < 0.2 || underexposedRatio > 0.42) {
    return { level: "warning", message: "Lighting is too dark. Face a soft light before capture." };
  }
  if (mean > 0.82 || overexposedRatio > 0.36) {
    return { level: "warning", message: "Lighting is too bright. Move away from glare or backlight." };
  }
  if (contrast < 0.09) {
    return { level: "warning", message: "Lighting is too flat. Add gentle front light and avoid shadows." };
  }

  return { level: "good", message: "Lighting looks good for capture." };
}
