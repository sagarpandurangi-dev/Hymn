import { useLocalSearchParams } from "expo-router";

import DreamMapScreen from "@/src/components/dreams/DreamMapScreen";
import type { DreamSourceType, JourneyShape } from "@/src/lib/dreams";

const sourceTypes: DreamSourceType[] = ["intent", "learning", "goal", "project", "journey"];
const shapeIds: JourneyShape[] = [
  "professional_qualification",
  "learn_skill",
  "complete_course",
  "learn_subject",
  "read_book",
  "purchase",
  "trip",
  "meeting_event",
  "financial_target",
  "health_wellbeing",
  "custom",
];

export default function NewDreamScreen() {
  const params = useLocalSearchParams<{
    sourceType?: string;
    sourceId?: string;
    shape?: string;
  }>();
  const sourceType = sourceTypes.includes(params.sourceType as DreamSourceType)
    ? params.sourceType as DreamSourceType
    : "intent";
  const initialShape = shapeIds.includes(params.shape as JourneyShape)
    ? params.shape as JourneyShape
    : undefined;
  const sourceId = typeof params.sourceId === "string" ? params.sourceId : undefined;

  return (
    <DreamMapScreen
      initialShape={initialShape}
      sourceId={sourceId}
      sourceType={sourceType}
    />
  );
}
