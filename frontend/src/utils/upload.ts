import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";

export type UploadFile = { uri: string; name: string; mimeType?: string | null };

/** What JSON upload endpoints expect: send as {image_base64 | file_base64, media_type}. */
export type PickedFile = { base64: string; mediaType: string };

const MAX_IMAGE_SIDE = 1024;

async function readBase64(uri: string): Promise<string> {
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }
  return FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 });
}

/**
 * Pick a photo from the library, shrink it to at most 1024 px on the long side,
 * save as JPEG (quality 0.7) and return it as base64. Null if the user cancels.
 * Uses the system photo picker, which needs no photo-library permission.
 */
export async function pickImage(): Promise<PickedFile | null> {
  const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
  const asset = res.canceled ? null : res.assets?.[0];
  if (!asset) return null;
  let w = asset.width || 0;
  let h = asset.height || 0;
  if (!w || !h) {
    // Picker didn't report a size: measure it before deciding to resize.
    const probeCtx = ImageManipulator.manipulate(asset.uri);
    const probe = await probeCtx.renderAsync();
    w = probe.width;
    h = probe.height;
    probe.release();
    probeCtx.release();
  }
  const ctx = ImageManipulator.manipulate(asset.uri);
  if (Math.max(w, h) > MAX_IMAGE_SIDE) {
    ctx.resize(w >= h ? { width: MAX_IMAGE_SIDE } : { height: MAX_IMAGE_SIDE });
  }
  const rendered = await ctx.renderAsync();
  const saved = await rendered.saveAsync({ format: SaveFormat.JPEG, compress: 0.7 });
  rendered.release();
  ctx.release();
  return { base64: await readBase64(saved.uri), mediaType: "image/jpeg" };
}

/** Pick a PDF and return it as base64. Null if the user cancels. */
export async function pickPdf(): Promise<PickedFile | null> {
  const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true, multiple: false });
  const asset = res.canceled ? null : res.assets?.[0];
  if (!asset) return null;
  return { base64: await readBase64(asset.uri), mediaType: "application/pdf" };
}

/**
 * Builds a multipart form for upload. The file is read into a Blob
 * (expo/fetch on native, window fetch on web) — never `{ uri, name, type }`.
 * Empty string fields are omitted.
 */
export async function uploadForm(
  fileField: string,
  file: UploadFile,
  fields: Record<string, string | undefined> = {},
): Promise<FormData> {
  const blob =
    Platform.OS === "web"
      ? await (await fetch(file.uri)).blob()
      : await (await expoFetch(file.uri)).blob();
  const form = new FormData();
  form.append(fileField, blob as any, file.name);
  for (const [key, value] of Object.entries(fields)) {
    if (value) form.append(key, value);
  }
  return form;
}
