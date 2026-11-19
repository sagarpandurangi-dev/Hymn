import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { subscribeToast } from "@/src/lib/toast";
import { colors, radius, spacing } from "@/src/lib/theme";

/** Shows one message at a time at the top of the screen for ~4s. Tap to dismiss. */
export default function ToastHost() {
  const insets = useSafeAreaInsets();
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const unsub = subscribeToast((m) => {
      setMessage(m);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setMessage(null), 4000);
    });
    return () => {
      unsub();
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  if (!message) return null;
  return (
    <Pressable
      onPress={() => setMessage(null)}
      style={[styles.toast, { top: insets.top + spacing.sm }]}
      accessibilityRole="alert"
      testID="app-toast"
    >
      <Text style={styles.text}>{message}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  toast: {
    position: "absolute",
    left: spacing.lg,
    right: spacing.lg,
    backgroundColor: colors.onSurface,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    zIndex: 1000,
    elevation: 8,
  },
  text: { color: colors.surface, fontSize: 14, lineHeight: 20 },
});
