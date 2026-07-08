import { useRouter } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

// Placeholder for the reserved center-tab slot; the actual + button lives in the layout overlay.
export default function AddPlaceholder() {
  const router = useRouter();
  useEffect(() => { router.replace("/(tabs)/today"); }, [router]);
  return <View />;
}
