import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { colors, radius, spacing } from "@/src/lib/theme";

export function CategoryLabel({ category }: { category: string }) {
  return (
    <View style={styles.label}>
      <Text style={styles.labelText}>{category || "unsorted"}</Text>
    </View>
  );
}

/** One inbox item: its text plus a small category label. */
export default function InboxItemRow({
  text,
  category,
  testID,
  children,
}: {
  text: string;
  category: string;
  testID?: string;
  children?: React.ReactNode;
}) {
  return (
    <View style={styles.row} testID={testID}>
      <View style={styles.head}>
        <Text style={styles.text}>{text}</Text>
        <CategoryLabel category={category} />
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg, gap: spacing.md,
  },
  head: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  text: { flex: 1, fontSize: 15, color: colors.onSurface },
  label: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.pill,
    paddingHorizontal: spacing.sm, paddingVertical: 2,
  },
  labelText: { fontSize: 11, color: colors.onBrandTertiary, fontWeight: "600", textTransform: "capitalize" },
});
