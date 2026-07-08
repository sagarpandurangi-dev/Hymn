import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  ActivityIndicator,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Link } from "expo-router";
import { useAuth } from "@/src/lib/AuthContext";
import GoogleAuthButton from "@/src/components/GoogleAuthButton";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function SignInScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async () => {
    setError(null);
    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      await signIn(email.trim().toLowerCase(), password);
    } catch (e: any) {
      setError(e?.message || "Sign in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.flex}
      >
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.hero}>
            <Text style={styles.brand} testID="hymn-wordmark">Hymn.</Text>
            <Text style={styles.tagline}>Remember what mattered.</Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="you@example.com"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              testID="sign-in-email-input"
            />
            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor={colors.onSurfaceTertiary}
              secureTextEntry
              testID="sign-in-password-input"
            />
            {error ? <Text style={styles.errorText} testID="sign-in-error">{error}</Text> : null}

            <Link href="/(auth)/forgot-password" asChild>
              <Pressable testID="forgot-password-link"><Text style={styles.link}>Forgot password?</Text></Pressable>
            </Link>
          </View>
        </ScrollView>

        <View style={styles.footer}>
          <Pressable
            style={[styles.cta, busy && styles.ctaDisabled]}
            onPress={onSubmit}
            disabled={busy}
            testID="sign-in-submit-button"
          >
            {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.ctaText}>Sign in</Text>}
          </Pressable>

          <View style={styles.dividerRow}>
            <View style={styles.divider} />
            <Text style={styles.dividerText}>or</Text>
            <View style={styles.divider} />
          </View>

          <GoogleAuthButton testID="sign-in-google-button" />

          <View style={styles.footerRow}>
            <Text style={styles.footerText}>New here? </Text>
            <Link href="/(auth)/sign-up" asChild>
              <Pressable testID="go-to-sign-up-link"><Text style={styles.link}>Create an account</Text></Pressable>
            </Link>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.xxl, paddingBottom: spacing.xl },
  hero: { alignItems: "center", marginTop: spacing.xxl, marginBottom: spacing.xxxl },
  brand: { fontFamily: fonts.displayBold, fontSize: 44, color: colors.onSurface, fontWeight: "700" },
  tagline: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  form: { gap: spacing.sm },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs, letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontSize: 16,
    color: colors.onSurface,
  },
  errorText: { color: colors.error, marginTop: spacing.sm, fontSize: 13 },
  link: { color: colors.brandPrimary, fontSize: 14, marginTop: spacing.md, fontWeight: "500" },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.lg, gap: spacing.md },
  cta: {
    backgroundColor: colors.onSurface,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
  footerRow: { flexDirection: "row", justifyContent: "center", alignItems: "center" },
  footerText: { color: colors.onSurfaceSecondary, fontSize: 14 },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginVertical: spacing.xs },
  divider: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerText: { color: colors.onSurfaceTertiary, fontSize: 12 },
});
