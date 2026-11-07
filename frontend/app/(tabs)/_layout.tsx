import { Tabs } from "expo-router";

import AppBottomNavigation, {
  MainTabName,
} from "@/src/components/AppBottomNavigation";

/**
 * The Tabs navigator owns the mounted tree for the five tab routes.
 * It renders its own copy of the shared bottom navigation via the
 * custom `tabBar` prop so switching tabs is handled by React Navigation
 * (preserving tab state) rather than by Expo Router's root Stack.
 *
 * The root-Stack sibling of this component (in `app/_layout.tsx`) renders
 * the same shared bar on every authenticated non-tab screen, so the user
 * sees exactly one bar everywhere.
 */
export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
      }}
      tabBar={(props) => (
        <AppBottomNavigation
          activeRouteName={props.state.routes[props.state.index]?.name}
          onSelectTab={(name: MainTabName) => {
            props.navigation.navigate(name);
          }}
        />
      )}
    >
      <Tabs.Screen name="today" />
      <Tabs.Screen name="planning-space" options={{ href: null }} />
      <Tabs.Screen name="timeline" />
      <Tabs.Screen name="add-placeholder" options={{ href: null }} />
      <Tabs.Screen name="finance" />
      <Tabs.Screen name="knowledge" />
    </Tabs>
  );
}
