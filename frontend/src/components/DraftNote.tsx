import { StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { colors, radius, spacing } from "@/src/lib/theme";

/** Small amber note; show when the API says rules_reviewed / values_reviewed is false. */
export default function DraftNote({ text = "Draft — not yet reviewed by a doctor", testID = "draft-note" }: { text?: string; testID?: string }) {
  return (
    <View style={styles.box} testID={testID}>
      <Ionicons name="alert-circle-outline" size={14} color={colors.warning} />
      <Text style={styles.text}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.warning,
    borderLeftWidth: 3,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  text: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
});
