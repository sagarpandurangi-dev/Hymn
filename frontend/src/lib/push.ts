import { useEffect, useState } from "react";
import { Platform } from "react-native";
import { useRouter } from "expo-router";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { api } from "./api";

/** Screens a nudge may open, as sent in `data.screen`. */
const NUDGE_SCREENS = ["inbox/review", "inbox/patterns"] as const;

let registeredToken: string | null = null;

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

/**
 * Registers this device for nudges. Skips silently on web, simulators,
 * denied permission, a missing EAS project ID, or any registration error.
 */
export async function registerForPushNotifications(): Promise<void> {
  if (Platform.OS === "web" || !Device.isDevice) return;
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Default",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }
    const current = await Notifications.getPermissionsAsync();
    let status = current.status;
    if (status !== "granted" && current.canAskAgain) {
      status = (await Notifications.requestPermissionsAsync()).status;
    }
    if (status !== "granted") return;
    const projectId =
      (Constants.expoConfig?.extra as any)?.eas?.projectId ?? Constants.easConfig?.projectId;
    if (!projectId) return;
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    await api.registerNudgeDevice({ token, platform: Platform.OS === "ios" ? "ios" : "android" });
    registeredToken = token;
  } catch {
    // Push is optional — skip silently (e.g. Expo Go, no network).
  }
}

/** Removes this device's token from the backend. Call before clearing the session. */
export async function unregisterPushDevice(): Promise<void> {
  const token = registeredToken;
  if (!token) return;
  registeredToken = null;
  try {
    await api.unregisterNudgeDevice(token);
  } catch {
    // Logout must proceed even if this fails.
  }
}

/** Opens a nudge's `data.screen` when it is one of the known targets. */
export function openNudgeScreen(router: ReturnType<typeof useRouter>, screen: unknown): boolean {
  if (typeof screen !== "string" || !(NUDGE_SCREENS as readonly string[]).includes(screen)) return false;
  router.push(`/${screen}` as any);
  return true;
}

/**
 * Opens `data.screen` when a notification is tapped, including the tap that
 * launched the app. Navigation waits until `ready` (signed in and set up).
 */
export function useNotificationTapNavigation(ready: boolean) {
  const router = useRouter();
  const [pendingScreen, setPendingScreen] = useState<unknown>(null);

  useEffect(() => {
    if (Platform.OS === "web") return;
    const take = (r: Notifications.NotificationResponse | null) => {
      if (r) setPendingScreen(r.notification.request.content.data?.screen ?? null);
    };
    Notifications.getLastNotificationResponseAsync().then((r) => {
      take(r);
      if (r) Notifications.clearLastNotificationResponseAsync().catch(() => undefined);
    }).catch(() => undefined);
    const sub = Notifications.addNotificationResponseReceivedListener(take);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (!ready || !pendingScreen) return;
    openNudgeScreen(router, pendingScreen);
    setPendingScreen(null);
  }, [ready, pendingScreen, router]);
}
