import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import {
  getOverlayPermissionStatus,
  isOverlayCapable,
  requestOverlayPermission,
  setOverlayPermissionStatus,
  type OverlayPermissionStatus,
} from "@/src/lib/overlayPermission";

function statusLabel(s: OverlayPermissionStatus): string {
  switch (s) {
    case "unsupported": return "Not supported on this platform";
    case "supported":   return "Supported — permission not requested yet";
    case "enabled":     return "Enabled";
    case "disabled":    return "Disabled";
    case "not_yet_supported": return "Not yet supported (native module pending)";
    default: return "Unknown";
  }
}

function statusColor(s: OverlayPermissionStatus): string {
  if (s === "enabled") return colors.success;
  if (s === "disabled") return colors.error;
  if (s === "supported") return colors.warning;
  return colors.onSurfaceTertiary;
}

export default function OverlaySettingsScreen() {
  const router = useRouter();
  const [status, setStatus] = useState<OverlayPermissionStatus>("unknown");
  const capable = isOverlayCapable();

  const refresh = useCallback(async () => {
    setStatus(await getOverlayPermissionStatus());
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const onPrepare = async () => {
    // Placeholder — real native flow lands with the overlay bubble ship.
    const next = await requestOverlayPermission();
    setStatus(next);
  };

  const onMarkEnabled = async () => {
    await setOverlayPermissionStatus("enabled");
    await refresh();
  };
  const onMarkDisabled = async () => {
    await setOverlayPermissionStatus("disabled");
    await refresh();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="overlay-settings-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="overlay-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Quick Check-in Overlay</Text>
        <View style={{ width: 22 }} />
      </View>

      <View style={styles.body}>
        <Text style={styles.p}>
          Hymn is preparing an Android &quot;Display over other apps&quot; overlay so you
          can launch a Quick Check-in from anywhere, without opening the full app.
        </Text>

        <View style={styles.statusBox} testID="overlay-status-box">
          <Text style={styles.label}>PLATFORM</Text>
          <Text style={styles.value}>{capable ? "Android" : "Not Android"}</Text>

          <Text style={[styles.label, { marginTop: spacing.md }]}>STATUS</Text>
          <View style={styles.statusRow}>
            <View style={[styles.dot, { backgroundColor: statusColor(status) }]} />
            <Text style={styles.value} testID="overlay-status-value">{statusLabel(status)}</Text>
          </View>
        </View>

        {capable && (
          <>
            <Pressable style={styles.cta} onPress={onPrepare} testID="overlay-request-button">
              <Text style={styles.ctaText}>Prepare permission</Text>
            </Pressable>
            <View style={styles.debugRow}>
              <Pressable style={styles.debugBtn} onPress={onMarkEnabled} testID="overlay-mark-enabled">
                <Text style={styles.debugText}>Mark enabled</Text>
              </Pressable>
              <Pressable style={styles.debugBtn} onPress={onMarkDisabled} testID="overlay-mark-disabled">
                <Text style={styles.debugText}>Mark disabled</Text>
              </Pressable>
            </View>
          </>
        )}

        <Text style={styles.note}>
          The overlay bubble itself will ship in a future release. This page keeps the
          permission flow persistent so it is ready when that lands.
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  body: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  p: { fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 22 },
  statusBox: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  label: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5 },
  value: { fontSize: 14, color: colors.onSurface, marginTop: 4 },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  cta: { alignSelf: "flex-start", backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  ctaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  debugRow: { flexDirection: "row", gap: spacing.sm },
  debugBtn: { backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill },
  debugText: { color: colors.onSurfaceSecondary, fontSize: 13 },
  note: { fontSize: 12, color: colors.onSurfaceTertiary, fontStyle: "italic" },
});
