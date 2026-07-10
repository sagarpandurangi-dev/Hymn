import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function MeScreen() {
  const router = useRouter();
  const { user, signOut } = useAuth();
  const [busy, setBusy] = useState(false);

  const onLogout = async () => {
    setBusy(true);
    try {
      await signOut();
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]} testID="me-screen">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} testID="me-back" hitSlop={12}>
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Me</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.profile}>
          <View style={styles.avatar}>
            <Ionicons name="person" size={32} color={colors.onBrandPrimary} />
          </View>
          <Text style={styles.email} testID="me-email">{user?.email || ""}</Text>
        </View>

        <View style={styles.section}>
          <Pressable style={styles.row} onPress={() => router.push("/domains")} testID="me-open-domains">
            <View style={styles.rowLeft}>
              <Ionicons name="grid-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Domains</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>

          <Pressable style={styles.row} onPress={() => router.push("/goals")} testID="me-open-goals">
            <View style={styles.rowLeft}>
              <Ionicons name="flag-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Goals</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>

          <Pressable style={styles.row} onPress={() => router.push("/projects")} testID="me-open-projects">
            <View style={styles.rowLeft}>
              <Ionicons name="briefcase-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Projects</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>

          <Pressable style={styles.row} onPress={() => router.push("/tasks")} testID="me-open-tasks">
            <View style={styles.rowLeft}>
              <Ionicons name="list-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Tasks</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>

          <Pressable style={styles.row} onPress={() => router.push("/settings/overlay")} testID="me-open-overlay">
            <View style={styles.rowLeft}>
              <Ionicons name="layers-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Quick Check-in overlay</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>
        </View>

        <View style={styles.section}>
          <Pressable style={styles.logoutButton} onPress={onLogout} disabled={busy} testID="logout-button">
            {busy ? <ActivityIndicator color={colors.error} /> : <>
              <Ionicons name="log-out-outline" size={20} color={colors.error} />
              <Text style={styles.logoutText}>Log out</Text>
            </>}
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md,
  },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 20, fontWeight: "600", color: colors.onSurface },
  scroll: { paddingBottom: spacing.xxxl },
  profile: { alignItems: "center", paddingHorizontal: spacing.xl, paddingVertical: spacing.xl, gap: spacing.md },
  avatar: {
    width: 72, height: 72, borderRadius: 36, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  email: { fontSize: 16, color: colors.onSurface, fontWeight: "500" },
  section: { paddingHorizontal: spacing.xl, marginTop: spacing.lg, gap: spacing.sm },
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    paddingVertical: spacing.lg, paddingHorizontal: spacing.lg,
  },
  rowLeft: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  rowText: { fontSize: 15, color: colors.onSurface, fontWeight: "500" },
  logoutButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, paddingVertical: spacing.lg, borderRadius: radius.md,
  },
  logoutText: { color: colors.error, fontSize: 16, fontWeight: "600" },
});
