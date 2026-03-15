"""
OMR Grading System — FastAPI backend (API-only)
================================================
Type A : YOLO-based grading (green layout)
Type B : SimpleBlobDetector engine

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Environment variables:
    ALLOWED_ORIGINS  – comma-separated origins, default "*"
                       e.g. "http://localhost:3000,https://myapp.com"
    MODEL_LAYOUT_PT  – path to YOLO layout model weights
    MODEL_XMARK_PT   – path to YOLO xmark model weights
"""

import io
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import List

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

# ─────────────────────────────────────────────
#  App setup
# ─────────────────────────────────────────────
app = FastAPI(
    title="OMR Grading System API",
    version="1.0.0",
    description="Optical Mark Recognition grading API — Type A (YOLO) and Type B (SimpleBlobDetector)",
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",")] if _raw_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR        = Path("data")
ANSWER_KEYS_DIR = DATA_DIR / "answer_keys"
RESULTS_DIR     = DATA_DIR / "results"
for d in [DATA_DIR, ANSWER_KEYS_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
#  Root / Health
# ─────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "service": "OMR Grading System API",
        "version": "1.0.0",
        "endpoints": {
            "health":            "GET  /api/health",
            "list_answer_keys":  "GET  /api/answer-keys",
            "create_answer_key": "POST /api/answer-keys",
            "get_answer_key":    "GET  /api/answer-keys/{key_id}",
            "delete_answer_key": "DELETE /api/answer-keys/{key_id}",
            "grade_single":      "POST /api/grade/single",
            "grade_batch":       "POST /api/grade/batch",
            "grade_batch_zip":   "POST /api/grade/batch/download",
            "get_result_image":  "GET  /api/results/{filename}",
        }
    }


@app.get("/api/health", tags=["Info"])
def health_check():
    return {"status": "ok"}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


_model_layout = None
_model_xmark  = None

MODEL_LAYOUT_PT = os.getenv(
    "MODEL_LAYOUT_PT",
    os.path.join(BASE_DIR, "models", "layout.pt")
)
MODEL_XMARK_PT = os.getenv(
    "MODEL_XMARK_PT",
    os.path.join(BASE_DIR, "models", "xmark.pt")
)


def get_models():
    global _model_layout, _model_xmark
    if _model_layout is None:
        try:
            from ultralytics import YOLO
            _model_layout = YOLO(MODEL_LAYOUT_PT)
            _model_xmark  = YOLO(MODEL_XMARK_PT)
        except Exception as e:
            raise RuntimeError(f"Cannot load YOLO models: {e}")
    return _model_layout, _model_xmark


# ═══════════════════════════════════════════════════════════════
#  TYPE B — SimpleBlobDetector engine
# ═══════════════════════════════════════════════════════════════

FIXED_W = 1748
FIXED_H = 1195

SC_X_COLS  = [172, 216, 262, 306, 350, 394]
SI_X_COLS  = [484, 528, 572, 616, 662, 704, 748, 792]
DIGIT_Y    = [626, 668, 712, 756, 798, 840, 884, 926, 970, 1012]

ANS_X_G0   = [880,  924,  968, 1012, 1058]
ANS_X_G1   = [1146, 1190, 1234, 1280, 1324]
ANS_X_G2   = [1414, 1458, 1502, 1548, 1592]
ANS_Y_ROWS = [244,  288,  330,  372,  414,  458,  500,  542,  586,  628,
              670,  712,  756,  798,  842,  884,  928,  970, 1014, 1056]

BOUNDS_B = {
    "subject_code": (120,  420,  560, 1042),
    "student_id":   (440,  820,  560, 1042),
    "answers":      (820, 1740,  195, 1105),
}

CHOICES_B        = "ABCDE"
SNAP             = 32

BLOB_MIN_AREA    = 200
BLOB_MAX_AREA    = 800
BLOB_CIRCULARITY = 0.6
BLOB_CONVEXITY   = 0.7
BLOB_INERTIA     = 0.4

FILLED_MIN_SIZE  = 28.0
FILLED_MAX_MEAN  = 120

COLORS_BGR_B = {
    "subject_code": (0,   112, 219),
    "student_id":   (0,   165, 255),
    "answers":      (0,     0, 220),
}


