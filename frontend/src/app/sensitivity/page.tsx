"use client";

import { useEffect, useState } from "react";

import { fetchSensitivity, type SensitivityReport } from "@/lib/api";
import { pp } from "@/lib/format";
import { Callout, Card, Failed, Loading, Page, Stat } from "@/components/ui";
import { SlidersIcon, FlaskIcon, AlertIcon } from "@/components/icons";
import Tornado from "@/components/charts/Tornado";

/**
 * How much of the result survives the assumptions being wrong.
 *
 * The evaluation page reports what the run produced. This one reports how much
 * of that is load-bearing on numbers we chose rather than measured — which is
 * the question a reviewer asks second and a buyer asks first.
 */
export default function Sensitivity() {
  const [report, setReport] = useState<SensitivityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSensitivity().then(setReport).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <Failed error={error} />;
  if (!report) return <Loading what="the sweep" />;

  const c = report.committed;
  const breaker = report.breakers[0];
  const params = report.parameters;

  return (
    <Page
      crumbs={[{ label: "RecoverOS" }, { label: "Sensitivity", accent: true }]}
      title="How wrong could we be?"
      subtitle="Seventy-three numbers in this project were chosen, not measured. Every one of them is swept here, and the answer is recomputed — so the result comes with the range it survives in rather than a single figure."
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Stat
          label="Published net lift"
          value={pp(c.net_lift)}
          icon={<FlaskIcon size={17} />}
          sub={`95% CI ${pp(c.ci_lower)} to ${pp(c.ci_upper)}`}
        />
        <Stat
          label="Assumptions that matter"
          value={`${report.material_count} of ${params.length}`}
          icon={<SlidersIcon size={17} />}
          sub="Move the lift by more than two points"
        />
        <Stat
          label={breaker ? "Breaks when off by" : "Nothing tested breaks it"}
          value={breaker ? `${Math.abs(breaker.wrong_by_pct ?? 0)}%` : "—"}
          tone={breaker ? "warn" : "good"}
          icon={<AlertIcon size={17} />}
          sub={
            breaker
              ? breaker.label.toLowerCase()
              : `held from ×${Math.min(...report.sweep_factors)} to ×${Math.max(
                  ...report.sweep_factors,
                )}`
          }
        />
      </div>

      <Card
        title="What would have to be wrong"
        icon={<AlertIcon size={18} />}
        hint="The conclusion, not the exact figure"
      >
        {breaker ? (
          <>
            <p className="text-[14px] text-[var(--ink-2)] leading-relaxed mb-4">
              A significant positive lift survives every assumption tested,
              moved anywhere from{" "}
              <span className="text-[var(--ink)] tnum">
                ×{Math.min(...report.sweep_factors)}
              </span>{" "}
              to{" "}
              <span className="text-[var(--ink)] tnum">
                ×{Math.max(...report.sweep_factors)}
              </span>{" "}
              of the value we chose — with one exception.
            </p>
            <Callout tone="warn">
              <strong className="text-[var(--ink)]">{breaker.label}</strong>{" "}
              breaks it at{" "}
              <span className="tnum">×{breaker.breaking_point}</span>. Every
              intervention in the ladder would have to be{" "}
              <strong className="text-[var(--ink)]">
                {Math.abs(breaker.wrong_by_pct ?? 0)}% less effective
              </strong>{" "}
              than we assumed, all at once. Any single rung being wrong is not
              enough.
            </Callout>
          </>
        ) : (
          <Callout tone="good">
            Every assumption was swept across the full range one at a time and
            the lift stayed significant throughout.
          </Callout>
        )}
      </Card>

      <div className="mt-4">
        <Card
          title="Ranked by how much each moves the answer"
          icon={<SlidersIcon size={18} />}
          hint="Attack the top row first"
        >
          <Tornado
            rows={params}
            committed={c.net_lift}
            max={12}
          />
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Why this is a recomputation, not eighty re-runs">
          <p className="text-[14px] text-[var(--ink-2)] leading-relaxed">
            No decision module imports the outcome oracle. The classifier, the
            ladder, the policy engine and the detector cannot see it, so moving
            a base rate cannot change which messages were sent — only whether
            the customer paid. The actions are held exactly as recorded and the
            outcomes re-decided.
          </p>
          <p className="text-[14px] text-[var(--ink-2)] leading-relaxed mt-3">
            The architectural rule that keeps the experiment honest is the same
            one that makes this analysis cheap enough to run on every push.
          </p>
          <div className="mt-4">
            <Callout>
              <strong className="text-[var(--ink)]">
                What this cannot tell you.
              </strong>{" "}
              It varies our assumptions inside our model. If the shape of the
              model is wrong — if lift is not additive across touches, or if
              contacting someone twice annoys them into not paying — no amount
              of moving these numbers will reveal it. The only cure is real
              outcome data.
            </Callout>
          </div>
        </Card>
      </div>
    </Page>
  );
}
