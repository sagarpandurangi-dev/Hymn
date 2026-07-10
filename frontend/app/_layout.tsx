import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider, useAuth } from "@/src/lib/AuthContext";

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

function AuthGate() {
  const { user, loading } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    const seg0 = segments[0] as string | undefined;
    const inAuthGroup = seg0 === "(auth)";
    if (!user && !inAuthGroup) {
      router.replace("/(auth)/sign-in");
    } else if (user && inAuthGroup) {
      router.replace("/(tabs)/today");
    }
  }, [user, loading, segments, router]);

  return null;
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
          <Stack.Screen name="me" />
          <Stack.Screen name="knowledge/new" options={{ presentation: "modal", gestureEnabled: false }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
