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
import { useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function ForgotPasswordScreen() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [email, setEmail] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchQuestion = async () => {
    setError(null);
    if (!email) { setError("Enter your email."); return; }
    setBusy(true);
    try {
      const res = await api.getSecurityQuestion(email.trim().toLowerCase());
      setQuestion(res.security_question);
      setStep(2);
    } catch (e: any) {
      setError(e?.message || "Could not fetch question");
    } finally {
      setBusy(false);
    }
  };

  const submitReset = async () => {
    setError(null);
    if (!answer || !newPassword) { setError("All fields are required."); return; }
    if (newPassword.length < 6) { setError("Password must be at least 6 characters."); return; }
    setBusy(true);
    try {
      await api.forgotPassword({
        email: email.trim().toLowerCase(),
        security_answer: answer.trim(),
        new_password: newPassword,
      });
      setStep(3);
    } catch (e: any) {
      setError(e?.message || "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.flex}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => router.back()} testID="forgot-back-button" hitSlop={12}>
            <Text style={styles.back}>← Back</Text>
          </Pressable>

          <View style={styles.hero}>
            <Text style={styles.brand}>Reset password</Text>
            <Text style={styles.tagline}>
              {step === 1 && "Enter your email to continue."}
              {step === 2 && "Answer your security question."}
              {step === 3 && "Password updated. You can sign in now."}
            </Text>
          </View>

          {step === 1 && (
            <>
              <Text style={styles.label}>Email</Text>
              <TextInput
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                placeholder="you@example.com"
                placeholderTextColor={colors.onSurfaceTertiary}
                keyboardType="email-address"
                autoCapitalize="none"
                testID="forgot-email-input"
              />
            </>
          )}

          {step === 2 && (
            <>
              <Text style={styles.label}>Your Security Question</Text>
              <Text style={styles.questionText}>{question}</Text>

              <Text style={styles.label}>Answer</Text>
              <TextInput
                style={styles.input}
                value={answer}
                onChangeText={setAnswer}
                placeholder="Your answer"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="none"
                testID="forgot-answer-input"
              />

              <Text style={styles.label}>New Password</Text>
              <TextInput
                style={styles.input}
                value={newPassword}
                onChangeText={setNewPassword}
                placeholder="At least 6 characters"
                placeholderTextColor={colors.onSurfaceTertiary}
                secureTextEntry
                testID="forgot-new-password-input"
              />
            </>
          )}

          {error ? <Text style={styles.errorText} testID="forgot-error">{error}</Text> : null}
        </ScrollView>

        <View style={styles.footer}>
          {step === 1 && (
            <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={fetchQuestion} disabled={busy} testID="forgot-continue-button">
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.ctaText}>Continue</Text>}
            </Pressable>
          )}
          {step === 2 && (
            <Pressable style={[styles.cta, busy && styles.ctaDisabled]} onPress={submitReset} disabled={busy} testID="forgot-reset-button">
              {busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <Text style={styles.ctaText}>Reset password</Text>}
            </Pressable>
          )}
          {step === 3 && (
            <Pressable style={styles.cta} onPress={() => router.replace("/(auth)/sign-in")} testID="forgot-go-signin-button">
              <Text style={styles.ctaText}>Back to sign in</Text>
            </Pressable>
          )}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  flex: { flex: 1 },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xl },
  back: { color: colors.onSurfaceSecondary, fontSize: 14, marginBottom: spacing.lg },
  hero: { marginBottom: spacing.xl },
  brand: { fontFamily: fonts.displayBold, fontSize: 32, color: colors.onSurface, fontWeight: "700" },
  tagline: { fontFamily: fonts.body, fontSize: 14, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  label: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.lg, marginBottom: spacing.xs, letterSpacing: 0.5 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontSize: 16,
    color: colors.onSurface,
  },
  questionText: { fontSize: 16, color: colors.onSurface, backgroundColor: colors.brandTertiary, padding: spacing.md, borderRadius: radius.sm, marginTop: spacing.xs },
  errorText: { color: colors.error, marginTop: spacing.md, fontSize: 13 },
  footer: { paddingHorizontal: spacing.xl, paddingBottom: spacing.lg },
  cta: { backgroundColor: colors.onSurface, paddingVertical: spacing.lg, borderRadius: radius.pill, alignItems: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: colors.onSurfaceInverse, fontSize: 16, fontWeight: "600" },
});
