import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import { getOverlayPermissionStatus, isOverlayCapable, requestOverlayPermission, type OverlayPermissionStatus } from "@/src/lib/overlayPermission";

export default function OverlaySettingsScreen() {
  const router = useRouter();
  const [status, setStatus] = useState<OverlayPermissionStatus>("unknown");

  const refresh = useCallback(async () => {
    setStatus(await getOverlayPermissionStatus());
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const onRequest = async () => {
    const next = await requestOverlayPermission();
    setStatus(next);
  };

  const capable = isOverlayCapable();

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
          In a future update, Hymn can launch a Quick Check-in from anywhere on Android,
          even when the full app is not open. This requires the &quot;Display over other apps&quot; permission.
        </Text>

        <View style={styles.statusBox} testID="overlay-status-box">
          <Text style={styles.label}>PLATFORM</Text>
          <Text style={styles.value}>{capable ? "Android — supported" : "Not supported on this platform"}</Text>
          <Text style={[styles.label, { marginTop: spacing.md }]}>STATUS</Text>
          <Text style={styles.value}>{status.replace(/_/g, " ")}</Text>
        </View>

        {capable && (
          <Pressable style={styles.cta} onPress={onRequest} testID="overlay-request-button">
            <Text style={styles.ctaText}>Prepare permission</Text>
          </Pressable>
        )}

        <Text style={styles.note}>
          The overlay UI itself will ship in a later release. This screen only prepares
          the permission flow so it is ready when the overlay feature lands.
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
  value: { fontSize: 14, color: colors.onSurface, marginTop: 4, textTransform: "capitalize" },
  cta: { alignSelf: "flex-start", backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  ctaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  note: { fontSize: 12, color: colors.onSurfaceTertiary, fontStyle: "italic" },
});
