import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { useRouter } from "expo-router";

import { StepNav } from "@/src/components/welcome/WelcomeShell";
import { FocusStep, PromiseStep, TimezoneStep } from "@/src/components/welcome/IntroSteps";
import { SleepStep, WorkStep } from "@/src/components/welcome/WeekSteps";
import DumpStep from "@/src/components/welcome/DumpStep";
import PeopleStep from "@/src/components/welcome/PeopleStep";
import { MoneyStep, NotifyStep, PayoffStep } from "@/src/components/welcome/FinalSteps";
import { api } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { clearWelcome, loadWelcomeStep, saveWelcomeStep, WELCOME_OWNER_KEY } from "@/src/lib/welcome";
import { colors } from "@/src/lib/theme";

const TOTAL = 10;

/** Welcome wizard: one question per screen; resumes at the step reached. */
export default function WelcomeScreen() {
  const router = useRouter();
  const { user, refreshUser, signOut } = useAuth();
  const [step, setStep] = useState<number | null>(null);
  const finishingRef = useRef(false);

  // Progress belongs to one person: start fresh if another account used this device.
  useEffect(() => {
    if (!user?.id) return;
    // Setup already done (and not finishing right now): the wizard can't be re-run.
    if (user.portfolio_setup_completed_at && !finishingRef.current) {
      router.replace("/(tabs)/today");
      return;
    }
    (async () => {
      const owner = await AsyncStorage.getItem(WELCOME_OWNER_KEY).catch(() => null);
      if (owner !== user.id) {
        await clearWelcome();
        await AsyncStorage.setItem(WELCOME_OWNER_KEY, user.id).catch(() => undefined);
      }
      const s = await loadWelcomeStep();
      setStep(Math.min(s, TOTAL - 1));
    })();
  }, [user?.id, user?.portfolio_setup_completed_at, router]);

  const go = useCallback((s: number) => {
    const n = Math.max(0, Math.min(TOTAL - 1, s));
    setStep(n);
    void saveWelcomeStep(n);
  }, []);

  // PUT setup-status completed; main currency comes from the bank account, else ₹.
  const finish = async (dest: "today" | "planner") => {
    finishingRef.current = true;
    try {
      let currency: string | undefined;
      if (!user?.portfolio_reporting_currency) {
        const accounts = await api.listFinancialAccounts().catch(() => []);
        currency = accounts[0]?.currency || "INR";
      }
      await api.updatePortfolioSetupStatus(currency ? { reporting_currency: currency, completed: true } : { completed: true });
      await clearWelcome();
      await refreshUser();
      router.replace(dest === "planner" ? "/(tabs)/planning-space" : "/(tabs)/today");
    } catch (e) {
      finishingRef.current = false;
      throw e;
    }
  };

  if (step === null) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface }}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View>
    );
  }

  const nav: StepNav = { index: step, total: TOTAL, back: () => go(step - 1), skip: () => go(step + 1), next: () => go(step + 1) };

  switch (step) {
    case 0: return <PromiseStep nav={nav} />;
    case 1: return <FocusStep nav={nav} />;
    case 2: return <TimezoneStep nav={nav} />;
    case 3: return <WorkStep nav={nav} />;
    case 4: return <SleepStep nav={nav} />;
    case 5: return <DumpStep nav={nav} />;
    case 6: return <PeopleStep nav={nav} />;
    case 7: return <MoneyStep nav={nav} />;
    case 8: return <NotifyStep nav={nav} />;
    default: return <PayoffStep nav={nav} onFinish={finish} onSignOut={() => void signOut()} />;
  }
}
