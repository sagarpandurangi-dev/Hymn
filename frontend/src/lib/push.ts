import { useEffect, useState } from "react";
import { Platform } from "react-native";
import { useRouter } from "expo-router";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { api } from "./api";

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

/**
 * Opens the screen a nudge points at (`data.screen` + ids). `data.for` means the
 * nudge is about someone the user looks after: open Health for that person.
 * Unknown screens open Today.
 */
export function openNudgeScreen(router: ReturnType<typeof useRouter>, data: unknown): void {
  const d = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const screen = typeof d.screen === "string" ? d.screen : "";
  const id = (k: string) => (typeof d[k] === "string" && d[k] ? String(d[k]) : "");
  const q = (params: Record<string, string>) => {
    const s = Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    return s ? `?${s}` : "";
  };

  const forPerson = id("for");
  if (forPerson) {
    const section = screen.startsWith("health/") ? screen.slice(7) : "";
    router.push(`/life/health${q({ for: forPerson, section })}` as any);
    return;
  }

  let path: string;
  if (screen === "inbox/review" || screen === "inbox/patterns") path = `/${screen}`;
  else if (screen === "plans") path = `/(tabs)/planning-space${q({ plan_id: id("plan_id") })}`;
  else if (screen === "health") path = "/life/health";
  else if (screen.startsWith("health/")) path = `/life/health${q({ section: screen.slice(7) })}`;
  else if (screen === "habits") path = `/life/health${q({ section: "habits", habit_id: id("habit_id") })}`;
  else if (screen === "people") path = `/life/family${q({ person_id: id("person_id") })}`;
  else if (screen === "learning") path = `/(tabs)/knowledge${q({ journey_id: id("journey_id") })}`;
  else if (screen === "work") path = `/life/work${q({ role_id: id("role_id") })}`;
  else path = "/(tabs)/today";
  router.push(path as any);
}

/**
 * Opens a nudge's target when a notification is tapped, including the tap that
 * launched the app. Navigation waits until `ready` (signed in and set up).
 */
export function useNotificationTapNavigation(ready: boolean) {
  const router = useRouter();
  const [pending, setPending] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (Platform.OS === "web") return;
    const take = (r: Notifications.NotificationResponse | null) => {
      if (r) setPending((r.notification.request.content.data as Record<string, unknown>) ?? {});
    };
    Notifications.getLastNotificationResponseAsync().then((r) => {
      take(r);
      if (r) Notifications.clearLastNotificationResponseAsync().catch(() => undefined);
    }).catch(() => undefined);
    const sub = Notifications.addNotificationResponseReceivedListener(take);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (!ready || !pending) return;
    openNudgeScreen(router, pending);
    setPending(null);
  }, [ready, pending, router]);
}
