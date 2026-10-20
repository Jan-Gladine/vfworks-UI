from pathlib import Path

from cv2 import imread
from modelguard.zoo import UltralyticsYOLO11

#from utils import preprocess_image, render_sample_prediction_frame


def load_model(model_location, validityframe):
    BASE_MODEL_PATH = "/app/nodes/CCM1/input/VF_FORKLIFT/Sources/yolo.pt"
    CHECKPOINT_PATH = "/app/nodes/CCM1/input/VF_FORKLIFT/Sources/monitoring_strategy_checkpoint.tar"

    monitoring_strategy = UltralyticsYOLO11.from_checkpoint_with_weights_path(
    model_weights=Path(BASE_MODEL_PATH),
    path=Path(CHECKPOINT_PATH)
    )
    return monitoring_strategy