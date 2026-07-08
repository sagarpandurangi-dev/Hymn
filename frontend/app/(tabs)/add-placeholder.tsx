import { useRouter } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

// Never actually rendered; the tab bar item is hidden and + button opens the modal.
export default function AddPlaceholder() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/event/add");
  }, [router]);
  return <View />;
}
