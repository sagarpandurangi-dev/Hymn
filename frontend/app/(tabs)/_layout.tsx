import { Tabs, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, View, Text } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useState } from "react";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

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

function ChooserModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const router = useRouter();
  const go = (path: string) => { onClose(); setTimeout(() => router.push(path as any), 50); };
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.chooserBackdrop} onPress={onClose} testID="checkin-chooser-modal">
        <Pressable style={styles.chooserSheet} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.chooserTitle}>Check in</Text>
          <Text style={styles.chooserSubtitle}>What are you recording?</Text>

          <Pressable style={styles.chooserRow} onPress={() => go("/checkin/goal")} testID="chooser-goal">
            <Ionicons name="flag-outline" size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.chooserRowTitle}>Goal check-in</Text>
              <Text style={styles.chooserRowText}>Log progress on an expected outcome</Text>
            </View>
          </Pressable>
          <Pressable style={styles.chooserRow} onPress={() => go("/checkin/project")} testID="chooser-project">
            <Ionicons name="briefcase-outline" size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.chooserRowTitle}>Project check-in</Text>
              <Text style={styles.chooserRowText}>Progress on a project (optionally a task)</Text>
            </View>
          </Pressable>
          <Pressable style={styles.chooserRow} onPress={() => go("/checkin/life")} testID="chooser-life">
            <Ionicons name="leaf-outline" size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.chooserRowTitle}>Life check-in</Text>
              <Text style={styles.chooserRowText}>Standalone note about your day</Text>
            </View>
          </Pressable>

          <Pressable style={styles.chooserCancel} onPress={onClose} testID="chooser-cancel">
            <Text style={styles.chooserCancelText}>Cancel</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export default function TabsLayout() {
  const insets = useSafeAreaInsets();
  const barHeight = 62 + insets.bottom;
  const [chooserOpen, setChooserOpen] = useState(false);

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
          options={{ tabBarButton: () => <View style={styles.tabItem} /> }}
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
          name="knowledge"
          options={{
            tabBarButton: (props) => (
              <Pressable {...(props as any)} testID="tab-knowledge" style={styles.tabItem}>
                <TabIcon name="school-outline" focused={!!props.accessibilityState?.selected} />
                <TabLabel label="Knowledge" focused={!!props.accessibilityState?.selected} />
              </Pressable>
            ),
          }}
        />
      </Tabs>

      <View style={[styles.centerButtonContainer, { bottom: insets.bottom + 14 }]} pointerEvents="box-none">
        <Pressable
          onPress={() => setChooserOpen(true)}
          style={({ pressed }) => [styles.centerButton, pressed && { transform: [{ scale: 0.96 }] }]}
          testID="tab-add-event-button"
          hitSlop={12}
        >
          <Ionicons name="add" size={28} color={colors.onBrandPrimary} />
        </Pressable>
      </View>

      <ChooserModal visible={chooserOpen} onClose={() => setChooserOpen(false)} />
    </View>
  );
}

const styles = StyleSheet.create({
  tabItem: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: spacing.xs },
  centerButtonContainer: { position: "absolute", left: 0, right: 0, alignItems: "center", justifyContent: "center" },
  centerButton: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
  chooserBackdrop: { flex: 1, backgroundColor: "rgba(30,30,28,0.55)", justifyContent: "flex-end" },
  chooserSheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.xl, paddingTop: spacing.xl, paddingBottom: spacing.xxl, gap: spacing.md,
  },
  chooserTitle: { fontFamily: fonts.displayBold, fontSize: 24, fontWeight: "700", color: colors.onSurface },
  chooserSubtitle: { fontSize: 13, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  chooserRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md,
  },
  chooserRowTitle: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
  chooserRowText: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  chooserCancel: { alignItems: "center", paddingVertical: spacing.md, marginTop: spacing.xs },
  chooserCancelText: { color: colors.onSurfaceSecondary, fontSize: 14 },
});
