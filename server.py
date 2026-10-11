"""FastAPI backend: JSON API + static HTML/CSS frontend. Run: uvicorn server:app --reload"""
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import events
from pipeline.moderation import HarmfulContentError
from pipeline.run import run_pipeline

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Multi-Step Content Generator")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class RunRequest(BaseModel):
    idea: str


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/run")
def run(req: RunRequest):
    try:
        return run_pipeline(req.idea)
    except HarmfulContentError as exc:
        return JSONResponse(status_code=400, content={"blocked": True, "detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=502, content={"detail": f"LLM call failed: {exc}"})


@app.post("/api/stream")
def stream(req: RunRequest):
    """Same pipeline as /api/run, streamed as server-sent events while each stage finishes."""
    q: queue.Queue = queue.Queue()

    def worker():
        with events.listen(q.put):
            try:
                q.put({"type": "done", "result": run_pipeline(req.idea)})
            except HarmfulContentError as exc:
                q.put({"type": "blocked", "where": exc.where, "detail": str(exc)})
            except ValueError as exc:
                q.put({"type": "error", "detail": str(exc)})
            except Exception as exc:
                q.put({"type": "error", "detail": f"LLM call failed: {exc}"})
            finally:
                q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def sse():
        while (event := q.get()) is not None:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
