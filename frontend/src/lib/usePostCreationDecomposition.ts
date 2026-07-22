import React, { useCallback, useState } from "react";
import { Platform, ToastAndroid } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/lib/AuthContext";
import type { PostCreationDecompositionPreference } from "@/src/lib/AuthContext";
import {
  PostCreationDecompositionModal,
  type DecompositionChoice,
} from "@/src/components/PostCreationDecompositionModal";

export type PlanningTargetType = "goal" | "project" | "journey";

export type HandleCreatedArgs = {
  targetType: PlanningTargetType;
  targetId: string;
  objectLabel: string;
  detailRoute: string;
};

type PendingState = {
  targetType: PlanningTargetType;
  targetId: string;
  objectLabel: string;
  detailRoute: string;
};

/**
 * Shared post-creation flow for user-created Goals, Projects and Learning
 * Journeys. The caller renders `element` inside its screen so the modal is
 * mounted at the correct level and awaits `handleCreatedPlannableObject`
 * after successful creation.
 */
export function usePostCreationDecomposition() {
  const router = useRouter();
  const { user, setPostCreationDecompositionPreference } = useAuth();

  const [pending, setPending] = useState<PendingState | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    if (Platform.OS === "android") {
      ToastAndroid.show(msg, ToastAndroid.SHORT);
    } else {
      // Best-effort inline error surfaced via state; screens can ignore.
      setErrorMessage(msg);
      setTimeout(() => setErrorMessage(null), 4000);
    }
  };

  const goPlanning = useCallback(
    (targetType: PlanningTargetType, targetId: string) => {
      router.replace(`/planning/${targetType}/${targetId}` as any);
    },
    [router],
  );

  const goDetail = useCallback(
    (detailRoute: string) => {
      router.replace(detailRoute as any);
    },
    [router],
  );

  const handleCreatedPlannableObject = useCallback(
    async (args: HandleCreatedArgs): Promise<void> => {
      const pref: PostCreationDecompositionPreference =
        (user?.post_creation_decomposition_preference as PostCreationDecompositionPreference) ||
        "always_ask";
      if (pref === "always_decompose") {
        goPlanning(args.targetType, args.targetId);
        return;
      }
      if (pref === "always_skip") {
        goDetail(args.detailRoute);
        return;
      }
      // always_ask (or missing)
      setPending({
        targetType: args.targetType,
        targetId: args.targetId,
        objectLabel: args.objectLabel,
        detailRoute: args.detailRoute,
      });
    },
    [user, goPlanning, goDetail],
  );

  const handleChoose = useCallback(
    async (choice: DecompositionChoice, remember: boolean) => {
      const current = pending;
      if (!current) return;
      // Clear the pending so the modal disappears; buttons are disabled
      // synchronously by the modal itself.
      setPending(null);

      const targetPref: PostCreationDecompositionPreference =
        choice === "decompose" ? "always_decompose" : "always_skip";

      if (remember) {
        try {
          await setPostCreationDecompositionPreference(targetPref);
        } catch {
          showToast("Your preference could not be saved.");
        }
      }

      if (choice === "decompose") {
        goPlanning(current.targetType, current.targetId);
      } else {
        goDetail(current.detailRoute);
      }
    },
    [pending, setPostCreationDecompositionPreference, goPlanning, goDetail],
  );

  const element = React.createElement(PostCreationDecompositionModal, {
    visible: pending !== null,
    objectLabel: pending?.objectLabel || "",
    onChoose: handleChoose,
  });

  return {
    handleCreatedPlannableObject,
    element,
    errorMessage,
  };
}
