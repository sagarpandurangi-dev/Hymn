import { Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/lib/AuthContext";
import { colors } from "@/src/lib/theme";

type Props = { testID?: string };

export default function HeaderAvatar({ testID = "header-avatar" }: Props) {
  const router = useRouter();
  const { user } = useAuth();
  const initial = (user?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <Pressable
      onPress={() => router.push("/me")}
      style={({ pressed }) => [styles.wrap, pressed && { opacity: 0.75 }]}
      hitSlop={10}
      testID={testID}
      accessibilityLabel="Profile"
      accessibilityRole="button"
    >
      <View style={styles.circle}>
        <Text style={styles.text}>{initial}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: 2 },
  circle: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  text: { color: colors.onBrandPrimary, fontSize: 15, fontWeight: "700" },
});
