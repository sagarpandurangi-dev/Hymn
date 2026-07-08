import { Tabs, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, View, Text } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing } from "@/src/lib/theme";

function TabIcon({ name, focused }: { name: keyof typeof Ionicons.glyphMap; focused: boolean }) {
  return <Ionicons name={name} size={24} color={focused ? colors.onSurface : colors.onSurfaceTertiary} />;
}

function TabLabel({ label, focused }: { label: string; focused: boolean }) {
  return (
    <Text style={{ fontSize: 11, marginTop: 2, color: focused ? colors.onSurface : colors.onSurfaceTertiary, fontWeight: focused ? "600" : "400" }}>
      {label}
    </Text>
  );
}

function CenterAddButton() {
  const router = useRouter();
  return (
    <View pointerEvents="box-none" style={styles.centerButtonWrap}>
      <Pressable
        onPress={() => router.push("/event/add")}
        style={({ pressed }) => [styles.centerButton, pressed && { transform: [{ scale: 0.96 }] }]}
        testID="tab-add-event-button"
        hitSlop={12}
      >
        <Ionicons name="add" size={28} color={colors.onBrandPrimary} />
      </Pressable>
    </View>
  );
}

export default function TabsLayout() {
  const insets = useSafeAreaInsets();
  const barHeight = 62 + insets.bottom;

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            height: barHeight,
            paddingBottom: insets.bottom,
            paddingTop: 6,
            backgroundColor: colors.surface,
            borderTopColor: colors.borderStrong,
            borderTopWidth: StyleSheet.hairlineWidth,
          },
          tabBarShowLabel: false,
        }}
      >
        <Tabs.Screen
          name="today"
          options={{
            tabBarButton: (props) => (
              <Pressable {...(props as any)} testID="tab-today" style={styles.tabItem}>
                <TabIcon name="sunny-outline" focused={!!props.accessibilityState?.selected} />
                <TabLabel label="Today" focused={!!props.accessibilityState?.selected} />
              </Pressable>
            ),
          }}
        />
        <Tabs.Screen
          name="timeline"
          options={{
            tabBarButton: (props) => (
              <Pressable {...(props as any)} testID="tab-timeline" style={styles.tabItem}>
                <TabIcon name="time-outline" focused={!!props.accessibilityState?.selected} />
                <TabLabel label="Timeline" focused={!!props.accessibilityState?.selected} />
              </Pressable>
            ),
          }}
        />
        <Tabs.Screen
          name="add-placeholder"
          options={{
            tabBarButton: () => <View style={styles.tabItem} />,
          }}
        />
        <Tabs.Screen
          name="finance"
          options={{
            tabBarButton: (props) => (
              <Pressable {...(props as any)} testID="tab-finance" style={styles.tabItem}>
                <TabIcon name="wallet-outline" focused={!!props.accessibilityState?.selected} />
                <TabLabel label="Finance" focused={!!props.accessibilityState?.selected} />
              </Pressable>
            ),
          }}
        />
        <Tabs.Screen
          name="me"
          options={{
            tabBarButton: (props) => (
              <Pressable {...(props as any)} testID="tab-me" style={styles.tabItem}>
                <TabIcon name="person-outline" focused={!!props.accessibilityState?.selected} />
                <TabLabel label="Me" focused={!!props.accessibilityState?.selected} />
              </Pressable>
            ),
          }}
        />
      </Tabs>
      <View style={[styles.centerButtonContainer, { bottom: insets.bottom + 14 }]} pointerEvents="box-none">
        <CenterAddButton />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  tabItem: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: spacing.xs },
  centerButtonContainer: {
    position: "absolute",
    left: 0,
    right: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  centerButtonWrap: { alignItems: "center", justifyContent: "center" },
  centerButton: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOpacity: 0.12,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
});
