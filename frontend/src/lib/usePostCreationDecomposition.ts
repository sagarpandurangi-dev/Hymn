import React, { useCallback, useRef, useState } from "react";
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

type ModalSession = {
  args: HandleCreatedArgs;
  resolve: () => void;
};

/**
 * Shared post-creation flow. `handleCreatedPlannableObject()` returns a
 * Promise that only resolves after:
 *   1. the user picks an action (or the deterministic preference decides),
 *   2. any preference save attempt has finished, and
 *   3. navigation has been dispatched.
 *
 * That guarantees the calling creation form stays busy until the flow is
 * complete, so double-taps cannot produce duplicate objects.
 *
 * Only ONE post-creation decision is active at a time — repeated calls
 * receive the SAME pending Promise until it resolves.
 */
export function usePostCreationDecomposition() {
  const router = useRouter();
  const { user, setPostCreationDecompositionPreference } = useAuth();

  const [session, setSession] = useState<ModalSession | null>(null);
  const [remember, setRemember] = useState(false);
  const [pendingChoice, setPendingChoice] = useState<DecompositionChoice | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Single-flight lock so simultaneous callers reuse the same Promise.
  const activePromiseRef = useRef<Promise<void> | null>(null);
  const resolveRef = useRef<(() => void) | null>(null);

  const finishFlow = useCallback(() => {
    const r = resolveRef.current;
    resolveRef.current = null;
    activePromiseRef.current = null;
    setSession(null);
    setPendingChoice(null);
    // Keep the error visible briefly for the caller if it wants to observe;
    // errors that surfaced inside the modal are cleared on the next session.
    if (r) r();
  }, []);

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

  const handleChoose = useCallback(
    async (choice: DecompositionChoice) => {
      // Guard against duplicate presses — the modal disables both buttons +
      // the checkbox as soon as pendingChoice is set, but a synchronous
      // double-fire could still slip through in edge cases.
      if (pendingChoice !== null) return;
      setPendingChoice(choice);

      const currentSession = session;
      if (!currentSession) return;

      const targetPref: PostCreationDecompositionPreference =
        choice === "decompose" ? "always_decompose" : "always_skip";

      let saveFailed = false;
      if (remember) {
        try {
          await setPostCreationDecompositionPreference(targetPref);
        } catch {
          saveFailed = true;
          setErrorMessage("Your preference could not be saved.");
        }
      }

      // Navigate — this is the point where the caller's Promise is allowed
      // to unblock.
      if (choice === "decompose") {
        goPlanning(currentSession.args.targetType, currentSession.args.targetId);
      } else {
        goDetail(currentSession.args.detailRoute);
      }

      // If the save failed we surface the message but still resolve the
      // outer Promise so the creation form no longer stays busy.
      // (The error was shown inside the modal above.)
      // eslint-disable-next-line no-unused-expressions
      saveFailed;

      finishFlow();
    },
    [
      pendingChoice,
      session,
      remember,
      setPostCreationDecompositionPreference,
      goPlanning,
      goDetail,
      finishFlow,
    ],
  );

  const handleCreatedPlannableObject = useCallback(
    (args: HandleCreatedArgs): Promise<void> => {
      // Single-flight: if a flow is already running, reuse it.
      if (activePromiseRef.current) {
        return activePromiseRef.current;
      }

      const pref: PostCreationDecompositionPreference =
        (user?.post_creation_decomposition_preference as PostCreationDecompositionPreference) ||
        "always_ask";

      // Deterministic branches — no modal, no preference save required.
      if (pref === "always_decompose") {
        const promise = new Promise<void>((resolve) => {
          goPlanning(args.targetType, args.targetId);
          resolve();
        });
        return promise;
      }
      if (pref === "always_skip") {
        const promise = new Promise<void>((resolve) => {
          goDetail(args.detailRoute);
          resolve();
        });
        return promise;
      }

      // always_ask — mount the modal and hold the promise open.
      const promise = new Promise<void>((resolve) => {
        resolveRef.current = resolve;
        // Fresh session — reset checkbox / processing / error.
        setRemember(false);
        setPendingChoice(null);
        setErrorMessage(null);
        setSession({ args, resolve });
      });
      activePromiseRef.current = promise;
      return promise;
    },
    [user, goPlanning, goDetail],
  );

  const element = React.createElement(PostCreationDecompositionModal, {
    visible: session !== null,
    objectLabel: session?.args.objectLabel || "",
    remember,
    onRememberChange: setRemember,
    onChoose: handleChoose,
    pendingChoice,
    errorMessage,
  });

  return {
    handleCreatedPlannableObject,
    element,
    errorMessage,
  };
}
