"""HTTP API for the EWS web app. Also serves the built front end from web/dist."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import ask, briefings, case_notes, evidence, mapping, presenters
from api.registry import Registry, frame_records
from ews import engine
from ews.engine.config import load_profile
from ews.store.db import DECISIONS, Store
from ews.ml.service import PredictionService

ROOT = Path(__file__).resolve().parents[1]


class SampleRequest(BaseModel):
    profile: str
    variant: str = "clean"


class RunRequest(BaseModel):
    dataset_id: str
    profile: str


class ReviewRequest(BaseModel):
    decision: str
    reason: str = Field(min_length=1, max_length=2000)
    analyst: str = Field(min_length=1, max_length=120)
    ai_note_id: int | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    analyst: str = Field(default="", max_length=120)


class BriefingRequest(BaseModel):
    dimension: str
    value: str
    analyst: str = Field(default="", max_length=120)
    regenerate: bool = False


class MemoRequest(BaseModel):
    analyst: str = Field(default="", max_length=120)
    regenerate: bool = False


class EvidenceDecisionRequest(BaseModel):
    repayment_id: str
    accepted: bool
    note: str = Field(min_length=1, max_length=2000)
    analyst: str = Field(min_length=1, max_length=120)
    output_id: int | None = None


class CaseNoteRequest(BaseModel):
    analyst: str = Field(default="", max_length=120)
    regenerate: bool = False


_FROM_ENV = object()


def watch_params(q: str = "", band: list[str] = Query(None), main_product: list[str] = Query(None),
                 segment: list[str] = Query(None), portfolio: list[str] = Query(None),
                 delinquency_bucket: list[str] = Query(None), customer_type: list[str] = Query(None),
                 region: list[str] = Query(None), industry: list[str] = Query(None), signals: list[str] = Query(None),
                 score_min: float | None = None, score_max: float | None = None, review: str = "",
                 sort: str = "score", order: str = "desc") -> dict:
    """Watchlist filters shared by the table, the CSV export and Ask EWS."""
    return dict(q=q, band=band, main_product=main_product, segment=segment, portfolio=portfolio,
                delinquency_bucket=delinquency_bucket, customer_type=customer_type, region=region, industry=industry,
                signals=signals, score_min=score_min, score_max=score_max, review=review, sort=sort, order=order)


def create_app(var_dir: Path | None = None, data_root: Path | None = None, web_dist: Path | None = None,
               ai_provider=_FROM_ENV, ml_model_dir: Path | None = None) -> FastAPI:
    var_dir = Path(var_dir or os.environ.get("EWS_VAR_DIR", ROOT / "var"))
    data_root = Path(data_root or os.environ.get("EWS_DATA_ROOT", ROOT / "data"))
    web_dist = Path(web_dist or ROOT / "web" / "dist")
    store = Store(os.environ.get("EWS_DB_PATH", var_dir / "ews.sqlite3"))
    registry = Registry(var_dir, data_root, store)
    ml = PredictionService(ml_model_dir or os.environ.get("EWS_ML_MODEL_DIR", ROOT / "models/delinquency_3m"), store)
    if ai_provider is _FROM_ENV:
        ai_provider, ai_disabled_reason = case_notes.provider_from_env()
    else:
        ai_disabled_reason = None if ai_provider else "AI drafting is not configured."

    app = FastAPI(title="EWS API", version="1.0.0",
                  description="Early Warning System: data ingestion, risk scoring, watchlist and analyst review.")

    def run_or_404(run_id: str):
        try:
            return registry.run(run_id)
        except KeyError:
            raise HTTPException(404, "Assessment not found")

    def watchlist(run_id: str):
        run = run_or_404(run_id)
        return run, presenters.watchlist_frame(run, store.latest_reviews(run_id))

    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # ------------------------------------------------------------------ config
    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        profiles = []
        for name in engine.available_profiles():
            p = load_profile(name)
            profiles.append({"id": name, "description": p.get("description", ""), "currency": p.get("currency", ""),
                             "as_of": p.get("as_of")})
        return {"profiles": profiles, "decisions": list(DECISIONS), "bands": presenters.BANDS,
                "samples": registry.samples(),
                "ai": {"enabled": ai_provider is not None,
                       "provider": getattr(ai_provider, "name", None), "model": getattr(ai_provider, "model", None),
                       "disabled_reason": ai_disabled_reason, "prompt_version": case_notes.PROMPT_VERSION}}

    @app.get("/api/ml/model")
    def ml_model():
        return ml.info()

    @app.get("/api/runs/{run_id}/customers/{customer_id}/ml")
    def ml_prediction(run_id: str, customer_id: str):
        run = run_or_404(run_id)
        if customer_id not in run.results:
            raise HTTPException(404, "Customer not found in this assessment")
        return ml.predict(run, customer_id, store.alert(run_id, customer_id))

    @app.get("/api/runs/{run_id}/customers/{customer_id}/ml/history")
    def ml_history(run_id: str, customer_id: str):
        run = run_or_404(run_id)
        if customer_id not in run.results:
            raise HTTPException(404, "Customer not found in this assessment")
        return ml.history(store.alert(run_id, customer_id)["alert_id"])

    # ------------------------------------------------------------------ datasets
    @app.get("/api/datasets")
    def list_datasets():
        return registry.datasets()

    @app.post("/api/datasets/sample")
    def load_sample(req: SampleRequest):
        meta = registry.register_sample(req.profile, req.variant)
        return {**meta, "quality": presenters.quality_report(registry.dataset(meta["dataset_id"]))}

    @app.post("/api/datasets/propose-mapping")
    async def propose_mapping(files: list[UploadFile] = File(...)):
        sources = {f.filename or "upload": await f.read() for f in files}
        proposal, checks, source, model, error = mapping.propose(ai_provider, sources)
        return {**proposal.model_dump(), **checks, "targets": mapping.TARGETS, "source": source, "model": model,
                "error": error}

    @app.post("/api/datasets/upload")
    async def upload(files: list[UploadFile] = File(...), label: str = Form("Uploaded portfolio"),
                     column_mapping: str = Form("")):
        sources = {f.filename or "upload": await f.read() for f in files}
        if column_mapping:
            try:
                proposal = mapping.MappingProposal.model_validate_json(column_mapping)
            except ValueError as e:
                raise HTTPException(422, f"Invalid column mapping: {e}")
            proposal, _ = mapping.clean(proposal, mapping.describe(mapping.read_tables(sources)))
            sources = mapping.apply(sources, proposal)
        meta = registry.register(sources, label.strip() or "Uploaded portfolio")
        return {**meta, "quality": presenters.quality_report(registry.dataset(meta["dataset_id"]))}

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str):
        try:
            meta = registry.dataset_meta(dataset_id)
        except KeyError:
            raise HTTPException(404, "Dataset not found")
        return {**meta, "quality": presenters.quality_report(registry.dataset(dataset_id))}

    @app.get("/api/datasets/{dataset_id}/quarantined/{table}")
    def quarantined(dataset_id: str, table: str):
        ds = registry.dataset(dataset_id)
        return frame_records(ds.quarantined.get(table))

    @app.get("/api/datasets/{dataset_id}/tables/{table}")
    def preview(dataset_id: str, table: str, limit: int = Query(50, le=500)):
        ds = registry.dataset(dataset_id)
        if table not in ds.tables:
            raise HTTPException(404, "Table not found")
        return {"rows": frame_records(ds.tables[table], limit=limit), "total": int(len(ds.tables[table]))}

    # ------------------------------------------------------------------ runs
    @app.get("/api/runs")
    def list_runs():
        return store.runs()

    @app.post("/api/runs", status_code=201)
    def create_run(req: RunRequest):
        try:
            return registry.create_run(req.dataset_id, req.profile)
        except KeyError:
            raise HTTPException(404, "Dataset not found")

    @app.get("/api/runs/{run_id}/summary")
    def summary(run_id: str):
        run, df = watchlist(run_id)
        return presenters.summary(run, df, store.latest_reviews(run_id), presenters.quality_report(run.dataset))

    @app.get("/api/runs/{run_id}/watchlist")
    def get_watchlist(run_id: str, params: dict = Depends(watch_params),
                      page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500)):
        _, df = watchlist(run_id)
        filtered = presenters.filter_watchlist(df, params)
        start = (page - 1) * page_size
        return {"total": int(len(filtered)), "page": page, "page_size": page_size,
                "rows": presenters.watchlist_rows(filtered.iloc[start:start + page_size]),
                "facets": presenters.facets(df)}

    @app.post("/api/runs/{run_id}/ask")
    def ask_watchlist(run_id: str, req: AskRequest):
        run, df = watchlist(run_id)
        names = {s.signal_id: s.name for r in run.results.values() for s in r.signals}
        options = ask.build_options(presenters.facets(df), names)
        filters, meta, source, model, error = ask.interpret(ai_provider, req.question, options)
        filtered = presenters.filter_watchlist(df, filters)
        store.add_output("ask", run_id, req.question.strip(), source, model,
                         case_notes.input_hash({"q": req.question, "options": options}, source),
                         req.analyst, {"filters": filters, **meta}, {"dropped": meta["dropped"]}, error)
        return {"filters": filters, **meta, "source": source, "model": model, "error": error,
                "total": int(len(filtered)), "rows": presenters.watchlist_rows(filtered.head(10))}

    def saved_or_new(kind: str, run_id: str, subject: str, payload: dict, generate, analyst: str, regenerate: bool):
        """Reuse a saved AI output for identical input; otherwise generate and save a new version."""
        source = ai_provider.name if ai_provider else "template"
        digest = case_notes.input_hash(payload, f"{kind}:{source}:{getattr(ai_provider, 'model', '')}")
        if not regenerate:
            for saved in store.outputs(kind, run_id, subject):
                if saved["input_hash"] == digest and not saved["error"]:
                    return {**saved, "cached": True}
        result, checks, used, model, error = generate(ai_provider, payload)
        saved = store.add_output(kind, run_id, subject, used, model, digest, analyst, result.model_dump(), checks, error)
        return {**saved, "cached": False}

    def currency(run) -> str:
        return run.profile.get("currency", "INR")

    @app.post("/api/runs/{run_id}/clusters/briefing", status_code=201)
    def cluster_briefing(run_id: str, req: BriefingRequest):
        run, df = watchlist(run_id)
        cluster = next((c for c in run.clusters if c.dimension == req.dimension and c.value == req.value), None)
        if cluster is None:
            raise HTTPException(404, "Cluster not found in this assessment")
        names = {s.signal_id: s.name for r in run.results.values() for s in r.signals}
        payload = briefings.cluster_payload(presenters.cluster_dict(cluster, run, df), names, run.actions, currency(run))
        return saved_or_new("cluster_briefing", run_id, f"{req.dimension}::{req.value}", payload,
                            briefings.brief_cluster, req.analyst, req.regenerate)

    @app.get("/api/runs/{run_id}/clusters/briefings")
    def cluster_briefings(run_id: str, dimension: str, value: str):
        run_or_404(run_id)
        return store.outputs("cluster_briefing", run_id, f"{dimension}::{value}")

    def previous_run(run) -> dict | None:
        earlier = [r for r in store.runs() if r["profile"] == run.meta["profile"]
                   and r["created_at"] < run.meta["created_at"] and r["run_id"] != run.meta["run_id"]]
        return max(earlier, key=lambda r: r["created_at"]) if earlier else None

    @app.post("/api/runs/{run_id}/memo", status_code=201)
    def risk_memo(run_id: str, req: MemoRequest):
        run, df = watchlist(run_id)
        summary_now = presenters.summary(run, df, store.latest_reviews(run_id), presenters.quality_report(run.dataset))
        prev_meta, prev_summary, transitions = previous_run(run), None, None
        if prev_meta:
            prev, prev_df = watchlist(prev_meta["run_id"])
            prev_summary = presenters.summary(prev, prev_df, store.latest_reviews(prev_meta["run_id"]),
                                              presenters.quality_report(prev.dataset))
            transitions = briefings.band_transitions(df, prev_df)
        payload = briefings.memo_payload(summary_now, prev_summary, transitions, currency(run))
        record = saved_or_new("memo", run_id, "portfolio", payload, briefings.write_memo, req.analyst, req.regenerate)
        return {**record, "compared_with": prev_meta}

    @app.get("/api/runs/{run_id}/memo")
    def risk_memos(run_id: str):
        run_or_404(run_id)
        return store.outputs("memo", run_id, "portfolio")

    @app.get("/api/runs/{run_id}/memo/{output_id}.md")
    def risk_memo_markdown(run_id: str, output_id: int):
        try:
            record = store.output(output_id)
        except KeyError:
            raise HTTPException(404, "Memo not found")
        if record["kind"] != "memo" or record["run_id"] != run_id:
            raise HTTPException(404, "Memo not found")
        text = briefings.memo_markdown(briefings.RiskMemo(**record["output"]))
        return Response(text, media_type="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="risk_memo_{run_id[:8]}.md"'})

    @app.get("/api/runs/{run_id}/watchlist.csv")
    def export_watchlist(run_id: str, params: dict = Depends(watch_params)):
        _, df = watchlist(run_id)
        filtered = presenters.filter_watchlist(df, params)
        out = filtered.drop(columns=["_band_rank", "products", "active_signals"], errors="ignore").copy()
        out["top_factors"] = out["top_factors"].apply(lambda fs: "; ".join(f"{f['name']} ({f['points']})" for f in fs))
        buf = io.StringIO()
        out.to_csv(buf, index=False)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="watchlist_{run_id[:8]}.csv"'})

    @app.get("/api/runs/{run_id}/clusters")
    def clusters(run_id: str):
        run, df = watchlist(run_id)
        return [presenters.cluster_dict(c, run, df) for c in run.clusters]

    @app.get("/api/runs/{run_id}/customers/{customer_id}")
    def customer(run_id: str, customer_id: str):
        run, df = watchlist(run_id)
        if customer_id not in run.results:
            raise HTTPException(404, "Customer not found in this assessment")
        row = presenters.watchlist_rows(df[df["customer_id"] == customer_id])
        alert = store.alert(run_id, customer_id)
        return {**presenters.customer_detail(run, customer_id, row[0] if row else None),
                "alert_id": alert["alert_id"], "reviews": store.reviews(alert["alert_id"])}

    @app.get("/api/runs/{run_id}/customers/{customer_id}/alert.json")
    def original_alert(run_id: str, customer_id: str):
        try:
            alert = store.alert(run_id, customer_id)
        except KeyError:
            raise HTTPException(404, "Alert not found")
        return Response(alert["result_json"], media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{customer_id}_alert.json"'})

    @app.post("/api/runs/{run_id}/customers/{customer_id}/reviews", status_code=201)
    def add_review(run_id: str, customer_id: str, req: ReviewRequest):
        try:
            alert = store.alert(run_id, customer_id)
        except KeyError:
            raise HTTPException(404, "Alert not found")
        return store.add_review(alert["alert_id"], req.decision, req.reason, req.analyst, req.ai_note_id)

    def note_payload(run, customer_id: str, df):
        row = presenters.watchlist_rows(df[df["customer_id"] == customer_id])
        return case_notes.build_payload(run.results[customer_id], run.actions.get(customer_id, []), run.profile,
                                        row[0] if row else None, run.facts[customer_id].clusters)

    def customer_repayments(run, customer_id: str):
        rep = run.dataset.tables["repayments"]
        return rep[rep["customer_id"] == customer_id]

    @app.post("/api/runs/{run_id}/customers/{customer_id}/evidence-checks", status_code=201)
    async def check_evidence(run_id: str, customer_id: str, file: UploadFile = File(...),
                             repayment_id: str = Form(""), claim: str = Form(""), analyst: str = Form("")):
        run, df = watchlist(run_id)
        if customer_id not in run.results:
            raise HTTPException(404, "Customer not found in this assessment")
        reps = customer_repayments(run, customer_id)
        if repayment_id and repayment_id not in set(reps["repayment_id"]):
            raise HTTPException(422, "That instalment does not belong to this customer")
        data = await file.read()
        digest, media = evidence.save_file(var_dir, file.filename or "document", data)
        row = presenters.watchlist_rows(df[df["customer_id"] == customer_id])[0]
        context = {"customer": {k: row.get(k) for k in ("customer_type", "segment", "industry", "region")},
                   "claim": claim.strip(), "late_instalments": evidence.late_instalments(reps, repayment_id or None)}
        assessment, checks, source, model, error = evidence.assess(ai_provider, context, file.filename or "document",
                                                                  media, data)
        output = {**assessment.model_dump(), "file_name": file.filename, "file_sha": digest, "media_type": media,
                  "requested_repayment_id": repayment_id or None, "claim": claim.strip()}
        return store.add_output("evidence", run_id, customer_id, source, model, digest, analyst, output, checks, error)

    @app.get("/api/runs/{run_id}/customers/{customer_id}/evidence-checks")
    def evidence_checks(run_id: str, customer_id: str):
        run_or_404(run_id)
        return store.outputs("evidence", run_id, customer_id)

    @app.post("/api/runs/{run_id}/customers/{customer_id}/evidence-decisions", status_code=201)
    def decide_evidence(run_id: str, customer_id: str, req: EvidenceDecisionRequest):
        run = run_or_404(run_id)
        if req.repayment_id not in set(customer_repayments(run, customer_id)["repayment_id"]):
            raise HTTPException(422, "That instalment does not belong to this customer")
        if req.output_id is not None:
            try:
                check = store.output(req.output_id)
            except KeyError:
                raise HTTPException(404, "Evidence check not found")
            if check["kind"] != "evidence" or check["run_id"] != run_id or check["subject"] != customer_id:
                raise HTTPException(422, "That evidence check belongs to another customer")
        alert = store.alert(run_id, customer_id)
        return store.add_evidence_decision(alert["alert_id"], req.repayment_id, req.accepted, req.note, req.analyst,
                                           req.output_id)

    @app.get("/api/runs/{run_id}/customers/{customer_id}/evidence-decisions")
    def evidence_decisions(run_id: str, customer_id: str):
        try:
            alert = store.alert(run_id, customer_id)
        except KeyError:
            raise HTTPException(404, "Alert not found")
        return store.evidence_decisions(alert["alert_id"])

    @app.get("/api/runs/{run_id}/customers/{customer_id}/case-notes")
    def list_case_notes(run_id: str, customer_id: str):
        try:
            alert = store.alert(run_id, customer_id)
        except KeyError:
            raise HTTPException(404, "Alert not found")
        return store.notes(alert["alert_id"])

    @app.post("/api/runs/{run_id}/customers/{customer_id}/case-notes", status_code=201)
    def create_case_note(run_id: str, customer_id: str, req: CaseNoteRequest):
        run, df = watchlist(run_id)
        if customer_id not in run.results:
            raise HTTPException(404, "Customer not found in this assessment")
        alert = store.alert(run_id, customer_id)
        payload = note_payload(run, customer_id, df)
        source = ai_provider.name if ai_provider else "template"
        digest = case_notes.input_hash(payload, f"{source}:{getattr(ai_provider, 'model', '')}")
        if not req.regenerate:
            for saved in store.notes(alert["alert_id"]):
                if saved["input_hash"] == digest and not saved["error"]:
                    return {**saved, "cached": True}
        note, checks, used, model, error = case_notes.draft(ai_provider, payload)
        saved = store.add_note(alert["alert_id"], used, model, case_notes.PROMPT_VERSION, digest,
                               req.analyst, note.model_dump(), checks, error)
        return {**saved, "cached": False}

    @app.get("/api/runs/{run_id}/reviews")
    def review_log(run_id: str):
        run_or_404(run_id)
        return store.review_log(run_id)

    # ------------------------------------------------------------------ front end
    if web_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = web_dist / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(web_dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def not_built():
            return Response("<h1>EWS API is running</h1><p>The web app has not been built yet. Run "
                            "<code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, then restart. "
                            "API docs: <a href='/docs'>/docs</a></p>", media_type="text/html")

    return app


app = create_app()
