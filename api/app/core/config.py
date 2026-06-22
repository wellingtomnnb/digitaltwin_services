from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

MODEL_KERAS_PATH = DATA_DIR / "gru_model.keras"
MODEL_COLUMNS_PATH = DATA_DIR / "model_columns.pkl"
X_SCALER_PATH = DATA_DIR / "x_scaler.pkl"
Y_SCALER_PATH = DATA_DIR / "y_scaler.pkl"
FIREBASE_HOST = "https://digitaltwim-default-rtdb.firebaseio.com"
FIREBASE_COLLECTION = "digital_twin_dinamico_rev1"

WINDOW_SIZE = 20
HORIZON = 10
