import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function MeScreen() {
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
    <SafeAreaView style={styles.safe} edges={["top"]} testID="me-screen">
      <View style={styles.header}>
        <Text style={styles.title}>Me</Text>
      </View>

      <View style={styles.profile}>
        <View style={styles.avatar}>
          <Ionicons name="person" size={32} color={colors.onBrandPrimary} />
        </View>
        <Text style={styles.email} testID="me-email">{user?.email || ""}</Text>
      </View>

      <View style={styles.section}>
        <Pressable
          style={styles.logoutButton}
          onPress={onLogout}
          disabled={busy}
          testID="logout-button"
        >
          {busy ? <ActivityIndicator color={colors.error} /> : <>
            <Ionicons name="log-out-outline" size={20} color={colors.error} />
            <Text style={styles.logoutText}>Log out</Text>
          </>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  profile: { alignItems: "center", paddingHorizontal: spacing.xl, paddingVertical: spacing.xl, gap: spacing.md },
  avatar: {
    width: 72, height: 72, borderRadius: 36, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  email: { fontSize: 16, color: colors.onSurface, fontWeight: "500" },
  section: { paddingHorizontal: spacing.xl, marginTop: spacing.xl },
  logoutButton: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, paddingVertical: spacing.lg, borderRadius: radius.md,
  },
  logoutText: { color: colors.error, fontSize: 16, fontWeight: "600" },
});
