"""HTTP API for the EWS web app. Also serves the built front end from web/dist."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import case_notes, presenters
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


class CaseNoteRequest(BaseModel):
    analyst: str = Field(default="", max_length=120)
    regenerate: bool = False


_FROM_ENV = object()


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

    @app.post("/api/datasets/upload")
    async def upload(files: list[UploadFile] = File(...), label: str = Form("Uploaded portfolio")):
        sources = {f.filename or "upload": await f.read() for f in files}
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
    def get_watchlist(run_id: str, q: str = "", band: list[str] = Query(None), main_product: list[str] = Query(None),
                      segment: list[str] = Query(None), portfolio: list[str] = Query(None),
                      delinquency_bucket: list[str] = Query(None), customer_type: list[str] = Query(None),
                      region: list[str] = Query(None), review: str = "", sort: str = "score", order: str = "desc",
                      page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500)):
        _, df = watchlist(run_id)
        params = dict(q=q, band=band, main_product=main_product, segment=segment, portfolio=portfolio,
                      delinquency_bucket=delinquency_bucket, customer_type=customer_type, region=region,
                      review=review, sort=sort, order=order)
        filtered = presenters.filter_watchlist(df, params)
        start = (page - 1) * page_size
        return {"total": int(len(filtered)), "page": page, "page_size": page_size,
                "rows": presenters.watchlist_rows(filtered.iloc[start:start + page_size]),
                "facets": presenters.facets(df)}

    @app.get("/api/runs/{run_id}/watchlist.csv")
    def export_watchlist(run_id: str, q: str = "", band: list[str] = Query(None), main_product: list[str] = Query(None),
                         segment: list[str] = Query(None), portfolio: list[str] = Query(None),
                         delinquency_bucket: list[str] = Query(None), review: str = ""):
        _, df = watchlist(run_id)
        filtered = presenters.filter_watchlist(df, dict(q=q, band=band, main_product=main_product, segment=segment,
                                                        portfolio=portfolio, delinquency_bucket=delinquency_bucket,
                                                        review=review))
        out = filtered.drop(columns=["_band_rank", "products"], errors="ignore").copy()
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
