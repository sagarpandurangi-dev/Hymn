import { useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
import { showToast } from "@/src/lib/toast";
import { formStyles as s } from "@/src/lib/formStyles";
import { colors, spacing } from "@/src/lib/theme";

const GONE = [
  "Everything you've put into Hymn: check-ins, plans, money, notes and documents.",
  "People you look after, including their health data.",
  "Your Pamphlet ID is retired. It is never given to anyone else.",
];

export default function DeleteAccountScreen() {
  const router = useRouter();
  const { signOut } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const ready = password.length > 0 && confirm.trim() === "DELETE";

  const remove = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteAccount(password);
      showToast("Your account has been deleted.");
      void signOut(); // session is already gone server-side; don't wait for logout
    } catch (e) {
      setError((e as ApiError).message || "Couldn't delete your account. Try again.");
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.headerRow}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="delete-account-back"><Text style={s.cancel}>Back</Text></Pressable>
        <Text style={s.headerTitle}>Delete account</Text>
        <View style={{ width: 56 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.lead}>{"This permanently deletes your Hymn account. It can't be undone."}</Text>
          <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
            {GONE.map((g) => (
              <View key={g} style={styles.bulletRow}>
                <Text style={styles.bullet}>•</Text>
                <Text style={styles.bulletText}>{g}</Text>
              </View>
            ))}
          </View>
          <Text style={styles.tip}>{"Want a copy first? Use \u201cDownload my data\u201d on the Me screen."}</Text>

          <Text style={s.label}>Your password</Text>
          <TextInput
            style={s.input}
            value={password}
            onChangeText={(v) => { setPassword(v); setError(""); }}
            secureTextEntry
            autoCapitalize="none"
            autoComplete="current-password"
            placeholder="Password"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="delete-account-password"
          />
          <Text style={s.label}>Type DELETE to confirm</Text>
          <TextInput
            style={s.input}
            value={confirm}
            onChangeText={(v) => { setConfirm(v); setError(""); }}
            autoCapitalize="characters"
            autoCorrect={false}
            placeholder="DELETE"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="delete-account-confirm"
          />
          {error ? <Text style={s.errorText} testID="delete-account-error">{error}</Text> : null}
          <Pressable
            style={[styles.danger, (!ready || busy) && { opacity: 0.45 }]}
            onPress={remove}
            disabled={!ready || busy}
            accessibilityState={{ disabled: !ready || busy }}
            testID="delete-account-submit"
          >
            {busy ? <ActivityIndicator color={colors.onSurfaceInverse} /> : <Text style={styles.dangerText}>Delete my account</Text>}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  lead: { fontSize: 16, lineHeight: 23, fontWeight: "600", color: colors.onSurface },
  bulletRow: { flexDirection: "row", gap: spacing.sm },
  bullet: { fontSize: 15, color: colors.onSurfaceSecondary, lineHeight: 22 },
  bulletText: { flex: 1, fontSize: 15, lineHeight: 22, color: colors.onSurfaceSecondary },
  tip: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.lg },
  danger: { backgroundColor: colors.error, minHeight: 52, borderRadius: 999, alignItems: "center", justifyContent: "center", marginTop: spacing.xl },
  dangerText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
