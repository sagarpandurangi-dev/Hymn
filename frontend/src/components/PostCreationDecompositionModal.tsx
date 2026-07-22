import React from "react";
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
  /** Externally-controlled remember flag. */
  remember: boolean;
  /** Toggle handler for the checkbox. */
  onRememberChange: (next: boolean) => void;
  /** Selection handler. Both buttons + the checkbox are disabled until the
   * parent hook completes the flow. */
  onChoose: (choice: DecompositionChoice) => void;
  /** Which choice, if any, has been picked in the current session. */
  pendingChoice: DecompositionChoice | null;
  /** Non-blocking error surfaced when preference saving fails. */
  errorMessage?: string | null;
};

export function PostCreationDecompositionModal({
  visible,
  objectLabel,
  remember,
  onRememberChange,
  onChoose,
  pendingChoice,
  errorMessage,
}: PostCreationDecompositionModalProps) {
  const disabled = pendingChoice !== null;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={() => {
        // No-op — the modal must not be dismissed without a decision.
      }}
    >
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>{objectLabel} created</Text>
          <Text style={styles.body}>
            Would you like Hymn to break this into outcomes, tasks, dependencies and resource requirements now?
          </Text>

          <Pressable
            onPress={() => {
              if (disabled) return;
              onRememberChange(!remember);
            }}
            style={[styles.rememberRow, disabled && styles.btnDisabled]}
            hitSlop={4}
            disabled={disabled}
            testID="pcdm-remember"
          >
            <Ionicons
              name={remember ? "checkbox" : "square-outline"}
              size={20}
              color={remember ? colors.brandPrimary : colors.onSurfaceSecondary}
            />
            <Text style={styles.rememberText}>Remember this choice</Text>
          </Pressable>

          <View style={styles.actionsRow}>
            <Pressable
              onPress={() => onChoose("skip")}
              disabled={disabled}
              style={[styles.secondaryBtn, disabled && styles.btnDisabled]}
              testID="pcdm-skip"
            >
              <Text style={styles.secondaryBtnText}>Skip for now</Text>
            </Pressable>
            <Pressable
              onPress={() => onChoose("decompose")}
              disabled={disabled}
              style={[styles.primaryBtn, disabled && styles.btnDisabled]}
              testID="pcdm-decompose"
            >
              <Text style={styles.primaryBtnText}>Break it down now</Text>
            </Pressable>
          </View>

          {errorMessage ? (
            <Text style={styles.errorText} testID="pcdm-error">
              {errorMessage}
            </Text>
          ) : null}
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
  errorText: {
    fontFamily: fonts.body,
    fontSize: 12,
    color: colors.error,
    marginTop: spacing.xs,
    textAlign: "center",
  },
});
