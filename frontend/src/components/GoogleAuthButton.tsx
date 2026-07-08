import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, radius, spacing } from "@/src/lib/theme";

export default function GoogleAuthButton({ testID = "google-signin-button" }: { testID?: string }) {
  const { signInWithGoogle } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onPress = async () => {
    setError(null);
    setBusy(true);
    try {
      await signInWithGoogle();
    } catch (e: any) {
      setError(e?.message || "Google sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View>
      <Pressable style={[styles.btn, busy && styles.btnDisabled]} onPress={onPress} disabled={busy} testID={testID}>
        {busy ? (
          <ActivityIndicator color={colors.onSurface} />
        ) : (
          <>
            <Ionicons name="logo-google" size={18} color={colors.onSurface} />
            <Text style={styles.text}>Continue with Google</Text>
          </>
        )}
      </Pressable>
      {error ? <Text style={styles.error} testID="google-signin-error">{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.borderStrong,
    paddingVertical: spacing.md + 2, borderRadius: radius.pill,
  },
  btnDisabled: { opacity: 0.6 },
  text: { color: colors.onSurface, fontSize: 15, fontWeight: "500" },
  error: { color: colors.error, fontSize: 12, textAlign: "center", marginTop: spacing.sm },
});
