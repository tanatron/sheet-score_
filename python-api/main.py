"""
OMR Grading System — FastAPI backend (API-only)
================================================
Type A : YOLO-based grading (green layout)
Type B : SimpleBlobDetector engine (OMR Timing Marks + Template Matching + Shear Correction)

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import io
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from sqlalchemy import or_

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from database import SessionLocal, GradingResultDB, AnswerKeyDB, GradingSessionDB

# ─────────────────────────────────────────────
#  App setup
# ─────────────────────────────────────────────
app = FastAPI(
    title="OMR Grading System API",
    version="1.0.0",
    description="Optical Mark Recognition grading API — Type A (YOLO) and Type B (Timing Marks Dynamic)",
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
#  TYPE B — OMR Timing Marks Hybrid Engine
# ═══════════════════════════════════════════════════════════════

FIXED_W = 1748
FIXED_H = 1195

# 📌 แม่พิมพ์มาตรฐาน (Fallback Templates)
SC_X_COLS  = [172, 216, 262, 306, 350, 394]
SI_X_COLS  = [460, 504, 548, 592, 636, 680, 724, 768, 812, 856]
DIGIT_Y    = [626, 668, 712, 756, 798, 840, 884, 926, 970, 1012]

ANS_X_G0   = [880,  924,  968, 1012, 1058]
ANS_X_G1   = [1146, 1190, 1234, 1280, 1324]
ANS_X_G2   = [1414, 1458, 1502, 1548, 1592]
ANS_Y_ROWS = [244,  288,  330,  372,  414,  458,  500,  542,  586,  628,
              670,  712,  756,  798,  842,  884,  928,  970, 1014, 1056]

BOUNDS_B = {
    "subject_code": (120,  420,  240, 1042),
    "student_id":   (430,  870,  240, 1042),
    "answers":      (870, 1740,  240, 1105),
}

CHOICES_B        = "ABCDE"
SNAP             = 32

# --- Blob detector params ---
BLOB_MIN_AREA    = 150
BLOB_MAX_AREA    = 1000
BLOB_CIRCULARITY = 0.5
BLOB_CONVEXITY   = 0.6
BLOB_INERTIA     = 0.3

# --- Contour detector params ---
CONTOUR_MIN_AREA = 120
CONTOUR_MAX_AREA = 1200
CONTOUR_MIN_CIRC = 0.45

# --- Adaptive fill classification ---
FILL_RATIO_THRESH   = 0.35
FILL_MIN_SIZE        = 18
FILL_CONFIDENCE_NORM = 0.7

DEDUP_DIST = 15

COLORS_BGR_B = {
    "subject_code": (0,   112, 219),
    "student_id":   (0,   165, 255),
    "answers":      (0,     0, 220),
    "correct":      (0,   180,   0),
    "wrong":        (0,     0, 220),
    "multi":        (0,   165, 255),
    "unanswered":   (128, 128, 128),
    "confidence":   (255, 200,   0),
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


def _preprocess_b(warped_gray: np.ndarray):
    clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(warped_gray)
    denoised = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)
    adaptive_bin = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=31, C=10
    )
    return enhanced, denoised, adaptive_bin


def _is_filled_adaptive(gray: np.ndarray, x: int, y: int, size: float, r: int = 14) -> tuple:
    h, w = gray.shape
    y1i, y2i = max(0, y - r), min(h, y + r)
    x1i, x2i = max(0, x - r), min(w, x + r)
    inner = gray[y1i:y2i, x1i:x2i]
    if inner.size == 0:
        return False, 0.0

    local_mean = float(np.mean(inner))

    r2 = r * 2
    y1o, y2o = max(0, y - r2), min(h, y + r2)
    x1o, x2o = max(0, x - r2), min(w, x + r2)
    outer = gray[y1o:y2o, x1o:x2o]
    bg_mean = float(np.mean(outer)) if outer.size > 0 else 200.0

    fill_ratio = 1.0 - (local_mean / max(bg_mean, 1.0))
    filled     = fill_ratio > FILL_RATIO_THRESH and size >= FILL_MIN_SIZE
    confidence = min(1.0, max(0.0, fill_ratio / FILL_CONFIDENCE_NORM))
    return filled, round(confidence, 3)


def _build_blob_detector() -> cv2.SimpleBlobDetector:
    p = cv2.SimpleBlobDetector_Params()
    p.filterByColor       = True;  p.blobColor        = 0
    p.filterByArea        = True;  p.minArea          = BLOB_MIN_AREA
    p.maxArea             = BLOB_MAX_AREA
    p.filterByCircularity = True;  p.minCircularity  = BLOB_CIRCULARITY
    p.filterByConvexity   = True;  p.minConvexity    = BLOB_CONVEXITY
    p.filterByInertia     = True;  p.minInertiaRatio = BLOB_INERTIA
    return cv2.SimpleBlobDetector_create(p)


def _detect_contour_bubbles(adaptive_bin: np.ndarray, gray: np.ndarray):
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(adaptive_bin, cv2.MORPH_OPEN, kernel, iterations=1)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    results = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < CONTOUR_MIN_AREA or area > CONTOUR_MAX_AREA:
            continue
        perimeter = cv2.arcLength(cnt, True)
        if perimeter == 0:
            continue
        circularity = 4 * np.pi * area / (perimeter * perimeter)
        if circularity < CONTOUR_MIN_CIRC:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        equiv_d = np.sqrt(4 * area / np.pi)

        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [cnt], -1, 255, -1)
        local_mean = cv2.mean(gray, mask=mask)[0]

        results.append((cx, cy, float(equiv_d), float(local_mean)))
    return results


def _dedup_bubbles(bubbles: list, dist_thresh: int = DEDUP_DIST) -> list:
    if not bubbles:
        return []
    bubbles = sorted(bubbles, key=lambda b: (b[0], b[1]))
    merged  = [bubbles[0]]
    for b in bubbles[1:]:
        is_dup = False
        for m in merged:
            if abs(b[0] - m[0]) < dist_thresh and abs(b[1] - m[1]) < dist_thresh:
                is_dup = True
                break
        if not is_dup:
            merged.append(b)
    return merged


def _detect_bubbles_hybrid(warped_gray: np.ndarray, enhanced: np.ndarray,
                           adaptive_bin: np.ndarray) -> list:
    contour_bubbles = _detect_contour_bubbles(adaptive_bin, enhanced)
    detector  = _build_blob_detector()
    keypoints = detector.detect(warped_gray)
    blob_bubbles = []
    for kp in keypoints:
        x, y = int(kp.pt[0]), int(kp.pt[1])
        mask = np.zeros(enhanced.shape, dtype=np.uint8)
        cv2.circle(mask, (x, y), 11, 255, -1)
        mean = cv2.mean(enhanced, mask=mask)[0]
        blob_bubbles.append((x, y, kp.size, float(mean)))

    all_bubbles = contour_bubbles + blob_bubbles
    return _dedup_bubbles(all_bubbles)


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
            
            ratio = w / max(h, 1)
            if area < 2000 or ratio < 2.5 or ratio > 8:
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


def _deskew_warped(warped: np.ndarray, warped_gray: np.ndarray):
    edges = cv2.Canny(warped_gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=200,
                            minLineLength=FIXED_W // 4, maxLineGap=20)
    if lines is None or len(lines) < 3:
        return warped, warped_gray

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 50:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        if abs(angle) < 3.0:
            angles.append(angle)

    if not angles:
        return warped, warped_gray

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.15:
        return warped, warped_gray

    h, w = warped.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    deskewed = cv2.warpAffine(warped, M, (w, h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    deskewed_gray = cv2.cvtColor(deskewed, cv2.COLOR_BGR2GRAY)
    return deskewed, deskewed_gray


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

    warped, warped_gray = _deskew_warped(warped, warped_gray)
    return warped, warped_gray


def _cluster_xs(xs: list, min_gap: int = 20) -> list:
    if not xs:
        return []
    xs = sorted(xs)
    clusters = [[xs[0]]]
    for v in xs[1:]:
        if v - clusters[-1][-1] < min_gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [int(round(sum(c) / len(c))) for c in clusters]


# ═══════════════════════════════════════════════════════════════
#  NEW: OMR Timing Marks (Template Matching Method)
# ═══════════════════════════════════════════════════════════════

def _extract_grid_from_timing_marks(bubbles: list, fallback_grid: dict) -> dict:
    grid = fallback_grid.copy()
    
    # 1. ดึงจุดไข่ปลาขอบซ้ายและล่าง
    left_ys = sorted([b[1] for b in bubbles if b[0] < 150])
    bottom_xs = sorted([b[0] for b in bubbles if b[1] > 1080])
    
    left_ys = _cluster_xs(left_ys, min_gap=15)
    bottom_xs = _cluster_xs(bottom_xs, min_gap=15)
    
    grid["DEBUG_LEFT"] = left_ys
    grid["DEBUG_BOTTOM"] = bottom_xs

    # 📌 ฟังก์ชันคำนวณการเลื่อนของกระดาษ (Shift) เพื่อเทียบแม่พิมพ์
    def get_shift(detected, template):
        if not detected or not template: return 0
        shifts = []
        for d in detected:
            diffs = [abs(d - t) for t in template]
            min_idx = int(np.argmin(diffs))
            if diffs[min_idx] < 22:  # ถ้าระยะห่างน้อยกว่า 22px ให้ถือว่าเป็นจุดเดียวกัน
                shifts.append(d - template[min_idx])
        return int(np.median(shifts)) if shifts else 0

    # 📌 ฟังก์ชันสวมแม่พิมพ์ (ทิ้งจุดที่เป็นเส้นคั่น (Divider) อัตโนมัติ)
    def match_template(detected, template, shift):
        shifted_template = [t + shift for t in template]
        matched = []
        for st in shifted_template:
            if not detected:
                matched.append(st)
                continue
            diffs = [abs(d - st) for d in detected]
            min_idx = int(np.argmin(diffs))
            if diffs[min_idx] <= 22:
                matched.append(detected[min_idx]) # ดึงจุดจริงมาใช้
            else:
                matched.append(st) # ถ้าแหว่ง ให้เติมจุดหลอกเข้าไปตามตำแหน่งที่ควรเป็น
        return matched

    # 2. จัดการแกน X (ล่าง) โดยเทียบกับโครงสร้างทั้งหมด
    all_x_templates = SC_X_COLS + SI_X_COLS + ANS_X_G0 + ANS_X_G1 + ANS_X_G2
    shift_x = get_shift(bottom_xs, all_x_templates)
    
    grid["SC_X_COLS"] = match_template(bottom_xs, SC_X_COLS, shift_x)
    grid["SI_X_COLS"] = match_template(bottom_xs, SI_X_COLS, shift_x)
    grid["ANS_X_G0"]  = match_template(bottom_xs, ANS_X_G0, shift_x)
    grid["ANS_X_G1"]  = match_template(bottom_xs, ANS_X_G1, shift_x)
    grid["ANS_X_G2"]  = match_template(bottom_xs, ANS_X_G2, shift_x)

    # 3. จัดการแกน Y (ซ้าย) 
    shift_y = get_shift(left_ys, ANS_Y_ROWS)
    grid["ANS_Y_ROWS"] = match_template(left_ys, ANS_Y_ROWS, shift_y)
    grid["DIGIT_Y"]    = match_template(left_ys, DIGIT_Y, shift_y)

    # 4. อัปเดต Bounding Box แบบเป๊ะๆ ไร้ขอบเหลื่อม
    try:
        dig_y1 = grid["DIGIT_Y"][0] - 25
        dig_y2 = grid["DIGIT_Y"][-1] + 25
        
        ans_y1 = grid["ANS_Y_ROWS"][0] - 25
        ans_y2 = grid["ANS_Y_ROWS"][-1] + 25
        
        sc_x1 = grid["SC_X_COLS"][0] - 25
        sc_x2 = grid["SC_X_COLS"][-1] + 25
        
        si_x1 = grid["SI_X_COLS"][0] - 25
        si_x2 = grid["SI_X_COLS"][-1] + 25
        
        ans_x1 = grid["ANS_X_G0"][0] - 30
        ans_x2 = grid["ANS_X_G2"][-1] + 35 
        
        grid["BOUNDS"] = {
            "subject_code": (sc_x1, sc_x2, dig_y1, dig_y2),
            "student_id":   (si_x1, si_x2, dig_y1, dig_y2),
            "answers":      (ans_x1, ans_x2, ans_y1, ans_y2)
        }
    except Exception as e:
        pass 
    
    return grid

# ═══════════════════════════════════════════════════════════════
#  NEW: Shear Calculation
# ═══════════════════════════════════════════════════════════════

def _calculate_shear(bubbles, grid):
    """คำนวณการเยื้อง (Shear) ของวงกลมคำตอบ เมื่อเทียบกับแกนตั้งฉาก"""
    ans_y_rows = grid.get("ANS_Y_ROWS", ANS_Y_ROWS)
    shear_offsets = []
    
    for row_y in ans_y_rows:
        row_bubbles = [b for b in bubbles if abs(b[1] - row_y) < SNAP]
        if not row_bubbles:
            shear_offsets.append(0)
            continue
            
        row_xs = [b[0] for b in row_bubbles]
        
        # หาวงกลมที่ใกล้เคียงกับคอลัมน์ A (คอลัมน์แรก) ของแต่ละกลุ่มมากที่สุด
        g0_a_diffs = [abs(x - grid["ANS_X_G0"][0]) for x in row_xs]
        g1_a_diffs = [abs(x - grid["ANS_X_G1"][0]) for x in row_xs]
        g2_a_diffs = [abs(x - grid["ANS_X_G2"][0]) for x in row_xs]
        
        min_diffs = []
        if g0_a_diffs: min_diffs.append(min(g0_a_diffs))
        if g1_a_diffs: min_diffs.append(min(g1_a_diffs))
        if g2_a_diffs: min_diffs.append(min(g2_a_diffs))

        # ถ้าระยะห่างน้อยกว่า 30 แปลว่าเราเจอจุดอ้างอิงที่ดี เอามาคำนวณ shear ได้เลย
        best_shear = 0
        if min_diffs and min(min_diffs) < 30:
            if min_diffs[0] == min(min_diffs):
                best_shear = row_xs[g0_a_diffs.index(min(min_diffs))] - grid["ANS_X_G0"][0]
            elif len(min_diffs) > 1 and min_diffs[1] == min(min_diffs):
                best_shear = row_xs[g1_a_diffs.index(min(min_diffs))] - grid["ANS_X_G1"][0]
            elif len(min_diffs) > 2 and min_diffs[2] == min(min_diffs):
                best_shear = row_xs[g2_a_diffs.index(min(min_diffs))] - grid["ANS_X_G2"][0]
                
        shear_offsets.append(int(best_shear))
        
    return shear_offsets


# ── Decode functions ──

def _decode_subject_code_b(bubbles, enhanced, grid) -> str:
    bounds = grid.get("BOUNDS", BOUNDS_B)
    x1, x2, y1, y2 = bounds["subject_code"]
    digits = [None] * 6
    sc_x   = grid["SC_X_COLS"]
    dy     = grid["DIGIT_Y"]
    snap   = grid.get("SNAP", SNAP)
    for (x, y, size, _mean) in bubbles:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        filled, conf = _is_filled_adaptive(enhanced, x, y, size)
        if not filled:
            continue
        diffs_y = [abs(y - v) for v in dy]
        di      = int(np.argmin(diffs_y))
        if diffs_y[di] > snap:
            continue
        diffs_x = [abs(x - v) for v in sc_x]
        ci      = int(np.argmin(diffs_x))
        if diffs_x[ci] > snap:
            continue
        digits[ci] = di
    return "".join(str(d) if d is not None else "?" for d in digits)


def _decode_student_id_b(bubbles, enhanced, grid) -> str:
    bounds = grid.get("BOUNDS", BOUNDS_B)
    x1, x2, y1, y2 = bounds["student_id"]
    digits = [None] * 10
    si_x   = grid["SI_X_COLS"]
    dy     = grid["DIGIT_Y"]
    snap   = grid.get("SNAP", SNAP)
    for (x, y, size, _mean) in bubbles:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        filled, conf = _is_filled_adaptive(enhanced, x, y, size)
        if not filled:
            continue
        diffs_y = [abs(y - v) for v in dy]
        di      = int(np.argmin(diffs_y))
        if diffs_y[di] > snap:
            continue
        diffs_x = [abs(x - v) for v in si_x]
        ci      = int(np.argmin(diffs_x))
        if diffs_x[ci] > snap:
            continue
        digits[ci] = di
    return "".join(str(d) if d is not None else "?" for d in digits)


def _decode_answers_b(bubbles, enhanced, grid) -> tuple:
    bounds = grid.get("BOUNDS", BOUNDS_B)
    x1, x2, y1, y2 = bounds["answers"]
    q_choices = {}
    snap      = grid.get("SNAP", SNAP)
    
    # 📌 คำนวณ Shear สดๆ
    shears = _calculate_shear(bubbles, grid)

    for (x, y, size, _mean) in bubbles:
        if not (x1 < x < x2 and y1 < y < y2):
            continue
        filled, conf = _is_filled_adaptive(enhanced, x, y, size)
        if not filled:
            continue
            
        row_ys = grid["ANS_Y_ROWS"]
        diffs  = [abs(y - v) for v in row_ys]
        row_i  = int(np.argmin(diffs))
        
        # คลายข้อจำกัดแกน Y ให้กว้างขึ้น เผื่อกระดาษโค้งงอ
        if diffs[row_i] > snap * 1.5: 
            continue
            
        # 📌 ชดเชยแกน X ด้วย Shear ที่คำนวณได้
        shear = shears[row_i]
        
        for g, x_cols in enumerate([grid["ANS_X_G0"], grid["ANS_X_G1"], grid["ANS_X_G2"]]):
            col_diffs = [abs((x - shear) - v) for v in x_cols]
            if not col_diffs: continue
            ci        = int(np.argmin(col_diffs))
            if col_diffs[ci] <= snap:
                q_num = g * 20 + row_i + 1
                if q_num not in q_choices:
                    q_choices[q_num] = []
                q_choices[q_num].append((CHOICES_B[ci], conf))
                break

    answers     = {}
    confidences = {}
    multi_marks = set()

    for q_num, choices in q_choices.items():
        if len(choices) == 1:
            answers[q_num]     = choices[0][0]
            confidences[q_num] = choices[0][1]
        else:
            multi_marks.add(q_num)
            choices_sorted = sorted(choices, key=lambda c: c[1], reverse=True)
            answers[q_num]     = "Multi"
            confidences[q_num] = choices_sorted[0][1]

    return answers, confidences, multi_marks


def _annotate_b(warped, bubbles, answers, confidences, multi_marks,
                ans_key, subject_code, student_id, score, total, enhanced, grid):
    out = warped.copy()
    bounds = grid.get("BOUNDS", BOUNDS_B)
    
    # 📌 คำนวณ Shear สดๆ
    shears = _calculate_shear(bubbles, grid)
    snap   = grid.get("SNAP", SNAP)

    def draw_circle(x, y, color, filled=True, thickness=-1):
        if filled:
            cv2.circle(out, (x, y), 18, color, -1)
            cv2.circle(out, (x, y), 18, (0, 0, 0), 1)
        else:
            cv2.circle(out, (x, y), 18, color, 2)

    for (x, y, size, _mean) in bubbles:
        filled, conf = _is_filled_adaptive(enhanced, x, y, size)
        if not filled:
            continue
        x1s, x2s, y1s, y2s = bounds["subject_code"]
        x1i, x2i, y1i, y2i = bounds["student_id"]
        x1a, x2a, y1a, y2a = bounds["answers"]
        if x1s < x < x2s and y1s < y < y2s:
            draw_circle(x, y, COLORS_BGR_B["subject_code"])
        elif x1i < x < x2i and y1i < y < y2i:
            draw_circle(x, y, COLORS_BGR_B["student_id"])
        elif x1a < x < x2a and y1a < y < y2a:
            # 📌 ชดเชยแกน Y
            row_diffs = [abs(y - v) for v in grid["ANS_Y_ROWS"]]
            row_i = int(np.argmin(row_diffs)) if row_diffs else None
            
            q_nums = []
            if row_i is not None and row_diffs[row_i] <= snap * 1.5:
                shear = shears[row_i]
                q_nums = [
                    g * 20 + row_i + 1
                    for g, x_cols in enumerate([grid["ANS_X_G0"], grid["ANS_X_G1"], grid["ANS_X_G2"]])
                    if _nearest(x - shear, x_cols) is not None
                ]
            if q_nums:
                q = q_nums[0]
                if q in multi_marks:
                    color = COLORS_BGR_B["multi"]
                else:
                    key_ans = ans_key.get(str(q), "")
                    color   = COLORS_BGR_B["correct"] if answers.get(q) == key_ans else COLORS_BGR_B["wrong"]
            else:
                color = COLORS_BGR_B["answers"]
            draw_circle(x, y, color)

    for g, x_cols in enumerate([grid["ANS_X_G0"], grid["ANS_X_G1"], grid["ANS_X_G2"]]):
        for ri, row_y in enumerate(grid["ANS_Y_ROWS"]):
            q = g * 20 + ri + 1
            correct_letter = ans_key.get(str(q), "")
            if not correct_letter:
                continue
            given = answers.get(q, "")
            if given != correct_letter:
                ci = CHOICES_B.index(correct_letter) if correct_letter in CHOICES_B else None
                if ci is not None:
                    # 📌 ชดเชยแกน X สำหรับวงกลมเฉลย
                    shear = shears[ri]
                    correct_x = int(x_cols[ci] + shear)
                    cv2.circle(out, (correct_x, row_y), 18, COLORS_BGR_B["correct"], 2)

    for sec, (bx1, bx2, by1, by2) in bounds.items():
        cv2.rectangle(out, (bx1, by1), (bx2, by2), COLORS_BGR_B[sec], 2)

    cv2.putText(out, f"Subject: {subject_code}",
                (bounds['subject_code'][0], bounds['subject_code'][2] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS_BGR_B["subject_code"], 2)
    cv2.putText(out, f"Student ID: {student_id}",
                (bounds['student_id'][0], bounds['student_id'][2] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS_BGR_B["student_id"], 2)

    cv2.rectangle(out, (FIXED_W - 310, 10), (FIXED_W - 10, 60), (0, 0, 0), -1)
    cv2.putText(out, f"TOTAL: {score}/{total}",
                (FIXED_W - 300, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

    for g, x_cols in enumerate([grid["ANS_X_G0"], grid["ANS_X_G1"], grid["ANS_X_G2"]]):
        for ri, row_y in enumerate(grid["ANS_Y_ROWS"]):
            q = g * 20 + ri + 1
            if str(q) not in ans_key:
                continue
            given   = answers.get(q, "-")
            correct = ans_key.get(str(q), "")
            conf    = confidences.get(q, 0.0)

            if given == "-":
                color = COLORS_BGR_B["unanswered"]
                label = f"Q{q}:- (?)"
            elif q in multi_marks:
                color = COLORS_BGR_B["multi"]
                label = f"Q{q}:Multi!"
            elif given == correct:
                color = COLORS_BGR_B["correct"]
                label = f"Q{q}:{given}"
            else:
                color = COLORS_BGR_B["wrong"]
                label = f"Q{q}:{given}>{correct}"

            # 📌 ชดเชยแกน X สำหรับข้อความ Label
            shear = shears[ri]
            cv2.putText(out, label, (x_cols[-1] + int(shear) + 8, row_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

            if 0 < conf < 0.6 and given != "-":
                cv2.putText(out, f"[{conf:.0%}]",
                            (x_cols[-1] + int(shear) + 90, row_y + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.28,
                            COLORS_BGR_B["confidence"], 1)

    # ==========================================
    # วาดภาพ DEBUG แสดงจุดไข่ปลาที่ระบบจับได้ (สีชมพู)
    # ==========================================
    if "DEBUG_LEFT" in grid:
        for i, y in enumerate(grid["DEBUG_LEFT"]):
            cv2.putText(out, f"L{i}", (20, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
            cv2.circle(out, (80, y), 5, (255, 0, 255), -1)
            
    if "DEBUG_BOTTOM" in grid:
        for i, x in enumerate(grid["DEBUG_BOTTOM"]):
            cv2.putText(out, f"B{i}", (x - 12, FIXED_H - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
            cv2.circle(out, (x, FIXED_H - 35), 5, (255, 0, 255), -1)

    return out


# ═══════════════════════════════════════════════════════════════
#  Main grade_type_b 
# ═══════════════════════════════════════════════════════════════

def grade_type_b(img: np.ndarray, ans_key: dict) -> tuple:
    # Step 1: Warp + deskew
    warped, warped_gray = _warp_paper_b(img)

    # Step 2: Enhanced preprocessing
    enhanced, denoised, adaptive_bin = _preprocess_b(warped_gray)

    # Step 3: Hybrid bubble detection
    bubbles = _detect_bubbles_hybrid(warped_gray, enhanced, adaptive_bin)

    # Step 4: OMR Timing Marks Extraction (Template Method)
    fallback_grid = {
        "SC_X_COLS":  SC_X_COLS,
        "SI_X_COLS":  SI_X_COLS,
        "DIGIT_Y":    DIGIT_Y,
        "ANS_X_G0":   ANS_X_G0,
        "ANS_X_G1":   ANS_X_G1,
        "ANS_X_G2":   ANS_X_G2,
        "ANS_Y_ROWS": ANS_Y_ROWS,
        "ANS_SHEAR":  [0] * 20,
        "SNAP":       SNAP,
        "BOUNDS":     BOUNDS_B
    }
    
    grid = _extract_grid_from_timing_marks(bubbles, fallback_grid)

    # Step 5: Decode fields using calibrated grid
    subject_code = _decode_subject_code_b(bubbles, enhanced, grid)
    student_id   = _decode_student_id_b(bubbles, enhanced, grid)
    raw_answers, confidences, multi_marks = _decode_answers_b(bubbles, enhanced, grid)

    # Step 6: Score
    total_score      = 0
    details          = {}
    q_limit          = len(ans_key)
    unanswered_count = 0

    for q_num in range(1, q_limit + 1):
        given      = raw_answers.get(q_num)
        correct    = ans_key.get(str(q_num), "").upper()
        conf       = confidences.get(q_num, 0.0)
        is_multi   = q_num in multi_marks
        is_correct = (given is not None and given == correct and not is_multi)

        if is_correct:
            total_score += 1
        if given is None:
            unanswered_count += 1

        details[str(q_num)] = {
            "given":      given or "-",
            "correct":    correct,
            "is_correct": is_correct,
            "confidence": conf,
            "multi_mark": is_multi,
        }

    # Step 7: Annotate
    annotated = _annotate_b(warped, bubbles, raw_answers, confidences,
                            multi_marks, ans_key, subject_code, student_id,
                            total_score, q_limit, enhanced, grid)

    details["__meta__"] = {
        "subject_code":     subject_code,
        "student_id":       student_id,
        "unanswered_count": unanswered_count,
        "multi_mark_count": len(multi_marks),
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


def _deskew_column(col_img: np.ndarray) -> np.ndarray:
    gray = (cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
            if len(col_img.shape) == 3 else col_img)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    h, w = col_img.shape[:2]
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=w // 4, maxLineGap=15)
    if lines is None or len(lines) < 3:
        return col_img

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 20:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        if abs(angle) < 5.0:
            angles.append(angle)

    if not angles:
        return col_img

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.15:
        return col_img

    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    deskewed = cv2.warpAffine(col_img, M, (w, h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    return deskewed


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
        warped_col      = _deskew_column(warped_col)
        x_results       = model_xmark(warped_col, conf=0.15, verbose=False)
        x_boxes         = x_results[0].boxes.xywh.cpu().numpy()
        x_confs         = x_results[0].boxes.conf.cpu().numpy()
        x_points_warped = [(box[0], box[1], float(conf))
                           for box, conf in zip(x_boxes, x_confs)]

        row_h       = maxHeight / 15
        ans_start_x = int(maxWidth * 0.22)
        offset_x    = 0
        choice_w    = (maxWidth - ans_start_x) / 5

        for i in range(15):
            q_idx += 1
            if q_idx > q_limit:
                break

            curr_y1         = i * row_h
            curr_y2         = (i + 1) * row_h
            detected_in_row = []

            for wmx, wmy, wconf in x_points_warped:
                if curr_y1 <= wmy <= curr_y2:
                    for j in range(5):
                        cx1 = ans_start_x + (j * choice_w) + offset_x
                        cx2 = ans_start_x + ((j + 1) * choice_w) + offset_x
                        if cx1 <= wmx <= cx2:
                            detected_in_row.append((labels[j], wconf))
                            p      = np.array([[[wmx, wmy]]], dtype="float32")
                            p_real = cv2.perspectiveTransform(p, M_inv)[0][0]
                            cv2.circle(annotated, (int(p_real[0]), int(p_real[1])), 8, (0, 215, 255), -1)

            if len(detected_in_row) > 1:
                detected_in_row.sort(key=lambda d: d[1], reverse=True)
                best_conf   = detected_in_row[0][1]
                second_conf = detected_in_row[1][1]
                if second_conf / max(best_conf, 1e-6) < 0.85:
                    detected_in_row = [detected_in_row[0]]

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
            given_label = (detected_in_row[0][0] if len(detected_in_row) == 1
                           else ("Multi" if detected_in_row else "-"))
            given_conf  = detected_in_row[0][1] if detected_in_row else 0.0
            is_correct  = (len(detected_in_row) == 1 and given_label == current_ans)
            if is_correct:
                total_score += 1

            details[str(q_idx)] = {
                "given":      given_label,
                "correct":    current_ans,
                "is_correct": is_correct,
                "confidence": round(given_conf, 3),
            }

            color     = (0, 150, 0) if is_correct else (0, 0, 255)
            label_txt = f"Q{q_idx}:{given_label}"
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
    try:
        db = SessionLocal()
        db_keys = db.query(AnswerKeyDB).order_by(AnswerKeyDB.created_at.desc()).all()
        keys = []
        for k in db_keys:
            keys.append({
                "id":             k.id,
                "name":           k.name,
                "form_type":      k.form_type,
                "question_count": k.question_count,
            })
        return keys
    except Exception as e:
        print(f"Error fetching answer keys from DB: {e}")
        return []
    finally:
        db.close()


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
        
    try:
        db = SessionLocal()
        db_key = AnswerKeyDB(
            id=key_id,
            name=name,
            form_type=form_type,
            answers_json=answers,
            question_count=len(ans_obj)
        )
        db.add(db_key)
        db.commit()
    except Exception as e:
        print(f"Error saving AnswerKey to DB: {e}")
    finally:
        db.close()
    return {"id": key_id, "name": name, "form_type": form_type,
            "question_count": len(ans_obj)}


@app.get("/api/answer-keys/{key_id}", tags=["Answer Keys"])
def get_answer_key(key_id: str):
    try:
        db = SessionLocal()
        k = db.query(AnswerKeyDB).filter(AnswerKeyDB.id == key_id).first()
        if not k:
            raise HTTPException(404, "Answer key not found")
        
        try:
            answers = json.loads(k.answers_json)
        except:
            answers = {}
            
        return {
            "name": k.name,
            "form_type": k.form_type,
            "answers": answers
        }
    finally:
        db.close()


@app.delete("/api/answer-keys/{key_id}", tags=["Answer Keys"])
def delete_answer_key(key_id: str):
    try:
        db = SessionLocal()
        k = db.query(AnswerKeyDB).filter(AnswerKeyDB.id == key_id).first()
        if not k:
            raise HTTPException(404, "Answer key not found in DB")
        db.delete(k)
        db.commit()
    except Exception as e:
        raise HTTPException(500, f"Error deleting answer key: {e}")
    finally:
        db.close()
        
    path = ANSWER_KEYS_DIR / f"{key_id}.json"
    if path.exists():
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
    batch_id   = str(uuid.uuid4())[:8]
    result_path = RESULTS_DIR / f"{result_id}.jpg"
    cv2.imwrite(str(result_path), annotated)
    
    pct = round(score / len(key_data["answers"]) * 100, 1)

    try:
        db = SessionLocal()
        
        db_session = GradingSessionDB(
            id=batch_id,
            answer_key_id=answer_key_id,
            answer_key_name=key_data.get("name", "Unknown"),
            form_type=key_data["form_type"],
            average_percentage=pct,
            file_count=1
        )
        db.add(db_session)
        
        db_result = GradingResultDB(
            id=result_id,
            batch_id=batch_id,
            filename=file.filename,
            answer_key_id=answer_key_id,
            score=score,
            total=len(key_data["answers"]),
            percentage=pct,
            subject_code=meta.get("subject_code"),
            student_id=meta.get("student_id"),
            details_json=json.dumps(details, ensure_ascii=False),
            image_url=f"/api/results/{result_id}.jpg"
        )
        db.add(db_result)
        db.commit()
    except Exception as e:
        print(f"Error saving single result/session to database: {e}")
    finally:
        db.close()

    return {
        "result_id":    result_id,
        "score":        score,
        "total":        len(key_data["answers"]),
        "percentage":   pct,
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

    batch_id = str(uuid.uuid4())[:8]
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
            
            res_dict = {
                "filename":     upload.filename,
                "result_id":    result_id,
                "score":        score,
                "total":        len(key_data["answers"]),
                "percentage":   round(score / len(key_data["answers"]) * 100, 1),
                "details":      details,
                "subject_code": meta.get("subject_code"),
                "student_id":   meta.get("student_id"),
                "image_url":    f"/api/results/{result_id}.jpg",
            }
            results.append(res_dict)
            
            try:
                db = SessionLocal()
                db_result = GradingResultDB(
                    id=result_id,
                    batch_id=batch_id,
                    filename=res_dict["filename"],
                    answer_key_id=answer_key_id,
                    score=res_dict["score"],
                    total=res_dict["total"],
                    percentage=res_dict["percentage"],
                    subject_code=res_dict["subject_code"],
                    student_id=res_dict["student_id"],
                    details_json=json.dumps(details, ensure_ascii=False),
                    image_url=res_dict["image_url"]
                )
                db.add(db_result)
                db.commit()
            except Exception as e:
                print(f"Error saving batch result to database: {e}")
            finally:
                db.close()
                
        except Exception as e:
            results.append({"filename": upload.filename, "error": str(e)})

    valid_results = [r for r in results if "error" not in r]
    avg_pct = sum(r["percentage"] for r in valid_results) / len(valid_results) if valid_results else 0.0

    try:
        db = SessionLocal()
        db_session = GradingSessionDB(
            id=batch_id,
            answer_key_id=answer_key_id,
            answer_key_name=key_data.get("name", "Unknown"),
            form_type=key_data["form_type"],
            average_percentage=avg_pct,
            file_count=len(valid_results)
        )
        db.add(db_session)
        db.commit()
    except Exception as e:
        print(f"Error saving batch session to database: {e}")
    finally:
        db.close()

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
    key_path = ANSWER_KEYS_DIR / f"{answer_key_id}.json"
    if not key_path.exists():
        raise HTTPException(404, "Answer key not found")
    with open(key_path) as f:
        key_data = json.load(f)

    batch_id = str(uuid.uuid4())[:8]
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
                
                result_id = str(uuid.uuid4())[:8]
                try:
                    db = SessionLocal()
                    db_result = GradingResultDB(
                        id=result_id,
                        batch_id=batch_id,
                        filename=upload.filename,
                        answer_key_id=answer_key_id,
                        score=score,
                        total=total,
                        percentage=pct,
                        subject_code=meta.get("subject_code"),
                        student_id=meta.get("student_id"),
                        details_json=json.dumps(details, ensure_ascii=False),
                        image_url=None
                    )
                    db.add(db_result)
                    db.commit()
                except Exception as e:
                    print(f"Error saving batch download result to database: {e}")
                finally:
                    db.close()
                    
            except Exception as e:
                csv_rows.append(f"{upload.filename},,,ERROR,0,0 ({e})")
        zf.writestr("summary.csv", "\n".join(csv_rows))
        
    if len(csv_rows) > 1:
        pct_sum = 0
        valid_count = 0
        for row in csv_rows[1:]:
            parts = row.split(",")
            if parts[-3] != "ERROR":
                try:
                    pct_sum += float(parts[-1])
                    valid_count += 1
                except:
                    pass
        avg_pct = pct_sum / valid_count if valid_count > 0 else 0.0
        
        try:
            db = SessionLocal()
            db_session = GradingSessionDB(
                id=batch_id,
                answer_key_id=answer_key_id,
                answer_key_name=key_data.get("name", "Unknown"),
                form_type=key_data["form_type"],
                average_percentage=avg_pct,
                file_count=valid_count
            )
            db.add(db_session)
            db.commit()
        except Exception as e:
            print(f"Error saving batch session to database: {e}")
        finally:
            db.close()

    zip_buf.seek(0)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=grading_results_{answer_key_id}.zip"},
    )


# ═══════════════════════════════════════════════════════════════
#  History endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/api/history", tags=["History"])
def list_history(search: Optional[str] = None):
    try:
        db = SessionLocal()
        query = db.query(GradingSessionDB)

        if search:
            search_term = f"%{search}%"
            query = query.outerjoin(
                GradingResultDB, GradingSessionDB.id == GradingResultDB.batch_id
            ).filter(
                or_(
                    GradingSessionDB.answer_key_name.ilike(search_term),
                    GradingResultDB.student_id.ilike(search_term),
                    GradingResultDB.subject_code.ilike(search_term),
                    GradingResultDB.filename.ilike(search_term)
                )
            ).distinct()

        sessions = query.order_by(GradingSessionDB.created_at.desc()).all()
        items = []
        for s in sessions:
            items.append({
                "id": s.id,
                "timestamp": s.created_at.isoformat() + "Z",
                "answerKeyId": s.answer_key_id,
                "answerKeyName": s.answer_key_name,
                "formType": s.form_type,
                "averagePercentage": s.average_percentage,
                "fileCount": s.file_count,
            })
        return items
    except Exception as e:
        print(f"Error fetching history from DB: {e}")
        return []
    finally:
        db.close()

@app.get("/api/history/{session_id}", tags=["History"])
def get_history_details(session_id: str):
    try:
        db = SessionLocal()
        s = db.query(GradingSessionDB).filter(GradingSessionDB.id == session_id).first()
        if not s:
            raise HTTPException(404, "History session not found")
            
        db_results = db.query(GradingResultDB).filter(GradingResultDB.batch_id == session_id).all()
        
        results_list = []
        for r in db_results:
            results_list.append({
                "filename": r.filename,
                "result_id": r.id,
                "score": r.score,
                "total": r.total,
                "percentage": r.percentage,
                "subject_code": r.subject_code,
                "student_id": r.student_id,
                "image_url": r.image_url,
                "details": json.loads(r.details_json) if r.details_json else {}
            })
            
        return {
            "id": s.id,
            "timestamp": s.created_at.isoformat() + "Z",
            "answerKeyId": s.answer_key_id,
            "answerKeyName": s.answer_key_name,
            "formType": s.form_type,
            "averagePercentage": s.average_percentage,
            "fileCount": s.file_count,
            "results": results_list
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error getting session details: {e}")
    finally:
        db.close()

@app.delete("/api/history/{session_id}", tags=["History"])
def delete_history_session(session_id: str):
    try:
        db = SessionLocal()
        s = db.query(GradingSessionDB).filter(GradingSessionDB.id == session_id).first()
        if not s:
            raise HTTPException(404, "Session not found in Database")
            
        db_results = db.query(GradingResultDB).filter(GradingResultDB.batch_id == session_id).all()
        for r in db_results:
            db.delete(r)
            
        db.delete(s)
        db.commit()
        return {"deleted": session_id}
    except Exception as e:
        raise HTTPException(500, f"Error deleting session: {e}")
    finally:
        db.close()