/**
 * Shared health UI: screen header, red-flag panel, status helpers.
 * Tone: calm and plain — never scary, never guilt.
 */
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export function HealthHeader({ title, right, testID }: { title: string; right?: React.ReactNode; testID?: string }) {
  const router = useRouter();
  return (
    <View style={hs.header}>
      <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/life" as any))} hitSlop={12} style={hs.iconBtn} testID={`${testID ?? "health"}-back`}>
        <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
      </Pressable>
      <Text style={hs.title} numberOfLines={1}>{title}</Text>
      {right}
    </View>
  );
}

/** Colour for a domain or indicator status. Missing / not measured are grey. */
export const statusColour = (s?: string) =>
  s === "green" ? colors.success : s === "amber" ? colors.warning : s === "red" ? colors.error : colors.onSurfaceTertiary;

export const statusText = (s?: string) =>
  s === "green" ? "Looking good" : s === "amber" ? "Worth some attention" : s === "red" ? "Worth talking to your doctor" : s === "not_measured" ? "Not measured" : "Not added yet";

/** Turn API codes like "heart_disease_before_60" into "Heart disease before 60". */
export const humanize = (code: string) => {
  const special: Record<string, string> = { asthma_copd: "Asthma / COPD", depression_anxiety: "Depression or anxiety", high_blood_pressure: "High blood pressure" };
  if (special[code]) return special[code];
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const niceDay = (iso?: string | null) => {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS_SHORT[m - 1]} ${y}` : String(iso);
};

const PHONE = /(\b112\b|\b14416\b|\b1800[\d-]{6,}\b|\b\d{10}\b)/g;

export function PhoneText({ text, style }: { text: string; style?: any }) {
  const parts = String(text || "").split(PHONE);
  return (
    <Text style={style ?? hs.flagAction}>
      {parts.map((p, i) =>
        p.match(PHONE) ? (
          <Text key={i} style={hs.phone} onPress={() => Linking.openURL(`tel:${p.replace(/-/g, "")}`)} accessibilityRole="link" testID={`red-flag-call-${p}`}>
            {p}
          </Text>
        ) : p,
      )}
    </Text>
  );
}

/** Red flags come first, big and clear, with the action and tappable helplines. */
export function RedFlags({ flags }: { flags: any[] }) {
  if (!flags?.length) return null;
  return (
    <View style={hs.flags} testID="health-red-flags">
      {flags.map((f, i) => (
        <View key={i} style={hs.flag} testID={`health-red-flag-${i}`}>
          <View style={hs.flagHead}>
            <Ionicons name="alert-circle" size={26} color={colors.error} />
            <Text style={hs.flagWhat}>{f.what}</Text>
          </View>
          <PhoneText text={f.action} />
          {String(f.action || "").match(PHONE) ? null : (
            <Pressable style={hs.callBtn} onPress={() => Linking.openURL("tel:112")} testID={`red-flag-call-default-${i}`}>
              <Ionicons name="call" size={18} color={colors.onBrandPrimary} />
              <Text style={hs.callText}>Call 112</Text>
            </Pressable>
          )}
        </View>
      ))}
    </View>
  );
}

export const hs = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.sm },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 26, fontWeight: "700", color: colors.onSurface },
  scroll: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl * 2 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  h: { fontSize: 17, fontWeight: "700", color: colors.onSurface },
  section: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, letterSpacing: 0.4 },
  body: { fontSize: 14, lineHeight: 21, color: colors.onSurfaceSecondary },
  label: { fontSize: 14, fontWeight: "600", color: colors.onSurface, marginTop: spacing.md, marginBottom: spacing.xs },
  input: { minHeight: 48, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.surface, paddingHorizontal: spacing.md, fontSize: 15, color: colors.onSurface },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { minHeight: 40, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { fontSize: 14, fontWeight: "600", color: colors.onSurface },
  chipTextOn: { color: colors.onBrandPrimary },
  primary: { minHeight: 52, borderRadius: radius.pill, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  primaryText: { color: colors.onBrandPrimary, fontSize: 16, fontWeight: "700" },
  secondary: { minHeight: 48, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: spacing.sm },
  secondaryText: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
  error: { fontSize: 13, color: colors.error },
  muted: { fontSize: 13, color: colors.onSurfaceTertiary },
  dot: { width: 10, height: 10, borderRadius: 5 },
  flags: { gap: spacing.md },
  flag: { borderRadius: radius.md, borderWidth: 2, borderColor: colors.error, backgroundColor: colors.surface, padding: spacing.lg, gap: spacing.md },
  flagHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  flagWhat: { flex: 1, fontSize: 19, fontWeight: "700", color: colors.onSurface },
  flagAction: { fontSize: 17, lineHeight: 25, color: colors.onSurface },
  phone: { fontWeight: "800", color: colors.error, textDecorationLine: "underline" },
  callBtn: { minHeight: 48, borderRadius: radius.pill, backgroundColor: colors.error, flexDirection: "row", gap: spacing.sm, alignItems: "center", justifyContent: "center" },
  callText: { color: colors.onBrandPrimary, fontSize: 16, fontWeight: "700" },
});
