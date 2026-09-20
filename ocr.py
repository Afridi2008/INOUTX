# ============================================================
# INOUTX - OCR MODULE
# ============================================================

import cv2
import re

from paddleocr import PaddleOCR


# ============================================================
# GLOBAL OCR MODEL
# ============================================================

ocr = None


# ============================================================
# OCR CONFIGURATION
# ============================================================

FAST_ACCEPT_SCORE = 0.65
FALLBACK_ACCEPT_SCORE = 0.60


# ============================================================
# LOAD OCR
# ============================================================

def get_ocr():

    global ocr

    if ocr is None:

        print("=" * 60)
        print("Loading PaddleOCR...")
        print("=" * 60)

        ocr = PaddleOCR(
            lang="en",

            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,

            enable_mkldnn=False
        )

        print("PaddleOCR loaded successfully.")

    return ocr


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_plate_text(text):

    if text is None:
        return ""

    text = str(text).upper()

    text = text.replace(" ", "")
    text = text.replace(".", "")
    text = text.replace("-", "")
    text = text.replace("_", "")

    text = re.sub(
        r"[^A-Z0-9]",
        "",
        text
    )

    return text


# ============================================================
# VALIDATE PLATE
# ============================================================

def is_valid_plate(text):

    if not text:
        return False

    text = clean_plate_text(text)

    # Indian plates normally contain
    # letters + numbers
    if not (7 <= len(text) <= 12):
        return False

    has_letter = any(
        char.isalpha()
        for char in text
    )

    has_number = any(
        char.isdigit()
        for char in text
    )

    return (
        has_letter
        and
        has_number
    )


# ============================================================
# RUN RAW OCR
# ============================================================

def run_ocr(image):

    if image is None:
        return []

    if image.size == 0:
        return []

    try:

        ocr_model = get_ocr()

        # OCR expects BGR image
        if len(image.shape) == 2:

            image = cv2.cvtColor(
                image,
                cv2.COLOR_GRAY2BGR
            )

        results = ocr_model.predict(
            image
        )

        if not results:
            return []

        result = results[0]

        # PaddleOCR 3.x result object
        try:
            texts = result.get(
                "rec_texts",
                []
            )
        except Exception:
            texts = []

        try:
            scores = result.get(
                "rec_scores",
                []
            )
        except Exception:
            scores = []

        output = []

        for index, text in enumerate(texts):

            clean = clean_plate_text(
                text
            )

            if not clean:
                continue

            score = 0.0

            if index < len(scores):

                try:
                    score = float(
                        scores[index]
                    )

                except Exception:
                    score = 0.0

            output.append(
                (
                    clean,
                    score
                )
            )

        return output

    except Exception as e:

        print(
            "OCR engine error:",
            e
        )

        return []


# ============================================================
# BEST PLATE
# ============================================================

def get_best_plate(results):

    candidates = []

    for text, score in results:

        text = clean_plate_text(
            text
        )

        if not is_valid_plate(text):
            continue

        candidates.append(
            (
                text,
                float(score)
            )
        )

    if not candidates:
        return "", 0.0

    candidates.sort(
        key=lambda item: item[1],
        reverse=True
    )

    return candidates[0]


# ============================================================
# PREPROCESSING
# ============================================================

def create_preprocessed_images(image):

    if image is None:
        return []

    if image.size == 0:
        return []

    # Resize
    enlarged = cv2.resize(
        image,
        None,
        fx=4,
        fy=4,
        interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.cvtColor(
        enlarged,
        cv2.COLOR_BGR2GRAY
    )

    # CLAHE
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(
        gray
    )

    enhanced_bgr = cv2.cvtColor(
        enhanced,
        cv2.COLOR_GRAY2BGR
    )

    # OTSU
    _, otsu = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY
        +
        cv2.THRESH_OTSU
    )

    otsu_bgr = cv2.cvtColor(
        otsu,
        cv2.COLOR_GRAY2BGR
    )

    return [
        enlarged,
        enhanced_bgr,
        otsu_bgr
    ]


# ============================================================
# READ LICENSE PLATE
# ============================================================

def read_plate(image):

    if image is None:
        print("Invalid plate image.")
        return ""

    if image.size == 0:
        print("Empty plate image.")
        return ""

    try:

        height, width = image.shape[:2]

        print(
            f"Plate image: {width}x{height}"
        )

        # ----------------------------------------------------
        # FAST OCR
        # ----------------------------------------------------

        fast_image = cv2.resize(
            image,
            None,
            fx=4,
            fy=4,
            interpolation=cv2.INTER_CUBIC
        )

        print("Running fast OCR...")

        results = run_ocr(
            fast_image
        )

        text, score = get_best_plate(
            results
        )

        if text:

            print(
                f"Fast OCR: {text} "
                f"(confidence {score:.2f})"
            )

            if score >= FAST_ACCEPT_SCORE:

                return text

        fallback_text = text
        fallback_score = score

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        print(
            "Fast OCR not reliable."
        )

        print(
            "Running preprocessing fallback..."
        )

        images = create_preprocessed_images(
            image
        )

        best_text = fallback_text
        best_score = fallback_score

        # Maximum 2 fallback OCR calls
        for index, img in enumerate(
            images[1:],
            start=1
        ):

            print(
                f"Fallback OCR {index}/2..."
            )

            results = run_ocr(
                img
            )

            text, score = get_best_plate(
                results
            )

            if not text:
                continue

            if score > best_score:

                best_text = text
                best_score = score

            if score >= FALLBACK_ACCEPT_SCORE:

                print(
                    f"Fallback OCR: {text}"
                )

                print(
                    f"Confidence: {score:.2f}"
                )

                return text

        # ----------------------------------------------------
        # ACCEPT BEST RESULT
        # ----------------------------------------------------

        if (
            best_text
            and
            best_score >= FALLBACK_ACCEPT_SCORE
        ):

            print(
                f"Detected plate: "
                f"{best_text}"
            )

            return best_text

        print(
            "No reliable number plate detected."
        )

        return ""

    except Exception as e:

        print(
            "Plate OCR failed:",
            e
        )

        return ""


# ============================================================
# READ BUS BODY NUMBER
# ============================================================

def read_bus_number(image):

    if image is None:
        return ""

    if image.size == 0:
        return ""

    try:

        # ----------------------------------------------------
        # Resize bus crop
        # ----------------------------------------------------

        enlarged = cv2.resize(
            image,
            None,
            fx=2,
            fy=2,
            interpolation=cv2.INTER_CUBIC
        )

        results = run_ocr(
            enlarged
        )

        if not results:

            print(
                "Bus number OCR: nothing found."
            )

            return ""

        candidates = []

        for text, score in results:

            raw_text = str(
                text
            ).upper()

            # Keep digits only
            number = re.sub(
                r"[^0-9]",
                "",
                raw_text
            )

            # Bus number in current DB is "6"
            # but support up to 4 digits
            if 1 <= len(number) <= 4:

                candidates.append(
                    (
                        number,
                        score
                    )
                )

        if not candidates:

            print(
                "Bus number OCR: NOT READ"
            )

            return ""

        candidates.sort(
            key=lambda item: item[1],
            reverse=True
        )

        bus_number = candidates[0][0]

        print(
            "Detected Bus Number:",
            bus_number
        )

        return bus_number

    except Exception as e:

        print(
            "Bus number OCR error:",
            e
        )

        return ""