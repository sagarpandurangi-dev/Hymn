import { Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

const EMERGENT_AUTH_URL = "https://auth.emergentagent.com/";

function parseSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  // Try hash fragment first, then query.
  const hashMatch = url.match(/[#&]session_id=([^&]+)/);
  if (hashMatch) return decodeURIComponent(hashMatch[1]);
  const queryMatch = url.match(/[?&]session_id=([^&]+)/);
  if (queryMatch) return decodeURIComponent(queryMatch[1]);
  return null;
}

export function extractSessionIdFromWebUrl(): string | null {
  if (Platform.OS !== "web" || typeof window === "undefined") return null;
  const fromHash = parseSessionId(window.location.hash);
  const fromQuery = parseSessionId(window.location.search);
  return fromHash || fromQuery;
}

export function clearWebSessionIdFromUrl() {
  if (Platform.OS !== "web" || typeof window === "undefined") return;
  try {
    window.history.replaceState(null, "", window.location.pathname);
  } catch {
    // ignore
  }
}

/**
 * Start Google auth flow. Returns extracted session_id on mobile.
 * On web, redirects the browser (no return value).
 */
export async function startGoogleAuth(): Promise<string | null> {
  if (Platform.OS === "web") {
    if (typeof window === "undefined") return null;
    const redirectUrl = window.location.origin + "/";
    const authUrl = `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;
    window.location.href = authUrl;
    return null;
  }
  const redirectUrl = Linking.createURL("auth");
  const authUrl = `${EMERGENT_AUTH_URL}?redirect=${encodeURIComponent(redirectUrl)}`;
  const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
  if (result.type !== "success" || !result.url) return null;
  return parseSessionId(result.url);
}

export async function getInitialSessionIdMobile(): Promise<string | null> {
  if (Platform.OS === "web") return null;
  const url = await Linking.getInitialURL();
  return parseSessionId(url);
}
