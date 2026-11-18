import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { colors, radius, spacing } from "@/src/lib/theme";

/** Me screen: "Download my data" and the link to "Delete my account". */
export default function AccountDataSection() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const download = async () => {
    setBusy(true);
    setError("");
    try {
      await api.downloadAccountExport();
    } catch (e) {
      setError((e as ApiError).message || "Couldn't download your data. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.section}>
      <Text style={styles.heading}>Your data</Text>
      <View style={styles.card}>
        <Pressable style={styles.row} onPress={download} disabled={busy} testID="me-download-data">
          <View style={styles.rowLeft}>
            <Ionicons name="download-outline" size={20} color={colors.onSurface} />
            <View style={{ flex: 1 }}>
              <Text style={styles.rowText}>Download my data</Text>
              <Text style={styles.note}>Everything Hymn holds for you, in one file.</Text>
            </View>
          </View>
          {busy ? <ActivityIndicator color={colors.brandPrimary} /> : null}
        </Pressable>
        {error ? <Text style={styles.error} testID="me-download-error">{error}</Text> : null}
        <Pressable style={[styles.row, styles.divider]} onPress={() => router.push("/account/delete" as any)} testID="me-delete-account">
          <View style={styles.rowLeft}>
            <Ionicons name="trash-outline" size={20} color={colors.error} />
            <Text style={[styles.rowText, { color: colors.error }]}>Delete my account</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: spacing.xl, paddingHorizontal: spacing.xl },
  heading: { fontSize: 12, fontWeight: "700", letterSpacing: 0.6, color: colors.onSurfaceSecondary, marginBottom: spacing.sm, textTransform: "uppercase" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingHorizontal: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 56, paddingVertical: spacing.sm, gap: spacing.md },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  rowLeft: { flexDirection: "row", alignItems: "center", gap: spacing.md, flex: 1 },
  rowText: { fontSize: 15, color: colors.onSurface },
  note: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  error: { fontSize: 13, color: colors.error, paddingBottom: spacing.sm },
});
