import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function EditDomainScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const items = await api.listDomains();
        const d = items.find((x) => x.id === id);
        if (!d) throw new Error("Domain not found");
        setName(d.name);
      } catch (e: any) {
        setError(e?.message || "Could not load");
      } finally { setLoading(false); }
    })();
  }, [id]);

  const onSave = async () => {
    setError(null);
    if (!name.trim() || !id) { setError("Name is required."); return; }
    setBusy(true);
    try {
      await api.updateDomain(id, name.trim());
      router.back();
    } catch (e: any) {
      setError(e?.message || "Could not save");
    } finally { setBusy(false); }
  };

  if (loading) return (
    <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View></SafeAreaView>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="edit-domain-cancel" hitSlop={12}>
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>Edit Domain</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Name</Text>
          <TextInput
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="edit-domain-name-input"
          />
          {error ? <Text style={styles.errorText} testID="edit-domain-error">{error}</Text> : null}
        </ScrollView>
        <View style={styles.footer}>
          <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={onSave} disabled={busy} testID="edit-domain-save-button">
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={styles.ctaText}>Save changes</Text>}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  cancel: { color: colors.onSurfaceSecondary, fontSize: 14 },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.sm, letterSpacing: 0.5 },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 16, color: colors.onSurface },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
