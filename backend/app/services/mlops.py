"""Model status and background retraining (feedback loop: actual consumption retrains the forecast)."""
import sys, json, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
METRICS = ROOT / "ml" / "metrics.json"
state = {"training": False, "error": None}

def status():
    d = json.loads(METRICS.read_text()) if METRICS.exists() else {"trained_at": None, "metrics": {}}
    return {**d, **state}

def retrain():
    if state["training"]:
        raise ValueError("Training is already running")
    def run():
        state.update(training=True, error=None)
        try:
            from ml import forecast as fc
            fc.train_and_save(); fc._cache.clear()
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["training"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"started": True}