def _nearest(val: int, arr: list):
    diffs = [abs(val - v) for v in arr]
    idx   = int(np.argmin(diffs))
    return idx if diffs[idx] <= SNAP else None


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect    = np.zeros((4, 2), dtype=np.float32)
    s       = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff    = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _bubble_mean(gray: np.ndarray, x: int, y: int, r: int = 11) -> float:
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.circle(mask, (x, y), r, 255, -1)
    return cv2.mean(gray, mask=mask)[0]


def _is_filled(size: float, mean: float) -> bool:
    return size >= FILLED_MIN_SIZE and mean < FILLED_MAX_MEAN


def _auto_rotate(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    _, paper_mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    cnts, _ = cv2.findContours(paper_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return img
    cnts   = sorted(cnts, key=cv2.contourArea, reverse=True)
    px, py, pw, ph = cv2.boundingRect(cnts[0])
    paper  = gray[py:py+ph, px:px+pw]
    pph, ppw = paper.shape

    _, dark = cv2.threshold(paper, 100, 255, cv2.THRESH_BINARY_INV)

    best_rect = None
    best_area = 0
    best_quad = None

    quadrants = {
        "top_left":     (dark[:pph//2,  :ppw//2 ], 0,      0      ),
        "top_right":    (dark[:pph//2,  ppw//2: ], 0,      ppw//2 ),
        "bottom_left":  (dark[pph//2:,  :ppw//2 ], pph//2, 0      ),
        "bottom_right": (dark[pph//2:,  ppw//2: ], pph//2, ppw//2 ),
    }

    for quad_name, (region, oy, ox) in quadrants.items():
        dil = cv2.dilate(region, np.ones((5, 5), np.uint8), iterations=2)
        cc  = cv2.connectedComponentsWithStats(dil, connectivity=8)
        _, _, stats, _ = cc

        for i in range(1, stats.shape[0]):
            area = stats[i, cv2.CC_STAT_AREA]
            w    = stats[i, cv2.CC_STAT_WIDTH]
            h    = stats[i, cv2.CC_STAT_HEIGHT]
            x    = stats[i, cv2.CC_STAT_LEFT]
            y    = stats[i, cv2.CC_STAT_TOP]
            if area < 2000:
                continue
            ratio = w / max(h, 1)
            if ratio < 2.5 or ratio > 8:
                continue
            if w > ppw * 0.75 or h > pph * 0.25:
                continue
            if area > best_area:
                best_area = area
                best_rect = (ox + x, oy + y, w, h)
                best_quad = quad_name

    rotation_map = {
        "top_left":     None,
        "top_right":    cv2.ROTATE_90_CLOCKWISE,
        "bottom_right": cv2.ROTATE_180,
        "bottom_left":  cv2.ROTATE_90_COUNTERCLOCKWISE,
    }

    if best_quad is None:
        return img

    rot = rotation_map.get(best_quad)
    if rot is None:
        return img
    return cv2.rotate(img, rot)


def _warp_paper_b(img: np.ndarray):
    img  = _auto_rotate(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)

    corners = None
    for thresh_val in [180, 150, 120, 200]:
        _, bin_ = cv2.threshold(blur, thresh_val, 255, cv2.THRESH_BINARY)
        closed  = cv2.morphologyEx(bin_, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for cnt in contours[:5]:
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4 and cv2.contourArea(cnt) > 200_000:
                corners = _order_points(approx.reshape(4, 2).astype(np.float32))
                break
        if corners is not None:
            break

    if corners is None:
        hull    = cv2.convexHull(contours[0])
        peri    = cv2.arcLength(hull, True)
        approx  = cv2.approxPolyDP(hull, 0.02 * peri, True)
        corners = _order_points(approx.reshape(-1, 2).astype("float32"))

    dst         = np.float32([[0, 0], [FIXED_W, 0], [FIXED_W, FIXED_H], [0, FIXED_H]])
    M           = cv2.getPerspectiveTransform(corners, dst)
    warped      = cv2.warpPerspective(img, M, (FIXED_W, FIXED_H))
    warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    return warped, warped_gray


def _build_blob_detector() -> cv2.SimpleBlobDetector:
    p = cv2.SimpleBlobDetector_Params()
    p.filterByColor       = True;  p.blobColor       = 0
    p.filterByArea        = True;  p.minArea         = BLOB_MIN_AREA
    p.maxArea             = BLOB_MAX_AREA
    p.filterByCircularity = True;  p.minCircularity  = BLOB_CIRCULARITY
    p.filterByConvexity   = True;  p.minConvexity    = BLOB_CONVEXITY
    p.filterByInertia     = True;  p.minInertiaRatio = BLOB_INERTIA
    return cv2.SimpleBlobDetector_create(p)


def _detect_blobs_b(warped_gray: np.ndarray):
    detector  = _build_blob_detector()
    keypoints = detector.detect(warped_gray)
    result    = []
    for kp in keypoints:
        x, y = int(kp.pt[0]), int(kp.pt[1])
        mean = _bubble_mean(warped_gray, x, y)
        result.append((x, y, kp.size, mean))
    return result


def _decode_subject_code_b(blobs) -> str:
    x1, x2, y1, y2 = BOUNDS_B["subject_code"]
    digits = [None] * 6
    for (x, y, size, mean) in blobs:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        if not _is_filled(size, mean):
            continue
        ci = _nearest(x, SC_X_COLS)
        di = _nearest(y, DIGIT_Y)
        if ci is not None and di is not None:
            digits[ci] = di
    return "".join(str(d) if d is not None else "?" for d in digits)


def _decode_student_id_b(blobs) -> str:
    x1, x2, y1, y2 = BOUNDS_B["student_id"]
    digits = [None] * 8
    for (x, y, size, mean) in blobs:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        if not _is_filled(size, mean):
            continue
        ci = _nearest(x, SI_X_COLS)
        di = _nearest(y, DIGIT_Y)
        if ci is not None and di is not None:
            digits[ci] = di
    return "".join(str(d) if d is not None else "?" for d in digits)


def _decode_answers_b(blobs) -> dict:
    x1, x2, y1, y2 = BOUNDS_B["answers"]
    answers = {}
    for (x, y, size, mean) in blobs:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        if not _is_filled(size, mean):
            continue
        row_i = _nearest(y, ANS_Y_ROWS)
        if row_i is None:
            continue
        for g, x_cols in enumerate([ANS_X_G0, ANS_X_G1, ANS_X_G2]):
            ci = _nearest(x, x_cols)
            if ci is not None:
                q_num = g * 20 + row_i + 1
                answers[q_num] = CHOICES_B[ci]
                break
    return answers


def _annotate_b(warped, blobs, answers, ans_key, subject_code, student_id, score, total):
    out = warped.copy()

    def draw(x, y, color, filled=True):
        if filled:
            cv2.circle(out, (x, y), 18, color, -1)
            cv2.circle(out, (x, y), 18, (0, 0, 0), 1)
        else:
            cv2.circle(out, (x, y), 18, color, 2)

    for (x, y, size, mean) in blobs:
        if not _is_filled(size, mean):
            continue
        x1s, x2s, y1s, y2s = BOUNDS_B["subject_code"]
        x1i, x2i, y1i, y2i = BOUNDS_B["student_id"]
        x1a, x2a, y1a, y2a = BOUNDS_B["answers"]
        if x1s < x < x2s and y1s < y < y2s:
            draw(x, y, COLORS_BGR_B["subject_code"])
        elif x1i < x < x2i and y1i < y < y2i:
            draw(x, y, COLORS_BGR_B["student_id"])
        elif x1a < x < x2a and y1a < y < y2a:
            q_nums = [
                g * 20 + _nearest(y, ANS_Y_ROWS) + 1
                for g, x_cols in enumerate([ANS_X_G0, ANS_X_G1, ANS_X_G2])
                if _nearest(x, x_cols) is not None and _nearest(y, ANS_Y_ROWS) is not None
            ]
            if q_nums:
                q       = q_nums[0]
                key_ans = ans_key.get(str(q), "")
                color   = (0, 180, 0) if answers.get(q) == key_ans else (0, 0, 220)
            else:
                color = COLORS_BGR_B["answers"]
            draw(x, y, color)

    for sec, (x1, x2, y1, y2) in BOUNDS_B.items():
        cv2.rectangle(out, (x1, y1), (x2, y2), COLORS_BGR_B[sec], 2)

    cv2.putText(out, f"Subject: {subject_code}",
                (BOUNDS_B['subject_code'][0], BOUNDS_B['subject_code'][2] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS_BGR_B["subject_code"], 2)
    cv2.putText(out, f"Student ID: {student_id}",
                (BOUNDS_B['student_id'][0], BOUNDS_B['student_id'][2] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS_BGR_B["student_id"], 2)

    cv2.rectangle(out, (FIXED_W - 310, 10), (FIXED_W - 10, 60), (0, 0, 0), -1)
    cv2.putText(out, f"TOTAL: {score}/{total}",
                (FIXED_W - 300, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

    for g, x_cols in enumerate([ANS_X_G0, ANS_X_G1, ANS_X_G2]):
        for ri, row_y in enumerate(ANS_Y_ROWS):
            q = g * 20 + ri + 1
            if str(q) not in ans_key:
                continue
            given   = answers.get(q, "—")
            correct = ans_key.get(str(q), "")
            ok      = (given == correct)
            color   = (0, 150, 0) if ok else (0, 0, 200)
            label   = f"Q{q}:{given}"
            cv2.putText(out, label, (x_cols[-1] + 8, row_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

    return out


def grade_type_b(img: np.ndarray, ans_key: dict) -> tuple:
    warped, warped_gray = _warp_paper_b(img)
    blobs               = _detect_blobs_b(warped_gray)

    subject_code = _decode_subject_code_b(blobs)
    student_id   = _decode_student_id_b(blobs)
    raw_answers  = _decode_answers_b(blobs)

    total_score = 0
    details     = {}
    q_limit     = len(ans_key)

    for q_num in range(1, q_limit + 1):
        given      = raw_answers.get(q_num)
        correct    = ans_key.get(str(q_num), "").upper()
        is_correct = (given is not None and given == correct)
        if is_correct:
            total_score += 1
        details[str(q_num)] = {
            "given":      given or "-",
            "correct":    correct,
            "is_correct": is_correct,
        }

    annotated = _annotate_b(warped, blobs, raw_answers,
                            ans_key, subject_code, student_id,
                            total_score, q_limit)

    details["__meta__"] = {
        "subject_code": subject_code,
        "student_id":   student_id,
    }

    return total_score, annotated, details


# ═══════════════════════════════════════════════════════════════
#  TYPE A — YOLO-based grading
# ═══════════════════════════════════════════════════════════════

def order_points(pts):
    rect    = np.zeros((4, 2), dtype="float32")
    s       = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff    = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def grade_type_a(img: np.ndarray, ans_key: dict) -> tuple:
    labels    = ['A', 'B', 'C', 'D', 'E']
    maxWidth  = 300
    maxHeight = 1000
    model_layout, model_xmark = get_models()

    l_results = model_layout(img, conf=0.4, verbose=False)
    columns   = sorted(l_results[0].boxes, key=lambda b: b.xyxy[0][0])

    annotated   = img.copy()
    total_score = 0
    q_idx       = 0
    q_limit     = len(ans_key)
    details     = {}

    for col_box in columns:
        if q_idx >= q_limit:
            break

        x1, y1, x2, y2 = map(int, col_box.xyxy[0].cpu().numpy())
        pts  = np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], dtype="float32")
        rect = order_points(pts)
        dst  = np.array([[0,0],[maxWidth-1,0],[maxWidth-1,maxHeight-1],[0,maxHeight-1]], dtype="float32")
        M     = cv2.getPerspectiveTransform(rect, dst)
        M_inv = cv2.getPerspectiveTransform(dst, rect)

        warped_col      = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
        x_results       = model_xmark(warped_col, conf=0.15, verbose=False)
        x_boxes         = x_results[0].boxes.xywh.cpu().numpy()
        x_points_warped = [(box[0], box[1]) for box in x_boxes]

        row_h       = maxHeight / 15
        ans_start_x = int(maxWidth * 0.14)
        offset_x    = -2
        choice_w    = (maxWidth - ans_start_x) / 5

        for i in range(15):
            q_idx += 1
            if q_idx > q_limit:
                break

            curr_y1         = i * row_h
            curr_y2         = (i + 1) * row_h
            detected_in_row = []

            for wmx, wmy in x_points_warped:
                if curr_y1 <= wmy <= curr_y2:
                    for j in range(5):
                        cx1 = ans_start_x + (j * choice_w) + offset_x
                        cx2 = ans_start_x + ((j + 1) * choice_w) + offset_x
                        if cx1 <= wmx <= cx2:
                            detected_in_row.append(labels[j])
                            p      = np.array([[[wmx, wmy]]], dtype="float32")
                            p_real = cv2.perspectiveTransform(p, M_inv)[0][0]
                            cv2.circle(annotated, (int(p_real[0]), int(p_real[1])), 8, (0, 215, 255), -1)

            center_y_warped = curr_y1 + (row_h / 2)
            for j in range(5):
                gx1      = ans_start_x + (j * choice_w) + offset_x
                gx2      = ans_start_x + ((j + 1) * choice_w) + offset_x
                grid_pts = np.array([[[gx1, curr_y1]], [[gx2, curr_y1]],
                                     [[gx2, curr_y2]], [[gx1, curr_y2]]], dtype="float32")
                trans_grid = cv2.perspectiveTransform(grid_pts, M_inv).astype(int)
                cv2.polylines(annotated, [trans_grid], True, (0, 255, 0), 1)

            p_center       = np.array([[[ans_start_x / 4, center_y_warped]]], dtype="float32")
            p_real         = cv2.perspectiveTransform(p_center, M_inv)[0][0]
            real_x, real_y = int(p_real[0]), int(p_real[1])

            current_ans = ans_key.get(str(q_idx))
            is_correct  = (len(detected_in_row) == 1 and detected_in_row[0] == current_ans)
            if is_correct:
                total_score += 1

            given = (detected_in_row[0] if len(detected_in_row) == 1
                     else ("Multi" if detected_in_row else "-"))
            details[str(q_idx)] = {
                "given":      given,
                "correct":    current_ans,
                "is_correct": is_correct,
            }

            color     = (0, 150, 0) if is_correct else (0, 0, 255)
            label_txt = f"Q{q_idx}:{given}"
            cv2.putText(annotated, label_txt, (x1 - 105, real_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    if columns:
        last_col = columns[-1].xyxy[0].cpu().numpy()
        tx1, ty1 = int(last_col[0]), int(last_col[1])
        cv2.rectangle(annotated, (tx1, ty1 - 60), (tx1 + 250, ty1 - 10), (0, 0, 0), -1)
        cv2.putText(annotated, f"TOTAL: {total_score}/{q_limit}",
                    (tx1 + 10, ty1 - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    return total_score, annotated, details


# ═══════════════════════════════════════════════════════════════
#  Dispatcher
# ═══════════════════════════════════════════════════════════════

def _grade_single(img: np.ndarray, form_type: str, ans_key: dict):
    if form_type == "A":
        return grade_type_a(img, ans_key)
    elif form_type == "B":
        return grade_type_b(img, ans_key)
    else:
        raise HTTPException(400, f"Unknown form type: {form_type}")


# ═══════════════════════════════════════════════════════════════
#  Answer Key CRUD
# ═══════════════════════════════════════════════════════════════

@app.get("/api/answer-keys", tags=["Answer Keys"])
def list_answer_keys():
    keys = []
    for f in ANSWER_KEYS_DIR.glob("*.json"):
        with open(f) as fp:
            data = json.load(fp)
        keys.append({
            "id":             f.stem,
            "name":           data.get("name", f.stem),
            "form_type":      data.get("form_type", "A"),
            "question_count": len(data.get("answers", {})),
        })
    return keys


@app.post("/api/answer-keys", tags=["Answer Keys"])
async def create_answer_key(
    name:      str = Form(...),
    form_type: str = Form(...),
    answers:   str = Form(...),
):
    key_id  = str(uuid.uuid4())[:8]
    ans_obj = json.loads(answers)
    payload = {"name": name, "form_type": form_type, "answers": ans_obj}
    with open(ANSWER_KEYS_DIR / f"{key_id}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"id": key_id, "name": name, "form_type": form_type,
            "question_count": len(ans_obj)}


@app.get("/api/answer-keys/{key_id}", tags=["Answer Keys"])
def get_answer_key(key_id: str):
    path = ANSWER_KEYS_DIR / f"{key_id}.json"
    if not path.exists():
        raise HTTPException(404, "Answer key not found")
    with open(path) as f:
        return json.load(f)


@app.delete("/api/answer-keys/{key_id}", tags=["Answer Keys"])
def delete_answer_key(key_id: str):
    path = ANSWER_KEYS_DIR / f"{key_id}.json"
    if not path.exists():
        raise HTTPException(404, "Answer key not found")
    path.unlink()
    return {"deleted": key_id}


# ═══════════════════════════════════════════════════════════════
#  Grading endpoints
# ═══════════════════════════════════════════════════════════════

@app.post("/api/grade/single", tags=["Grading"])
async def grade_single(
    file:          UploadFile = File(...),
    answer_key_id: str        = Form(...),
):
    key_path = ANSWER_KEYS_DIR / f"{answer_key_id}.json"
    if not key_path.exists():
        raise HTTPException(404, "Answer key not found")
    with open(key_path) as f:
        key_data = json.load(f)

    data = await file.read()
    img  = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Cannot decode image")

    score, annotated, details = _grade_single(img, key_data["form_type"], key_data["answers"])
    meta       = details.pop("__meta__", {})
    result_id  = str(uuid.uuid4())[:8]
    result_path = RESULTS_DIR / f"{result_id}.jpg"
    cv2.imwrite(str(result_path), annotated)

    return {
        "result_id":    result_id,
        "score":        score,
        "total":        len(key_data["answers"]),
        "percentage":   round(score / len(key_data["answers"]) * 100, 1),
        "details":      details,
        "subject_code": meta.get("subject_code"),
        "student_id":   meta.get("student_id"),
        "image_url":    f"/api/results/{result_id}.jpg",
    }


@app.post("/api/grade/batch", tags=["Grading"])
async def grade_batch(
    files:         List[UploadFile] = File(...),
    answer_key_id: str              = Form(...),
):
    key_path = ANSWER_KEYS_DIR / f"{answer_key_id}.json"
    if not key_path.exists():
        raise HTTPException(404, "Answer key not found")
    with open(key_path) as f:
        key_data = json.load(f)

    results = []
    for upload in files:
        data = await upload.read()
        img  = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            results.append({"filename": upload.filename, "error": "Cannot decode image"})
            continue
        try:
            score, annotated, details = _grade_single(img, key_data["form_type"], key_data["answers"])
            meta       = details.pop("__meta__", {})
            result_id  = str(uuid.uuid4())[:8]
            result_path = RESULTS_DIR / f"{result_id}.jpg"
            cv2.imwrite(str(result_path), annotated)
            results.append({
                "filename":     upload.filename,
                "result_id":    result_id,
                "score":        score,
                "total":        len(key_data["answers"]),
                "percentage":   round(score / len(key_data["answers"]) * 100, 1),
                "details":      details,
                "subject_code": meta.get("subject_code"),
                "student_id":   meta.get("student_id"),
                "image_url":    f"/api/results/{result_id}.jpg",
            })
        except Exception as e:
            results.append({"filename": upload.filename, "error": str(e)})

    return {"batch_results": results, "processed": len(results)}


@app.get("/api/results/{filename}", tags=["Results"])
def get_result_image(filename: str):
    path = RESULTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Result not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.post("/api/grade/batch/download", tags=["Grading"])
async def grade_batch_download(
    files:         List[UploadFile] = File(...),
    answer_key_id: str              = Form(...),
):
    """Grade batch and return ZIP of annotated images + CSV summary."""
    key_path = ANSWER_KEYS_DIR / f"{answer_key_id}.json"
    if not key_path.exists():
        raise HTTPException(404, "Answer key not found")
    with open(key_path) as f:
        key_data = json.load(f)

    zip_buf  = io.BytesIO()
    csv_rows = ["filename,subject_code,student_id,score,total,percentage"]

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for upload in files:
            data = await upload.read()
            img  = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            try:
                score, annotated, details = _grade_single(img, key_data["form_type"], key_data["answers"])
                meta  = details.pop("__meta__", {})
                total = len(key_data["answers"])
                pct   = round(score / total * 100, 1)
                _, buf = cv2.imencode(".jpg", annotated)
                stem  = Path(upload.filename).stem
                zf.writestr(f"{stem}_result.jpg", buf.tobytes())
                csv_rows.append(
                    f"{upload.filename},"
                    f"{meta.get('subject_code','')},"
                    f"{meta.get('student_id','')},"
                    f"{score},{total},{pct}"
                )
            except Exception as e:
                csv_rows.append(f"{upload.filename},,,ERROR,0,0 ({e})")
        zf.writestr("summary.csv", "\n".join(csv_rows))

    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=grading_results.zip"},
    )