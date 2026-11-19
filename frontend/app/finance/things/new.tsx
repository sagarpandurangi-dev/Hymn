import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import DateTimeField from "@/src/components/DateTimeField";
import { foldPageStyle } from "@/src/components/finance/foldUi";
import { LIFE_KINDS, LIFE_TYPES, LOAN_ACCOUNT_TYPES, lifeStyles as s, PremiumCard } from "@/src/components/finance/lifeObjects";
import { todayIso } from "@/src/lib/finance/format";
import { financeColors } from "@/src/lib/finance/theme";

type Opt = { code: string; label: string };

function Chips({ options, value, onChange, testPrefix }: { options: readonly Opt[]; value: string; onChange: (v: string) => void; testPrefix: string }) {
  return (
    <View style={s.chipRow}>
      {options.map((o) => {
        const on = o.code === value;
        return (
          <Pressable key={o.code} style={[s.chip, on && s.chipOn]} onPress={() => onChange(o.code)} testID={`${testPrefix}-${o.code}`}>
            <Text style={[s.chipText, on && s.chipTextOn]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Num({ label, value, onChange, testID, placeholder, integer }: { label: string; value: string; onChange: (v: string) => void; testID: string; placeholder?: string; integer?: boolean }) {
  return (
    <>
      <Text style={s.label}>{label}</Text>
      <TextInput
        style={s.input}
        value={value}
        onChangeText={(v) => onChange(v.replace(integer ? /[^0-9]/g : /[^0-9.]/g, ""))}
        keyboardType={integer ? "number-pad" : "decimal-pad"}
        placeholder={placeholder ?? "0"}
        placeholderTextColor={financeColors.inkMuted}
        testID={testID}
      />
    </>
  );
}

export default function NewThingScreen() {
  const router = useRouter();
  const [type, setType] = useState("asset");
  const [kind, setKind] = useState("car");
  const [name, setName] = useState("");
  const [startedOn, setStartedOn] = useState(todayIso());
  // Asset
  const [price, setPrice] = useState("");
  const [extraCosts, setExtraCosts] = useState("");
  const [lifeMonths, setLifeMonths] = useState("");
  const [resale, setResale] = useState("");
  // Loan
  const [accounts, setAccounts] = useState<{ id: string; name: string; currency: string }[]>([]);
  const [accountId, setAccountId] = useState("");
  const [loanAmount, setLoanAmount] = useState("");
  const [rate, setRate] = useState("");
  const [tenure, setTenure] = useState("");
  const [firstEmi, setFirstEmi] = useState("");
  const [method, setMethod] = useState("reducing");
  const [emi, setEmi] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [premium, setPremium] = useState(true);

  const loan = type === "liability" || kind === "loan" || kind === "credit_card";

  useEffect(() => {
    api.listFinancialAccounts()
      .then((rows) => setAccounts(rows.filter((r) => LOAN_ACCOUNT_TYPES.includes(r.account_type))))
      .catch(() => setAccounts([]));
  }, []);

  const save = async () => {
    setError("");
    if (!name.trim()) { setError("Give it a name."); return; }
    if (!startedOn) { setError("Pick a start date."); return; }
    const payload: Record<string, any> = { type, kind, name: name.trim(), started_on: startedOn };
    if (type === "asset") {
      if (price) payload.price = price;
      if (extraCosts) payload.extra_costs = extraCosts;
      if (lifeMonths) payload.expected_life_months = Number(lifeMonths);
      if (resale) payload.resale_value = resale;
    }
    if (loan) {
      if (!accountId) { setError("Pick the loan or card account."); return; }
      if (!loanAmount || !rate || !tenure || !firstEmi) { setError("Fill in loan amount, interest, tenure and first EMI date."); return; }
      payload.account_id = accountId;
      payload.loan_amount = loanAmount;
      payload.interest_rate = rate;
      payload.tenure_months = Number(tenure);
      payload.first_emi_date = firstEmi;
      payload.method = method;
      if (emi) payload.emi = emi;
      const acc = accounts.find((a) => a.id === accountId);
      if (acc) payload.currency = acc.currency;
    }
    setBusy(true);
    try {
      const created = await api.createLifeObject(payload);
      if (created?.id) router.replace(`/finance/things/${created.id}` as any);
      else router.back();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 403) setPremium(false);
      else setError(err.message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Add a thing" subtitle="Something you own, owe or run" />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
          {!premium ? (
            <PremiumCard text="Tracking what you own and owe is part of Premium." />
          ) : (
            <View>
              <Text style={s.label}>Type</Text>
              <Chips options={LIFE_TYPES} value={type} onChange={setType} testPrefix="thing-type" />
              <Text style={s.label}>Kind</Text>
              <Chips options={LIFE_KINDS} value={kind} onChange={setKind} testPrefix="thing-kind" />
              <Text style={s.label}>Name</Text>
              <TextInput style={s.input} value={name} onChangeText={setName} placeholder="e.g. Swift VXi" placeholderTextColor={financeColors.inkMuted} testID="thing-name" />
              <Text style={s.label}>Start date</Text>
              <DateTimeField mode="date" value={startedOn} onChange={setStartedOn} testID="thing-started-on" />

              {type === "asset" ? (
                <>
                  <Num label="Price" value={price} onChange={setPrice} testID="thing-price" />
                  <Num label="Extra costs (registration, insurance, setup…)" value={extraCosts} onChange={setExtraCosts} testID="thing-extra-costs" />
                  <Num label="Life in months" value={lifeMonths} onChange={setLifeMonths} testID="thing-life-months" placeholder="e.g. 96" integer />
                  <Num label="Resale value at the end" value={resale} onChange={setResale} testID="thing-resale" />
                </>
              ) : null}

              {loan ? (
                <>
                  <Text style={s.label}>Account</Text>
                  {accounts.length === 0 ? (
                    <Text style={s.body}>Add a loan or credit card account in your portfolio first.</Text>
                  ) : (
                    <Chips options={accounts.map((a) => ({ code: a.id, label: `${a.name} (${a.currency})` }))} value={accountId} onChange={setAccountId} testPrefix="thing-account" />
                  )}
                  <Num label="Loan amount" value={loanAmount} onChange={setLoanAmount} testID="thing-loan-amount" />
                  <Num label="Interest % a year" value={rate} onChange={setRate} testID="thing-rate" placeholder="e.g. 9.5" />
                  <Num label="Tenure in months" value={tenure} onChange={setTenure} testID="thing-tenure" placeholder="e.g. 60" integer />
                  <Text style={s.label}>First EMI date</Text>
                  <DateTimeField mode="date" value={firstEmi} onChange={setFirstEmi} testID="thing-first-emi" />
                  <Text style={s.label}>Interest</Text>
                  <Chips options={[{ code: "reducing", label: "Reducing" }, { code: "flat", label: "Flat" }]} value={method} onChange={setMethod} testPrefix="thing-method" />
                  <Num label="EMI (optional — we work it out if blank)" value={emi} onChange={setEmi} testID="thing-emi" />
                </>
              ) : null}

              {error ? <Text style={[s.error, { marginTop: 12 }]} testID="thing-error">{error}</Text> : null}
              <Pressable style={[s.primary, { marginTop: 20 }, busy && { opacity: 0.5 }]} onPress={save} disabled={busy} testID="thing-save">
                {busy ? <ActivityIndicator color={financeColors.card} /> : <Text style={s.primaryText}>Save</Text>}
              </Pressable>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
