import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageSquareText, Sparkles } from "lucide-react";
import { api } from "../api";
import { useWorkspace } from "../state";
import type { AskResult } from "../types";
import { ErrorNote, Spinner } from "./ui";

const EXAMPLES = [
  "Critical SMEs in Tamil Nadu not yet reviewed",
  "Textiles customers with receivable days rising",
  "Largest exposures in Karnataka that are elevated",
];

/** Turns a question into watchlist filters; the parent applies them to the URL. */
export function AskBar({ runId, onFilters }: { runId: string; onFilters: (r: AskResult) => void }) {
  const { config, analyst } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [last, setLast] = useState<AskResult | null>(null);
  const ask = useMutation({
    mutationFn: (q: string) => api.ask(runId, q, analyst),
    onSuccess: (r) => { setLast(r); onFilters(r); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (question.trim().length >= 3) ask.mutate(question.trim()); };
  const ai = config?.ai?.enabled;

  return (
    <div className="stack" style={{ gap: 8 }}>
      <form className="row wrap" onSubmit={submit} style={{ gap: 8 }}>
        <div className="search" style={{ flex: 1, minWidth: 260, width: "auto", borderColor: "var(--lime-strong)" }}>
          <Sparkles size={16} color="var(--forest)" aria-hidden />
          <label htmlFor="ask-ews" className="sr-only">Ask EWS</label>
          <input id="ask-ews" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
            placeholder="Ask EWS, e.g. “critical SMEs in Tamil Nadu not yet reviewed”" />
        </div>
        <button className="btn dark" disabled={ask.isPending || question.trim().length < 3}>
          {ask.isPending ? <Spinner /> : <MessageSquareText size={16} />}Ask
        </button>
      </form>
      {!last && (
        <div className="row wrap" style={{ gap: 6 }}>
          <span className="muted tiny">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="tag" style={{ cursor: "pointer" }}
              onClick={() => { setQuestion(ex); ask.mutate(ex); }}>{ex}</button>
          ))}
          <span className="faint tiny">{ai ? `Interpreted by ${config?.ai?.model}` : "Interpreted by keyword matching (no AI key)"}</span>
        </div>
      )}
      <ErrorNote error={ask.error} />
      {last && (
        <div className="callout info small">
          <Sparkles size={16} color="var(--forest)" />
          <span>
            <b>{last.total} customers.</b> {last.explanation}
            <span className="muted"> · {last.source === "keywords" ? "keyword matching" : `AI · ${last.model}`}</span>
            {last.error && <span className="muted"> · AI unavailable ({last.error}), used keywords</span>}
            {last.unsupported.length > 0 && <span> · Not applied: {last.unsupported.join("; ")}</span>}
            {last.dropped.length > 0 && <span className="muted"> · Ignored unknown values: {last.dropped.join(", ")}</span>}
            <span className="muted"> The filters below show exactly what was applied; adjust them freely.</span>
          </span>
        </div>
      )}
    </div>
  );
}
