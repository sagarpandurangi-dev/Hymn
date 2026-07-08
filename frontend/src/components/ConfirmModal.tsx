import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Props = {
  visible: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  error?: string | null;
  onCancel: () => void;
  onConfirm: () => void;
  testID?: string;
};

export default function ConfirmModal({
  visible, title, message, confirmLabel = "Confirm", cancelLabel = "Cancel",
  danger, busy, error, onCancel, onConfirm, testID = "confirm-modal",
}: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={() => (busy ? null : onCancel())}>
      <View style={styles.backdrop} testID={testID}>
        <View style={styles.card}>
          <Text style={styles.title}>{title}</Text>
          {message ? <Text style={styles.body}>{message}</Text> : null}
          {error ? <Text style={styles.err} testID={`${testID}-error`}>{error}</Text> : null}
          <View style={styles.row}>
            <Pressable style={[styles.btn, styles.btnSecondary]} onPress={onCancel} disabled={busy} testID={`${testID}-cancel`}>
              <Text style={styles.btnSecondaryText}>{cancelLabel}</Text>
            </Pressable>
            <Pressable
              style={[styles.btn, danger ? styles.btnDanger : styles.btnPrimary, busy && styles.btnDisabled]}
              onPress={onConfirm}
              disabled={busy}
              testID={`${testID}-confirm`}
            >
              {busy ? (
                <ActivityIndicator color={danger ? colors.onError : colors.onSurfaceInverse} />
              ) : (
                <Text style={danger ? styles.btnDangerText : styles.btnPrimaryText}>{confirmLabel}</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(30,30,28,0.55)", alignItems: "center", justifyContent: "center", padding: spacing.xl },
  card: { width: "100%", maxWidth: 360, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl },
  title: { fontFamily: fonts.displayBold, fontSize: 20, color: colors.onSurface, fontWeight: "700", marginBottom: spacing.sm },
  body: { fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  err: { color: colors.error, fontSize: 13, marginTop: spacing.md },
  row: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xl },
  btn: { flex: 1, paddingVertical: spacing.md + 2, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  btnSecondary: { backgroundColor: colors.surfaceSecondary },
  btnSecondaryText: { color: colors.onSurface, fontSize: 15, fontWeight: "500" },
  btnPrimary: { backgroundColor: colors.onSurface },
  btnPrimaryText: { color: colors.onSurfaceInverse, fontSize: 15, fontWeight: "600" },
  btnDanger: { backgroundColor: colors.error },
  btnDangerText: { color: colors.onError, fontSize: 15, fontWeight: "600" },
  btnDisabled: { opacity: 0.7 },
});
