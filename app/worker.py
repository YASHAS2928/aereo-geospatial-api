import json
import logging
import sys
from pathlib import Path

from app.config import Settings
from app.errors import InputError
from app.processing import process_file


def main():
    payload = json.loads(Path(sys.argv[1]).read_text())
    try:
        crs, features = process_file(
            payload["path"],
            payload["extension"],
            payload["source_crs"],
            Settings(**payload["settings"]),
        )
        result = {"crs": crs, "features": features}
    except InputError as exc:
        result = {"error": {"code": exc.code, "message": exc.message, "status": exc.status}}
    except Exception:
        logging.exception("Unexpected processing failure")
        result = {
            "error": {"code": "PROCESSING_FAILED", "message": "Processing failed", "status": 500}
        }
    Path(sys.argv[2]).write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
