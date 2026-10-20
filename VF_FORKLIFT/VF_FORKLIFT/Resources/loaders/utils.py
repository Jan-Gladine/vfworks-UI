from typing import Any, Literal, Optional, cast

import albumentations as A  # pyright: ignore
import cv2
import numpy as np
from numpy.typing import NDArray
from ultralytics.utils.plotting import Annotator, colors


def preprocess_image(img_arr: NDArray[np.uint8]) -> NDArray[np.float32]:
    """Preprocess an image for inference using the YOLO model.

    Preprocessing steps:
    - Resize to 640 x 640
    - Normalize according to YOLO criteria (mean: 0, std: 1)
    - Reshape to (1, 3, 640, 640) and convert to float32

    Parameters
    ----------
    img_arr
        The input image as a numpy array of shape (H, W, C) and dtype uint8 (i.e. the
        raw image read by OpenCV with pixel values in the range [0, 255]).

    Returns
    -------
    NDArray
        The preprocessed image as a numpy array of shape (1, 3, 640, 640) and dtype
        float32.

    """

    predict_transform = A.Compose(
        [
            A.LongestMaxSize(max_size=640),
            A.PadIfNeeded(
                min_height=640,
                min_width=640,
                border_mode=cv2.BORDER_CONSTANT,  # pylint: disable=no-member
                fill=114,  # Standard YOLO padding color
            ),
            A.Normalize(mean=(0, 0, 0), std=(1, 1, 1), max_pixel_value=255.0),
        ]
    )

    # Shape: (640, 640, 3)
    processed_img = predict_transform(image=img_arr)["image"]

    # Convert to shape (1, 3, 640, 640) and float32
    processed_img = processed_img.transpose(2, 0, 1)
    processed_img = np.expand_dims(processed_img, axis=0).astype(np.float32)

    return processed_img


def draw_reject_circle(
    img: NDArray[Any],
    reject: bool,
    reject_indicator_location: Literal[
        "bottom_right", "bottom_left", "top_right", "top_left"
    ] = "bottom_right",
) -> None:
    """Draw a reject circle in the specified corner of the image.

    Parameters
    ----------
    img
        The image as a numpy array.
    reject
        Whether to draw a red circle (True) or green circle (False).
    reject_indicator_location
        The location where the reject circle should be placed.

    """
    indicator_color = (0, 255, 0) if not reject else (0, 0, 255)
    radius = img.shape[0] // 15
    margin = img.shape[0] // 10

    match reject_indicator_location:
        case "bottom_right":
            center = (img.shape[1] - radius - margin, img.shape[0] - radius - margin)
        case "bottom_left":
            center = (radius + margin, img.shape[0] - radius - margin)
        case "top_right":
            center = (img.shape[1] - radius - margin, radius + margin)
        case "top_left":
            center = (radius + margin, radius + margin)
        case _:
            raise ValueError(
                f"Invalid reject_indicator_location: {reject_indicator_location}"
            )

    cv2.circle(  # pylint: disable=no-member
        img=img, center=center, radius=radius, color=indicator_color, thickness=-1
    )


def render_sample_prediction_frame(
    image: NDArray[Any],
    detections: NDArray[Any],
    class_names: dict[int, str],
    reject: Optional[bool] = None,
    reject_indicator_location: Literal[
        "bottom_right", "bottom_left", "top_right", "top_left"
    ] = "bottom_right",
) -> NDArray[Any]:
    """Annotate and image with bounding boxes, class labels and confidence scores.

    Parameters
    ----------
    image
        The original image. This image will be annotated and returned.
    detections
        The detections from the YOLO model, expected to be in the shape (D, 6) with D
        the number of detections and each detection containing
        (x1, y1, x2, y2, confidence, class_id).
    class_names
        A mapping from class ID to class name.
    reject
        Whether this sample prediction was rejected or not. If True, a red circle will
        be drawn in the `reject_indicator_location` corner of the image. If False,
        a green circle will be drawn. If None, no circle will be drawn.
    reject_indicator_location
        The corner where the "REJECT" circle should be placed. Can be either
        "bottom_right", "bottom_left", "top_right", or "top_left".


    Returns
    -------
    NDArray
        The annotated image as a numpy array.

    """

    # Annotate the "REJECT" circle in the corner
    if reject is not None:
        draw_reject_circle(image, reject, reject_indicator_location)

    # Create the annotator on a copy of the original image
    annotator = Annotator(image.copy(), line_width=2, example=str(class_names))

    # Edge case: no detections
    if len(detections) == 0:
        return cast(NDArray[Any], annotator.result())

    # Unpack the detections into boxes, classes and scores
    boxes = detections[:, :4]
    classes = detections[:, 5].astype(int)
    scores = detections[:, 4]

    # Annotate each box to the image
    for box, cls_id, score in zip(boxes, classes, scores):
        cls_id = int(cls_id)
        label = f"{class_names.get(cls_id, 'Unknown')} {score:.2f}"

        # colors(cls_id, True) provides consistent, high-contrast colors
        annotator.box_label(box, label, color=colors(cls_id, True))  # type: ignore

    return cast(NDArray[Any], annotator.result())
