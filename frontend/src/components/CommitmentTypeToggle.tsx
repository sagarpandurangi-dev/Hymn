import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, radius, spacing } from "@/src/lib/theme";

type Props = {
  value: "postponable" | "exclusive";
  onChange: (v: "postponable" | "exclusive") => void;
  testID?: string;
};

const HELP_COPY: Record<Props["value"], string> = {
  postponable: "This can be moved or cancelled if life gets busy.",
  exclusive: "Locked in — Hymn will not suggest postponing or cancelling.",
};

export default function CommitmentTypeToggle({ value, onChange, testID }: Props) {
  return (
    <View>
      <View style={styles.row}>
        <Pressable
          onPress={() => onChange("postponable")}
          style={[styles.chip, value === "postponable" && styles.chipSelected]}
          testID={`${testID ?? "commitment-type"}-postponable`}
        >
          <Ionicons
            name="swap-horizontal-outline"
            size={14}
            color={value === "postponable" ? colors.onBrandPrimary : colors.onSurfaceSecondary}
          />
          <Text style={[styles.chipText, value === "postponable" && styles.chipTextSelected]}>Postponable</Text>
        </Pressable>
        <Pressable
          onPress={() => onChange("exclusive")}
          style={[styles.chip, value === "exclusive" && styles.chipSelected]}
          testID={`${testID ?? "commitment-type"}-exclusive`}
        >
          <Ionicons
            name="lock-closed-outline"
            size={14}
            color={value === "exclusive" ? colors.onBrandPrimary : colors.onSurfaceSecondary}
          />
          <Text style={[styles.chipText, value === "exclusive" && styles.chipTextSelected]}>Exclusive</Text>
        </Pressable>
      </View>
      <Text style={styles.help}>{HELP_COPY[value]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.sm },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.pill, backgroundColor: colors.brandTertiary,
  },
  chipSelected: { backgroundColor: colors.brandPrimary },
  chipText: { fontSize: 13, color: colors.onBrandTertiary, fontWeight: "500" },
  chipTextSelected: { color: colors.onBrandPrimary },
  help: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 6, lineHeight: 15 },
});
