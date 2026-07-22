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
  // Synchronous re-entry guard for handleChoose — set BEFORE
  // setPendingChoice() so a rapid double-tap cannot slip past the React
  // state update.
  const processingRef = useRef<boolean>(false);

  const finishFlow = useCallback(() => {
    const r = resolveRef.current;
    resolveRef.current = null;
    activePromiseRef.current = null;
    processingRef.current = false;
    setSession(null);
    setPendingChoice(null);
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
      // Synchronous re-entry guard — runs before any React state update
      // so a rapid double-tap cannot enter the flow twice.
      if (processingRef.current) return;
      processingRef.current = true;
      setPendingChoice(choice);

      const currentSession = session;
      if (!currentSession) {
        processingRef.current = false;
        return;
      }

      const targetPref: PostCreationDecompositionPreference =
        choice === "decompose" ? "always_decompose" : "always_skip";

      if (remember) {
        try {
          await setPostCreationDecompositionPreference(targetPref);
        } catch {
          // Show the message inside the still-visible modal for ~1.2s so
          // it is actually visible, then continue with navigation. Session
          // is NOT cleared and navigation does NOT start before this
          // interval completes.
          setErrorMessage("Your preference could not be saved.");
          await new Promise<void>((resolve) => setTimeout(resolve, 1200));
        }
      }

      // Navigate — this is the point where the caller's Promise unblocks.
      if (choice === "decompose") {
        goPlanning(currentSession.args.targetType, currentSession.args.targetId);
      } else {
        goDetail(currentSession.args.detailRoute);
      }

      finishFlow();
    },
    [
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
        // Fresh session — reset checkbox / processing / error / re-entry ref.
        processingRef.current = false;
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
