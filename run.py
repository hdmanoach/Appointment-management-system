from pathlib import Path
import sys

# Permet a Flask de trouver le package dans ./src sans export PYTHONPATH.
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from appointment_app import create_app


app = create_app()
