import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { Star, Phone, Target, Zap, Loader2, AlertTriangle, ShieldAlert } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { getAgentProfile, getAgents, getUserMe, type AgentProfile } from "../../services/api";

const MinimalTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="-mt-8 rounded-lg border border-border bg-card/90 px-2 py-1 shadow-xl backdrop-blur-sm">
        <p className="text-[12px] font-bold text-success">{payload[0].value}%</p>
      </div>
    );
  }
  return null;
};

function scoreColor(score: number): string {
  if (score >= 85) return "text-success";
  if (score >= 75) return "text-primary";
  return "text-warning";
}

function StatCard({
  label, value, sub, icon: Icon, accent,
}: {
  label: string;
  value: string | number;
  sub: string;
  icon: typeof Star;
  accent: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-card/40 p-5 shadow-sm transition-colors hover:border-primary/30">
      <div className="mb-3 flex items-start justify-between">
        <h3 className="text-[12px] font-bold uppercase tracking-widest text-muted-foreground">{label}</h3>
        <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${accent}`}>
          <Icon className="h-[18px] w-[18px]" />
        </div>
      </div>
      <div className="text-3xl font-black leading-none text-foreground">{value}</div>
      <div className="mt-1 text-[12px] text-muted-foreground">{sub}</div>
    </div>
  );
}

function Bar({ label, value, textColor, barColor }: { label: string; value: number; textColor: string; barColor: string }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[13px] text-foreground">{label}</span>
        <span className={`text-[13px] font-bold ${textColor}`}>{value}%</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export function AgentDashboard() {
  const { agentId: routeAgentId } = useParams();
  const [data, setData] = useState<AgentProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadAgent = async () => {
      try {
        let targetId = routeAgentId;
        if (!targetId) {
          try {
            const currentUser = await getUserMe();
            if (currentUser.role === "agent") targetId = currentUser.id;
          } catch {
            /* fall back to first agent */
          }
        }
        if (!targetId) {
          const agents = await getAgents();
          if (agents.length === 0) {
            setError("No agents found in the database");
            return;
          }
          targetId = agents[0].id;
        }
        setData(await getAgentProfile(targetId));
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    };
    void loadAgent();
  }, [routeAgentId]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3 text-sm text-muted-foreground">Loading your dashboard…</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-warning" />
          <p className="text-sm font-semibold text-foreground">Failed to load agent data</p>
          <p className="mt-1 text-xs text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  const displayAvgResponseTime = data.avgResponseTime.trim().toLowerCase().endsWith("s")
    ? data.avgResponseTime.trim()
    : `${data.avgResponseTime}s`;

  return (
    <div className="space-y-6 p-4 md:p-8">
      {/* Hero */}
      <div className="overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-primary to-primary/75 p-7 text-primary-foreground shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <p className="text-[11px] font-extrabold uppercase tracking-[0.24em] text-primary-foreground/70">My Performance</p>
            <h2 className="mt-1.5 text-3xl font-black tracking-tight">{data.name}</h2>
            <p className="mt-1 text-[13px] text-primary-foreground/70">{data.role}</p>
          </div>
          <div className="text-right">
            <div className="text-5xl font-black leading-none">{data.overallScore}%</div>
            <div className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-primary-foreground/60">Overall Score</div>
          </div>
        </div>

        <div className="my-5 h-px bg-primary-foreground/15" />

        <div className="grid grid-cols-3 gap-6">
          {[
            { v: data.callsThisWeek, l: "Calls This Week" },
            { v: `#${data.teamRank}`, l: "Team Rank" },
            { v: `${data.resolutionRate}%`, l: "Resolution Rate" },
          ].map((m) => (
            <div key={m.l}>
              <div className="text-3xl font-black leading-none">{m.v}</div>
              <div className="mt-1 text-[11px] font-medium text-primary-foreground/60">{m.l}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Overall Score" value={`${data.overallScore}%`} sub="from all calls" icon={Star} accent="bg-success/10 text-success" />
        <StatCard label="Total Calls" value={data.totalCalls} sub="processed calls" icon={Phone} accent="bg-primary/10 text-primary" />
        <StatCard label="Resolution Rate" value={`${data.resolutionRate}%`} sub="issues resolved" icon={Target} accent="bg-violet-500/10 text-violet-500" />
        <StatCard label="Avg Response" value={displayAvgResponseTime} sub="response time" icon={Zap} accent="bg-warning/10 text-warning" />
      </div>

      {/* Breakdown + trend */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
          <h3 className="text-[15px] font-bold text-foreground">My Score Breakdown</h3>
          <p className="mb-5 mt-0.5 text-[12px] text-muted-foreground">Averaged across my calls: empathy, policy, and resolution.</p>
          <div className="space-y-4">
            <Bar label="Empathy Score" value={data.empathyScore} textColor="text-primary" barColor="bg-primary" />
            <Bar label="Policy Adherence" value={data.policyScore} textColor="text-success" barColor="bg-success" />
            <Bar label="Resolution" value={data.resolutionScore} textColor="text-violet-500" barColor="bg-violet-500" />
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
          <h3 className="text-[15px] font-bold text-foreground">My Weekly Trend</h3>
          <p className="mb-4 mt-0.5 text-[12px] text-muted-foreground">Interaction score trend for my calls this week.</p>
          <ResponsiveContainer width="100%" height={190}>
            <LineChart data={data.weeklyTrend}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} opacity={0.5} />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} axisLine={{ stroke: "var(--border)" }} />
              <YAxis domain={[70, 100]} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} axisLine={{ stroke: "var(--border)" }} />
              <Tooltip content={<MinimalTooltip />} cursor={{ stroke: "var(--success)", strokeWidth: 1 }} />
              <Line type="monotone" dataKey="score" stroke="var(--success)" strokeWidth={3}
                dot={{ fill: "var(--card)", stroke: "var(--success)", strokeWidth: 2, r: 5 }} activeDot={{ r: 7, strokeWidth: 0 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent calls */}
      <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
        <h3 className="text-[15px] font-bold text-foreground">My Recent Calls</h3>
        <p className="mb-4 mt-0.5 text-[12px] text-muted-foreground">Personal calls only, sorted by date descending.</p>
        <div className="space-y-3">
          {data.recentCalls.map((call) => (
            <Link
              key={call.id}
              to={`/agent/calls/${call.id}`}
              className={`block rounded-2xl border p-4 transition-all hover:shadow-sm active:scale-[0.99] ${
                call.hasReview
                  ? "border-warning/30 bg-warning/5 hover:border-warning/50"
                  : "border-border bg-background/40 hover:border-primary/40 hover:bg-muted/20"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-bold text-foreground">{call.time}</span>
                  {call.hasReview && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-0.5 text-[11px] font-bold text-warning">
                      <ShieldAlert className="h-3 w-3" />
                      Review needed
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <div className={`text-2xl font-black leading-none ${scoreColor(call.score)}`}>{call.score}%</div>
                  <div className={`mt-1 text-[11px] font-bold ${call.resolved ? "text-success" : "text-destructive"}`}>
                    {call.resolved ? "Resolved" : "Unresolved"}
                  </div>
                </div>
              </div>
              <div className="mt-2 text-[12px] text-muted-foreground">{call.duration} • {call.language}</div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
