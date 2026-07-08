import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import ConfirmModal from "@/src/components/ConfirmModal";

type Domain = { id: string; name: string; is_default: boolean; created_at: string };

export default function DomainsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmFor, setConfirmFor] = useState<Domain | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const items = await api.listDomains();
      setDomains(items);
    } catch (e: any) {
      setError(e?.message || "Could not load");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const doDelete = async () => {
    if (!confirmFor) return;
    setDeleteError(null); setDeleting(true);
    try {
      await api.deleteDomain(confirmFor.id);
      setConfirmFor(null);
      await load();
    } catch (e: any) {
      setDeleteError(e?.message || "Could not delete");
    } finally { setDeleting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="domains-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="domains-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Domains</Text>
        <Pressable onPress={() => router.push("/domains/add")} testID="domains-add-button" hitSlop={12}>
          <Ionicons name="add" size={24} color={colors.onSurface} />
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={load} style={styles.retry}><Text>Retry</Text></Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
        >
          {domains.map((d) => (
            <View key={d.id} style={styles.row} testID={`domain-row-${d.name}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{d.name}</Text>
                {d.is_default && <Text style={styles.badge}>DEFAULT</Text>}
              </View>
              <Pressable
                onPress={() => router.push(`/domains/edit/${d.id}`)}
                testID={`domain-edit-${d.name}`}
                hitSlop={8}
                style={styles.iconBtn}
              >
                <Ionicons name="pencil-outline" size={18} color={colors.onSurfaceSecondary} />
              </Pressable>
              <Pressable
                onPress={() => { setDeleteError(null); setConfirmFor(d); }}
                testID={`domain-delete-${d.name}`}
                hitSlop={8}
                style={styles.iconBtn}
              >
                <Ionicons name="trash-outline" size={18} color={colors.error} />
              </Pressable>
            </View>
          ))}
        </ScrollView>
      )}

      <ConfirmModal
        visible={!!confirmFor}
        title={`Delete "${confirmFor?.name || ""}"?`}
        message="This action cannot be undone. A domain can only be deleted when no goals are linked to it."
        confirmLabel="Delete"
        danger
        busy={deleting}
        error={deleteError}
        onCancel={() => setConfirmFor(null)}
        onConfirm={doDelete}
        testID="domain-delete-modal"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 20, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.sm },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorText: { color: colors.error, marginBottom: spacing.md },
  retry: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  name: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  badge: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1, marginTop: 2 },
  iconBtn: { padding: spacing.xs },
});
