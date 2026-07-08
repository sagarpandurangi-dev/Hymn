import { Platform } from "react-native";

/**
 * Foundation for the Android "Display over other apps" (SYSTEM_ALERT_WINDOW) permission.
 * The actual overlay UI + native module will be implemented in a later iteration.
 *
 * This module abstracts the permission surface so callers can:
 *   - detect whether the platform can host an overlay
 *   - inspect the currently-known status (persisted locally)
 *   - request the permission (currently a stub — always throws NotYetSupported on native)
 *
 * Once the native side is wired (e.g. via a config-plugin or a native module exposing
 * Settings.canDrawOverlays / ACTION_MANAGE_OVERLAY_PERMISSION), replace the stub in
 * `requestPermission` and return the true status.
 */

const STORAGE_KEY = "hymn_overlay_permission_status";

export type OverlayPermissionStatus = "unsupported" | "unknown" | "granted" | "denied" | "not_yet_supported";

export function isOverlayCapable(): boolean {
  return Platform.OS === "android";
}

export async function getOverlayPermissionStatus(): Promise<OverlayPermissionStatus> {
  if (!isOverlayCapable()) return "unsupported";
  // Persistent state is stored via existing storage utility; kept simple to avoid coupling here.
  try {
    const { storage } = await import("@/src/utils/storage");
    const value = await storage.getItem<OverlayPermissionStatus | null>(STORAGE_KEY, null);
    return value || "unknown";
  } catch {
    return "unknown";
  }
}

export async function setOverlayPermissionStatus(status: OverlayPermissionStatus): Promise<void> {
  try {
    const { storage } = await import("@/src/utils/storage");
    await storage.setItem(STORAGE_KEY, status);
  } catch {
    // ignore — best-effort
  }
}

/**
 * Placeholder for the actual request flow. Real implementation must:
 *   - check Settings.canDrawOverlays()
 *   - if false, launch Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION) so the user
 *     can grant it in Android settings, then re-check on foreground
 *   - persist the final status via setOverlayPermissionStatus
 */
export async function requestOverlayPermission(): Promise<OverlayPermissionStatus> {
  if (!isOverlayCapable()) return "unsupported";
  await setOverlayPermissionStatus("not_yet_supported");
  return "not_yet_supported";
}
