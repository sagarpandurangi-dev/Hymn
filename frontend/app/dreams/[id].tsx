import { useLocalSearchParams } from "expo-router";

import DreamMapScreen from "@/src/components/dreams/DreamMapScreen";

export default function DreamDetailScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return <DreamMapScreen proposalId={typeof id === "string" ? id : undefined} />;
}
