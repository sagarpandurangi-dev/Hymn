// Batch 2A: account selector for money-bearing check-ins.
//
// When a user enters `money_spent` on a check-in we MUST persist the
// authoritative account it came out of. This lightweight modal lists the
// user's accounts filtered by currency so a mismatched account is not
// selectable at the UI layer (the backend also enforces this). Skipping
// the selection is allowed — the resulting event is created in
// `pending_account_assignment` and shows up in the Finance dashboard as
// a warning that the position isn't fully confident.
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { api } from "@/src/lib/api";
import { colors, spacing } from "@/src/lib/theme";

type AccountRow = {
  id: string;
  name: string;
  account_type: string;
  currency: string;
  current_value: string;
  liquidity_type: string;
};

type Props = {
  visible: boolean;
  currency: string; // ISO 4217 — only accounts in this currency are shown
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onClose: () => void;
};

export default function AccountPickerModal({ visible, currency, selectedId, onSelect, onClose }: Props) {
  const [accounts, setAccounts] = useState<AccountRow[] | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const rows = (await api.listFinancialAccounts()) as any as AccountRow[];
        if (!cancelled) setAccounts(rows || []);
      } catch {
        if (!cancelled) setAccounts([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [visible]);

  const filtered = useMemo(
    () => (accounts || []).filter((a) => a.currency === currency),
    [accounts, currency],
  );

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>Which account?</Text>
            <Pressable onPress={onClose} hitSlop={12} testID="account-picker-close">
              <Text style={styles.close}>Done</Text>
            </Pressable>
          </View>
          {loading && !accounts ? (
            <View style={styles.loading}><ActivityIndicator color={colors.onSurface} /></View>
          ) : filtered.length === 0 ? (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>No {currency} accounts</Text>
              <Text style={styles.emptyBody}>
                Add a {currency} account in Portfolio to link this spend. You can save the
                check-in now and assign an account later.
              </Text>
            </View>
          ) : (
            <FlatList
              data={filtered}
              keyExtractor={(a) => a.id}
              renderItem={({ item }) => {
                const active = item.id === selectedId;
                return (
                  <Pressable
                    onPress={() => { onSelect(item.id); onClose(); }}
                    style={[styles.row, active && styles.rowActive]}
                    testID={`account-picker-option-${item.id}`}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowName}>{item.name}</Text>
                      <Text style={styles.rowMeta}>{item.account_type} · {item.liquidity_type}</Text>
                    </View>
                    <Text style={styles.rowValue}>{item.currency} {item.current_value}</Text>
                  </Pressable>
                );
              }}
              ItemSeparatorComponent={() => <View style={styles.sep} />}
            />
          )}
          <Pressable
            onPress={() => { onSelect(null); onClose(); }}
            style={styles.pendingRow}
            testID="account-picker-skip"
          >
            <Text style={styles.pendingText}>Save without an account (assign later)</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: spacing.xl,
    maxHeight: "80%",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  title: { fontSize: 17, fontWeight: "600", color: colors.onSurface },
  close: { fontSize: 15, color: colors.brand, fontWeight: "600" },
  loading: { padding: spacing.xl },
  empty: { padding: spacing.xl },
  emptyTitle: { fontSize: 15, fontWeight: "600", color: colors.onSurface, marginBottom: spacing.sm },
  emptyBody: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 18 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.lg,
    gap: spacing.md,
  },
  rowActive: { backgroundColor: colors.surfaceSecondary },
  rowName: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  rowMeta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowValue: { fontSize: 13, color: colors.onSurfaceSecondary },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: colors.divider, marginLeft: spacing.lg },
  pendingRow: {
    padding: spacing.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  pendingText: { fontSize: 14, color: colors.onSurfaceSecondary, textAlign: "center" },
});
