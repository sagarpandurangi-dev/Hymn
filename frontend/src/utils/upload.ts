import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

export type UploadFile = { uri: string; name: string; mimeType?: string | null };

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
