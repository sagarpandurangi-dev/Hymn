import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/lib/AuthContext";
import {
  displayNameInitials,
  displayNameValidationError,
  normalizeDisplayName,
} from "@/src/lib/profile";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function MeScreen() {
  const router = useRouter();
  const { user, signOut, updateDisplayName } = useAuth();
  const [busy, setBusy] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState(user?.display_name || "");
  const [nameError, setNameError] = useState<string | null>(null);
  const initials = displayNameInitials(user?.display_name);

  const onLogout = async () => {
    setBusy(true);
    try {
      await signOut();
    } finally {
      setBusy(false);
    }
  };

  const saveName = async () => {
    const validationError = displayNameValidationError(nameValue);
    if (validationError) {
      setNameError(validationError);
      return;
    }
    setBusy(true);
    setNameError(null);
    try {
      const updated = await updateDisplayName(normalizeDisplayName(nameValue));
      setNameValue(updated.display_name || "");
      setEditingName(false);
    } catch (error: any) {
      setNameError(error?.message || "Hymn could not save your name.");
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
            {initials ? (
              <Text style={styles.avatarText}>{initials}</Text>
            ) : (
              <Ionicons name="person" size={32} color={colors.onBrandPrimary} />
            )}
          </View>
          {editingName ? (
            <View style={styles.nameEditor}>
              <Text style={styles.fieldLabel}>Your name</Text>
              <TextInput
                value={nameValue}
                onChangeText={setNameValue}
                style={styles.nameInput}
                placeholder="How should Hymn address you?"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="words"
                autoFocus
                maxLength={80}
                editable={!busy}
                testID="me-name-input"
              />
              {nameError ? <Text style={styles.errorText}>{nameError}</Text> : null}
              <View style={styles.nameActions}>
                <Pressable
                  onPress={saveName}
                  disabled={busy}
                  style={[styles.saveNameButton, busy && styles.disabled]}
                  testID="me-name-save"
                >
                  {busy ? (
                    <ActivityIndicator color={colors.onBrandPrimary} />
                  ) : (
                    <Text style={styles.saveNameText}>Save name</Text>
                  )}
                </Pressable>
                <Pressable
                  onPress={() => {
                    setNameValue(user?.display_name || "");
                    setNameError(null);
                    setEditingName(false);
                  }}
                  disabled={busy}
                  style={styles.cancelNameButton}
                >
                  <Text style={styles.cancelNameText}>Cancel</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <>
              <Text style={styles.displayName} testID="me-display-name">
                {user?.display_name || "Your profile"}
              </Text>
              <Pressable
                onPress={() => {
                  setNameValue(user?.display_name || "");
                  setEditingName(true);
                }}
                testID={user?.display_name ? "me-edit-name" : "me-add-name"}
              >
                <Text style={styles.nameLink}>
                  {user?.display_name ? "Edit your name" : "Add your name"}
                </Text>
              </Pressable>
            </>
          )}
          <View style={styles.emailBlock}>
            <Text style={styles.fieldLabel}>Email</Text>
            <Text style={styles.email} testID="me-email">{user?.email || ""}</Text>
          </View>
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

          <Pressable style={styles.row} onPress={() => router.push("/portfolio")} testID="me-open-portfolio">
            <View style={styles.rowLeft}>
              <Ionicons name="pie-chart-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Portfolio</Text>
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

          <Pressable style={styles.row} onPress={() => router.push("/settings/decomposition" as any)} testID="me-open-decomposition">
            <View style={styles.rowLeft}>
              <Ionicons name="git-network-outline" size={20} color={colors.onSurface} />
              <Text style={styles.rowText}>Planning after creation</Text>
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
  avatarText: { color: colors.onBrandPrimary, fontSize: 24, fontWeight: "700" },
  displayName: { fontSize: 22, color: colors.onSurface, fontWeight: "600" },
  nameLink: { color: colors.brandPrimary, fontSize: 14, fontWeight: "600" },
  nameEditor: { width: "100%", gap: spacing.sm },
  fieldLabel: { color: colors.onSurfaceSecondary, fontSize: 12, letterSpacing: 0.4 },
  nameInput: {
    width: "100%",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    color: colors.onSurface,
    fontSize: 16,
  },
  nameActions: { flexDirection: "row", gap: spacing.sm },
  saveNameButton: {
    flex: 1,
    alignItems: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: spacing.md,
  },
  saveNameText: { color: colors.onBrandPrimary, fontWeight: "600" },
  cancelNameButton: {
    flex: 1,
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    paddingVertical: spacing.md,
  },
  cancelNameText: { color: colors.onSurface, fontWeight: "600" },
  disabled: { opacity: 0.55 },
  errorText: { color: colors.error, fontSize: 13 },
  emailBlock: { alignItems: "center", gap: spacing.xs, marginTop: spacing.sm },
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
