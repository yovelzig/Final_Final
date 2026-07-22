"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { PageHeading } from "@/components/ui/PageHeading";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateLearner } from "@/hooks/useDashboard";

export default function SettingsPage() {
  const { account, learner, logout, logoutAll, refreshIdentity } = useAuth();
  const router = useRouter();
  const updateLearner = useUpdateLearner();

  const [displayName, setDisplayName] = useState(learner?.display_name ?? "");
  const [preferredLanguage, setPreferredLanguage] = useState(learner?.preferred_language ?? "en");
  const [dailyGoalMinutes, setDailyGoalMinutes] = useState(String(learner?.daily_goal_minutes ?? 10));
  const [saved, setSaved] = useState(false);
  const [isLoggingOutAll, setIsLoggingOutAll] = useState(false);
  const [revokedCount, setRevokedCount] = useState<number | null>(null);

  useEffect(() => {
    if (learner) {
      setDisplayName(learner.display_name);
      setPreferredLanguage(learner.preferred_language);
      setDailyGoalMinutes(String(learner.daily_goal_minutes));
    }
  }, [learner]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setSaved(false);
    const goal = Number(dailyGoalMinutes);
    updateLearner.mutate(
      {
        display_name: displayName.trim() || null,
        preferred_language: preferredLanguage.trim() || null,
        daily_goal_minutes: Number.isFinite(goal) && goal > 0 ? goal : null,
      },
      {
        onSuccess: async () => {
          await refreshIdentity();
          setSaved(true);
        },
      }
    );
  };

  const handleLogoutAll = async () => {
    setIsLoggingOutAll(true);
    try {
      const count = await logoutAll();
      setRevokedCount(count);
    } finally {
      router.push("/login");
    }
  };

  return (
    <div>
      <PageHeading title="Settings" />

      <div className="flex max-w-lg flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
          </CardHeader>
          <dl className="flex flex-col gap-3 text-sm">
            <div>
              <dt className="text-xs text-muted">Email</dt>
              <dd className="font-medium text-slate-900">{account?.email}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Role</dt>
              <dd>
                <Badge tone="neutral">{account?.role}</Badge>
              </dd>
            </div>
          </dl>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {updateLearner.isError ? <ErrorState error={updateLearner.error} /> : null}
            {saved ? (
              <Alert tone="success" role="status">
                Your settings have been saved.
              </Alert>
            ) : null}

            <FormField
              label="Display name"
              value={displayName}
              onChange={(event) => {
                setSaved(false);
                setDisplayName(event.target.value);
              }}
              required
            />
            <FormField
              label="Preferred language"
              value={preferredLanguage}
              onChange={(event) => {
                setSaved(false);
                setPreferredLanguage(event.target.value);
              }}
              hint="A two-letter language code, e.g. en, es, fr."
            />
            <FormField
              label="Daily goal (minutes)"
              type="number"
              min={5}
              max={240}
              value={dailyGoalMinutes}
              onChange={(event) => {
                setSaved(false);
                setDailyGoalMinutes(event.target.value);
              }}
            />

            <Button type="submit" isLoading={updateLearner.isPending} className="self-start">
              Save changes
            </Button>
          </form>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sessions</CardTitle>
          </CardHeader>
          {revokedCount !== null ? (
            <Alert tone="info" role="status" title="Signed out everywhere">
              {revokedCount} session(s) were signed out.
            </Alert>
          ) : (
            <div className="flex flex-col gap-3">
              <Button variant="ghost" onClick={() => void logout()} className="self-start">
                Log out
              </Button>
              <Button variant="danger" onClick={() => void handleLogoutAll()} isLoading={isLoggingOutAll} className="self-start">
                Log out of all devices
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
