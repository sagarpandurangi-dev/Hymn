import AsyncStorage from "@react-native-async-storage/async-storage";

/** Welcome wizard persistence: the step reached, and which saves already went through. */
export const WELCOME_STEP_KEY = "hymn.welcome.step";
const SAVED_KEY = "hymn.welcome.saved";
export const WELCOME_OWNER_KEY = "hymn.welcome.user";
export const FOCUS_AREAS_KEY = "hymn.focusAreas";

export async function loadWelcomeStep(): Promise<number> {
  const raw = await AsyncStorage.getItem(WELCOME_STEP_KEY).catch(() => null);
  const n = raw ? parseInt(raw, 10) : 0;
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

export async function saveWelcomeStep(step: number): Promise<void> {
  await AsyncStorage.setItem(WELCOME_STEP_KEY, String(step)).catch(() => undefined);
}

/** Keys of saves already sent (e.g. "work", "sleep:monday") so Back/resume never duplicates them. */
export async function getSaved(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(SAVED_KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export async function markSaved(key: string): Promise<void> {
  const cur = await getSaved();
  if (!cur.includes(key)) await AsyncStorage.setItem(SAVED_KEY, JSON.stringify([...cur, key])).catch(() => undefined);
}

export async function clearWelcome(): Promise<void> {
  await AsyncStorage.multiRemove([WELCOME_STEP_KEY, SAVED_KEY]).catch(() => undefined);
}

export const todayISO = (): string => {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export const WEEK_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] as const;
export const WEEK_DAY_SHORT: Record<string, string> = {
  monday: "Mon", tuesday: "Tue", wednesday: "Wed", thursday: "Thu", friday: "Fri", saturday: "Sat", sunday: "Sun",
};
