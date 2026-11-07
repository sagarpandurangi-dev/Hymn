import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useAuth } from "@/src/lib/AuthContext";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export default function Index() {
  const { loading, startupError, retryStartup } = useAuth();

  if (startupError) {
    return (
      <View style={styles.container} testID="root-auth-error">
        <View style={styles.errorCard}>
          <Text style={styles.title}>Hymn couldn’t start</Text>
          <Text style={styles.message}>{startupError}</Text>
          <Pressable
            style={styles.retryButton}
            onPress={() => void retryStartup()}
            disabled={loading}
            testID="root-auth-retry"
          >
            <Text style={styles.retryButtonText}>Try again</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container} testID="root-loader">
      <ActivityIndicator color={colors.brandPrimary} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    padding: spacing.xl,
  },
  errorCard: {
    width: "100%",
    maxWidth: 420,
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.xl,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    backgroundColor: colors.surfaceSecondary,
  },
  title: {
    color: colors.onSurface,
    fontFamily: fonts.displayBold,
    fontSize: 24,
    textAlign: "center",
  },
  message: {
    color: colors.onSurfaceSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  retryButton: {
    marginTop: spacing.sm,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  retryButtonText: {
    color: colors.onBrandPrimary,
    fontSize: 14,
    fontWeight: "700",
  },
});
