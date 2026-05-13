export type ImageOptimizeOptions = {
  maxWidth: number;
  quality: number;
  filename: string;
};

export async function optimizeImageForUpload(file: File | Blob, options: ImageOptimizeOptions): Promise<File | Blob> {
  if (!file.type.startsWith("image/")) return file;
  const image = await loadImage(file).catch(() => null);
  if (!image) return file;
  const scale = image.width > options.maxWidth ? options.maxWidth / image.width : 1;
  if (scale >= 1 && file.size < 950_000) return file;

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) return file;
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const blob = await canvasToBlob(canvas, options.quality);
  if (!blob || blob.size >= file.size) return file;
  return new File([blob], options.filename, { type: "image/jpeg" });
}

function loadImage(file: File | Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Image could not be prepared for upload."));
    };
    image.src = url;
  });
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", quality);
  });
}
