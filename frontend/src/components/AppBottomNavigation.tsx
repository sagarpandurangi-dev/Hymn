/**
 * Shared bottom navigation.
 *
 * Rendered by two owners:
 *   1. frontend/app/(tabs)/_layout.tsx — as the Tabs navigator's custom
 *      tabBar, so React Navigation keeps the mounted tab tree alive and
 *      restores scroll/state when the user switches tabs.
 *   2. frontend/app/_layout.tsx — above every authenticated root-Stack
 *      screen (/me, /goals/..., /projects/..., /tasks/..., /portfolio,
 *      /settings/..., /checkin/..., /planning/..., etc.), so the user
 *      can jump straight to any main destination without first popping
 *      back to a tab.
 *
 * The two mount points use the same visual implementation to guarantee
 * one consistent bar everywhere.
 *
 * Navigation semantics
 *   - Inside the Tabs navigator the parent passes `onSelectTab`, which
 *     delegates to the Tabs navigator and preserves the mounted tab tree.
 *   - Outside the Tabs navigator the parent still passes `onSelectTab`,
 *     which delegates to the root navigation container and targets the
 *     existing `(tabs)` route so its mounted tab tree is reused instead
 *     of being replaced.
 */
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useState } from "react";

import { colors, fonts, radius, spacing } from "@/src/lib/theme";

export type MainTabName =
  | "today"
  | "timeline"
  | "finance"
  | "knowledge";

type AppBottomNavigationProps = {
  activeRouteName?: string | null;
  onSelectTab: (name: MainTabName) => void;
};

type TabDefinition = {
  name: MainTabName;
  path: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  label: string;
  testID: string;
};

const TAB_DEFINITIONS: TabDefinition[] = [
  {
    name: "today",
    path: "/(tabs)/today",
    icon: "sunny-outline",
    label: "Today",
    testID: "tab-today",
  },
  {
    name: "timeline",
    path: "/(tabs)/timeline",
    icon: "time-outline",
    label: "Timeline",
    testID: "tab-timeline",
  },
  {
    name: "finance",
    path: "/(tabs)/finance",
    icon: "wallet-outline",
    label: "Finance",
    testID: "tab-finance",
  },
  {
    name: "knowledge",
    path: "/(tabs)/knowledge",
    icon: "school-outline",
    label: "Knowledge",
    testID: "tab-knowledge",
  },
];

function TabIcon({
  name,
  focused,
}: {
  name: React.ComponentProps<typeof Ionicons>["name"];
  focused: boolean;
}) {
  return (
    <Ionicons
      name={name}
      size={24}
      color={focused ? colors.onSurface : colors.onSurfaceTertiary}
    />
  );
}

function TabLabel({ label, focused }: { label: string; focused: boolean }) {
  return (
    <Text
      style={{
        fontSize: 11,
        marginTop: 2,
        color: focused ? colors.onSurface : colors.onSurfaceTertiary,
        fontWeight: focused ? "600" : "400",
      }}
    >
      {label}
    </Text>
  );
}

function ChooserModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const router = useRouter();
  // The 50 ms delay lets the Modal finish its fade-out animation before the
  // destination screen begins mounting. Removing it causes a visible jank
  // on both platforms, so it is preserved verbatim from the original
  // Tabs layout implementation.
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

export default function AppBottomNavigation(props: AppBottomNavigationProps) {
  const { activeRouteName, onSelectTab } = props;
  const insets = useSafeAreaInsets();
  const [chooserOpen, setChooserOpen] = useState(false);

  const barHeight = 62 + insets.bottom;

  // Both call sites must supply `onSelectTab`. The Tabs-owned copy delegates
  // to the Tabs navigator (preserving tab state); the root-owned copy
  // delegates to the root navigation container and targets the existing
  // `(tabs)` route (preserving its mounted tab tree instead of replacing it).
  const selectTab = (tab: TabDefinition) => {
    onSelectTab(tab.name);
  };

  return (
    <View pointerEvents="box-none">
      <View
        style={{
          height: barHeight,
          paddingBottom: insets.bottom,
          paddingTop: 6,
          backgroundColor: colors.surface,
          borderTopColor: colors.borderStrong,
          borderTopWidth: StyleSheet.hairlineWidth,
          flexDirection: "row",
        }}
      >
        {/* Today */}
        {renderTabButton(TAB_DEFINITIONS[0], activeRouteName, selectTab)}
        {/* Timeline */}
        {renderTabButton(TAB_DEFINITIONS[1], activeRouteName, selectTab)}
        {/* Center spacer — the floating Check-in button lives above this slot. */}
        <View style={styles.tabItem} />
        {/* Finance */}
        {renderTabButton(TAB_DEFINITIONS[2], activeRouteName, selectTab)}
        {/* Knowledge */}
        {renderTabButton(TAB_DEFINITIONS[3], activeRouteName, selectTab)}
      </View>

      <View
        style={[styles.centerButtonContainer, { bottom: insets.bottom + 14 }]}
        pointerEvents="box-none"
      >
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

function renderTabButton(
  tab: TabDefinition,
  activeRouteName: string | null | undefined,
  selectTab: (tab: TabDefinition) => void,
) {
  const focused = activeRouteName === tab.name;
  return (
    <Pressable
      key={tab.name}
      onPress={() => selectTab(tab)}
      style={styles.tabItem}
      testID={tab.testID}
      accessibilityRole="button"
      accessibilityState={{ selected: focused }}
    >
      <TabIcon name={tab.icon} focused={focused} />
      <TabLabel label={tab.label} focused={focused} />
    </Pressable>
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
