import React, { useState } from "react";
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, fonts } from "@/src/lib/theme";

export type DecompositionChoice = "decompose" | "skip";

export type PostCreationDecompositionModalProps = {
  visible: boolean;
  objectLabel: string;
  onChoose: (choice: DecompositionChoice, remember: boolean) => void;
};

export function PostCreationDecompositionModal({
  visible,
  objectLabel,
  onChoose,
}: PostCreationDecompositionModalProps) {
  const [remember, setRemember] = useState(false);
  const [pending, setPending] = useState<DecompositionChoice | null>(null);

  const disabled = pending !== null;

  const handle = (choice: DecompositionChoice) => {
    if (disabled) return;
    setPending(choice);
    onChoose(choice, remember);
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={() => {
        // No-op — this modal must not be dismissed without a decision.
      }}
    >
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>{objectLabel} created</Text>
          <Text style={styles.body}>
            Would you like Hymn to break this into outcomes, tasks, dependencies and resource requirements now?
          </Text>

          <Pressable
            onPress={() => setRemember((v) => !v)}
            style={styles.rememberRow}
            hitSlop={4}
            testID="pcdm-remember"
          >
            <Ionicons
              name={remember ? "checkbox" : "square-outline"}
              size={20}
              color={remember ? colors.brandPrimary : colors.onSurfaceSecondary}
            />
            <Text style={styles.rememberText}>Remember my choice</Text>
          </Pressable>

          <View style={styles.actionsRow}>
            <Pressable
              onPress={() => handle("skip")}
              disabled={disabled}
              style={[styles.secondaryBtn, disabled && styles.btnDisabled]}
              testID="pcdm-skip"
            >
              <Text style={styles.secondaryBtnText}>Skip for now</Text>
            </Pressable>
            <Pressable
              onPress={() => handle("decompose")}
              disabled={disabled}
              style={[styles.primaryBtn, disabled && styles.btnDisabled]}
              testID="pcdm-decompose"
            >
              <Text style={styles.primaryBtnText}>Decompose now</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  title: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface },
  body: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  rememberRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  rememberText: { fontFamily: fonts.body, fontSize: 13, color: colors.onSurface },
  actionsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  primaryBtn: {
    flex: 1,
    backgroundColor: colors.brandPrimary,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: "center",
  },
  primaryBtnText: { color: colors.onBrandPrimary, fontFamily: fonts.displayBold, fontSize: 14 },
  secondaryBtn: {
    flex: 1,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.borderStrong,
  },
  secondaryBtnText: { color: colors.onSurface, fontFamily: fonts.body, fontSize: 14 },
  btnDisabled: { opacity: 0.5 },
});
