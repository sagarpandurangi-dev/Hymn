import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type Project = { id: string; title: string; status: string; description: string };

export default function ProjectsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);

  const load = useCallback(async () => {
    try {
      const items = await api.listProjects();
      setProjects(items);
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="projects-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="projects-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Projects</Text>
        <Pressable onPress={() => router.push("/projects/add")} testID="projects-add-button" hitSlop={12}>
          <Ionicons name="add" size={24} color={colors.onSurface} />
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : projects.length === 0 ? (
        <View style={styles.emptyWrap}>
          <Ionicons name="briefcase-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTitle}>No projects yet.</Text>
          <Pressable onPress={() => router.push("/projects/add")} style={styles.emptyCta} testID="projects-empty-add-button">
            <Text style={styles.emptyCtaText}>Add project</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
          {projects.map((p) => (
            <Pressable key={p.id} onPress={() => router.push(`/projects/${p.id}`)} style={styles.card} testID={`project-row-${p.id}`}>
              <Text style={styles.status}>{(p.status || "").toUpperCase()}</Text>
              <Text style={styles.title} numberOfLines={2}>{p.title}</Text>
              {p.description ? <Text style={styles.desc} numberOfLines={2}>{p.description}</Text> : null}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 20, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: spacing.xxxl, gap: spacing.md },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: fonts.displayBold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, fontWeight: "600" },
  emptyCta: { marginTop: spacing.lg, backgroundColor: colors.onSurface, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill },
  emptyCtaText: { color: colors.onSurfaceInverse, fontWeight: "600" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  status: { fontSize: 10, color: colors.onSurfaceTertiary, letterSpacing: 1.5, marginBottom: 4 },
  title: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "600", lineHeight: 24 },
  desc: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: 4 },
});
