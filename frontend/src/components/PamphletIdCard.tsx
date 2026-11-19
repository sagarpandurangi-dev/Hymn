import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import Ionicons from "@react-native-vector-icons/ionicons";
import { colors, radius, spacing } from "@/src/lib/theme";

function CopyButton({ value, testID }: { value: string; testID: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await Clipboard.setStringAsync(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Pressable onPress={copy} hitSlop={8} style={styles.copyBtn} testID={testID} accessibilityLabel={`Copy ${value}`}>
      <Ionicons name={copied ? "checkmark" : "copy-outline"} size={18} color={colors.brandPrimary} />
      <Text style={styles.copyText}>{copied ? "Copied" : "Copy"}</Text>
    </Pressable>
  );
}

/** "Your Pamphlet ID" card: alias (large, if set) and the Hymn ID, each copyable. */
export default function PamphletIdCard({ hymnId, hymnAlias }: { hymnId?: string | null; hymnAlias?: string | null }) {
  if (!hymnId && !hymnAlias) return null;
  return (
    <View style={styles.card} testID="me-pamphlet-card">
      <Text style={styles.title}>Your Pamphlet ID</Text>
      {hymnAlias ? (
        <View style={styles.row}>
          <Text style={styles.alias} selectable testID="me-hymn-alias">{hymnAlias}</Text>
          <CopyButton value={hymnAlias} testID="me-copy-hymn-alias" />
        </View>
      ) : null}
      {hymnId ? (
        <View style={styles.row}>
          <Text style={styles.id} selectable testID="me-hymn-id">{hymnId}</Text>
          <CopyButton value={hymnId} testID="me-copy-hymn-id" />
        </View>
      ) : null}
      <Text style={styles.note}>One ID for Hymn and Pamphlet — share it instead of your phone number.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { marginHorizontal: spacing.xl, marginBottom: spacing.lg, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  title: { fontSize: 12, color: colors.onSurfaceSecondary, letterSpacing: 0.5, fontWeight: "600" },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  alias: { flex: 1, fontSize: 26, fontWeight: "700", color: colors.onSurface, letterSpacing: 1 },
  id: { flex: 1, fontSize: 16, color: colors.onSurfaceSecondary, letterSpacing: 1 },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: spacing.sm },
  copyText: { fontSize: 13, color: colors.brandPrimary, fontWeight: "600" },
  note: { fontSize: 12.5, color: colors.onSurfaceSecondary, lineHeight: 18 },
});
