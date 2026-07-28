import { Redirect, useLocalSearchParams } from "expo-router";

import type { DreamSourceType } from "@/src/lib/dreams";

const supported: DreamSourceType[] = ["goal", "project", "journey"];

/**
 * Compatibility doorway for saved links from Planning v1.
 *
 * Goal, Project, and Learning actions now converge on the shared Dream Engine;
 * this route deliberately contains no competing proposal UI or persistence path.
 */
export default function PlanningCompatibilityRoute() {
  const params = useLocalSearchParams<{
    targetType?: string;
    targetId?: string;
  }>();
  const sourceType = supported.includes(params.targetType as DreamSourceType)
    ? params.targetType as DreamSourceType
    : "goal";
  const sourceId = typeof params.targetId === "string" ? params.targetId : "";
  return (
    <Redirect
      href={`/dreams/new?sourceType=${sourceType}&sourceId=${encodeURIComponent(sourceId)}`}
    />
  );
}
