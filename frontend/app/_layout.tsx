import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider, useAuth } from "@/src/lib/AuthContext";
import AppBottomNavigation from "@/src/components/AppBottomNavigation";

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

function AuthGate() {
  const { user, loading } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    const seg0 = segments[0] as string | undefined;
    const seg1 = segments[1] as string | undefined;
    const inAuthGroup = seg0 === "(auth)";
    // /portfolio/setup is allowed while portfolio setup is incomplete — we
    // must not redirect the user away from the very screen they need to use.
    const onPortfolioSetup = seg0 === "portfolio" && seg1 === "setup";

    if (!user && !inAuthGroup) {
      router.replace("/(auth)/sign-in");
      return;
    }
    if (user && inAuthGroup) {
      router.replace("/(tabs)/today");
      return;
    }
    if (user && !user.portfolio_setup_completed_at && !onPortfolioSetup) {
      // Portfolio Setup is the mandatory gate for any authenticated user
      // whose profile is still incomplete. Once completed_at is populated
      // (see /api/portfolio/setup-status PUT) this block stops firing.
      router.replace("/portfolio/setup");
    }
  }, [user, loading, segments, router]);

  return null;
}

/**
 * The authenticated app shell. It owns the root Stack (so route-file
 * registrations stay exactly where they were before this change) and
 * also renders the shared `AppBottomNavigation` beneath the Stack on
 * every non-tab, non-auth screen. The Tabs navigator renders its own
 * copy of the same shared component as a custom `tabBar`, so the user
 * always sees exactly one bar.
 */
function AuthenticatedAppShell() {
  const { user, loading } = useAuth();
  const segments = useSegments();

  const seg0 = segments[0] as string | undefined;
  const seg1 = segments[1] as string | undefined;

  const onPortfolioSetup =
    seg0 === "portfolio" && seg1 === "setup";

  // Root-copy visibility:
  //   - Suppressed while auth is still loading or there is no user, so we
  //     never flash a navigation bar underneath the splash/auth screens.
  //   - Suppressed on `(auth)` routes and the mandatory `/portfolio/setup`
  //     flow because the user has not entered the authenticated app yet.
  //   - Suppressed on `(tabs)` routes because the Tabs navigator renders
  //     its own copy of the same bar, and we must never render two bars.
  //   - `Boolean(seg0)` guards against the initial empty-segments render
  //     where `seg0` is undefined.
  const showRootBottomNavigation =
    !loading &&
    Boolean(user) &&
    Boolean(seg0) &&
    seg0 !== "(auth)" &&
    seg0 !== "(tabs)" &&
    !onPortfolioSetup;

  return (
    <View style={{ flex: 1, backgroundColor: "#FBFBF9" }}>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FBFBF9" } }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="checkin/goal" options={{ presentation: "modal" }} />
        <Stack.Screen name="checkin/project" options={{ presentation: "modal" }} />
        <Stack.Screen name="checkin/life" options={{ presentation: "modal" }} />
        <Stack.Screen name="checkin/[id]" />
        <Stack.Screen name="checkin/edit/[id]" />
        <Stack.Screen name="domains/index" />
        <Stack.Screen name="domains/add" options={{ presentation: "modal" }} />
        <Stack.Screen name="domains/edit/[id]" options={{ presentation: "modal" }} />
        <Stack.Screen name="goals/index" />
        <Stack.Screen name="goals/add" options={{ presentation: "modal" }} />
        <Stack.Screen name="goals/[id]" />
        <Stack.Screen name="goals/edit/[id]" />
        <Stack.Screen name="projects/index" />
        <Stack.Screen name="projects/add" options={{ presentation: "modal" }} />
        <Stack.Screen name="projects/[id]" />
        <Stack.Screen name="projects/edit/[id]" />
        <Stack.Screen name="tasks/index" />
        <Stack.Screen name="tasks/add" options={{ presentation: "modal" }} />
        <Stack.Screen name="tasks/[id]" />
        <Stack.Screen name="tasks/edit/[id]" />
        <Stack.Screen name="expected-outcomes/add" options={{ presentation: "modal" }} />
        <Stack.Screen name="expected-outcomes/edit/[id]" options={{ presentation: "modal" }} />
        <Stack.Screen name="settings/overlay" />
        <Stack.Screen name="settings/decomposition" />
        <Stack.Screen name="me" />
        <Stack.Screen name="portfolio/setup" options={{ gestureEnabled: false }} />
        <Stack.Screen name="portfolio/index" />
        <Stack.Screen name="goals/merge" options={{ presentation: "modal", gestureEnabled: false }} />
      </Stack>

      {showRootBottomNavigation ? (
        <AppBottomNavigation activeRouteName={null} />
      ) : null}
    </View>
  );
}

export default function RootLayout() {
  const [loaded, error] = useIconFonts();

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <SafeAreaProvider>
      <AuthProvider>
        <AuthGate />
        <AuthenticatedAppShell />
      </AuthProvider>
    </SafeAreaProvider>
  );
}
