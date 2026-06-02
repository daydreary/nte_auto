#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _build_mask(
    rgb: np.ndarray, low: tuple[int, int, int], high: tuple[int, int, int]
) -> np.ndarray:
    """
    Build a binary mask from RGB range.
    """
    low_arr = np.array(low, dtype=np.uint8)
    high_arr = np.array(high, dtype=np.uint8)
    in_range = (rgb >= low_arr) & (rgb <= high_arr)
    return np.all(in_range, axis=2)


def _connected_components(mask: np.ndarray) -> list[dict[str, Any]]:
    """
    Find all 8-connected components in a 2D bool mask.
    """
    if mask.ndim != 2:
        raise ValueError("mask must be a 2D array")

    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    offsets = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    components: list[dict[str, Any]] = []

    ys, xs = np.where(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if visited[y0, x0]:
            continue
        q: deque[tuple[int, int]] = deque([(y0, x0)])
        visited[y0, x0] = True
        area = 0
        min_x = max_x = x0
        min_y = max_y = y0
        sum_x = 0
        sum_y = 0

        while q:
            y, x = q.popleft()
            area += 1
            sum_x += x
            sum_y += y
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

            for dy, dx in offsets:
                ny = y + dy
                nx = x + dx
                if ny < 0 or ny >= h or nx < 0 or nx >= w:
                    continue
                if visited[ny, nx] or not mask[ny, nx]:
                    continue
                visited[ny, nx] = True
                q.append((ny, nx))

        components.append(
            {
                "area": int(area),
                "bbox": {
                    "x": int(min_x),
                    "y": int(min_y),
                    "w": int(max_x - min_x + 1),
                    "h": int(max_y - min_y + 1),
                },
                "center": {
                    "x": float(sum_x / area),
                    "y": float(sum_y / area),
                },
            }
        )

    components.sort(key=lambda item: item["area"], reverse=True)
    return components


def _merge_bboxes(bboxes: list[dict[str, int]]) -> dict[str, int]:
    min_x = min(box["x"] for box in bboxes)
    min_y = min(box["y"] for box in bboxes)
    max_x = max(box["x"] + box["w"] for box in bboxes)
    max_y = max(box["y"] + box["h"] for box in bboxes)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def _extract_green_region(mask: np.ndarray) -> dict[str, Any] | None:
    """
    Extract a logical green region which may be split by cursor.
    """
    components = _connected_components(mask)
    if not components:
        return None

    dominant = components[0]
    dominant_center_y = dominant["center"]["y"]
    dominant_h = dominant["bbox"]["h"]
    min_area = max(3, int(dominant["area"] * 0.25))
    max_center_y_gap = max(4.0, float(dominant_h))

    selected = [
        comp
        for comp in components
        if comp["area"] >= min_area
        and abs(comp["center"]["y"] - dominant_center_y) <= max_center_y_gap
    ]
    if not selected:
        selected = [dominant]

    selected.sort(key=lambda item: item["bbox"]["x"])
    merged_bbox = _merge_bboxes([item["bbox"] for item in selected])
    total_area = sum(item["area"] for item in selected)
    weighted_center_x = sum(item["center"]["x"] * item["area"] for item in selected) / total_area
    weighted_center_y = sum(item["center"]["y"] * item["area"] for item in selected) / total_area

    return {
        "area": int(total_area),
        "bbox": merged_bbox,
        "center": {"x": float(weighted_center_x), "y": float(weighted_center_y)},
        "segments": selected,
    }


def _bbox_distance(rect1: dict[str, int], rect2: dict[str, int]) -> tuple[int, int]:
    def axis_gap(a_start: int, a_len: int, b_start: int, b_len: int) -> int:
        a_end = a_start + a_len
        b_end = b_start + b_len
        if a_end < b_start:
            return b_start - a_end
        if b_end < a_start:
            return a_start - b_end
        return 0

    gap_x = axis_gap(rect1["x"], rect1["w"], rect2["x"], rect2["w"])
    gap_y = axis_gap(rect1["y"], rect1["h"], rect2["y"], rect2["h"])
    return gap_x, gap_y


def _extract_yellow_cursor(
    yellow_mask: np.ndarray, green_bbox: dict[str, int] | None
) -> dict[str, Any] | None:
    components = _connected_components(yellow_mask)
    if not components:
        return None

    # Step1: remove obvious noise components (single-pixel or wide horizontal lines).
    shape_candidates = []
    for comp in components:
        bbox = comp["bbox"]
        w = bbox["w"]
        h = bbox["h"]
        if comp["area"] < 3:
            continue
        if h < 2:
            continue
        if w > max(6, h * 2):
            continue
        shape_candidates.append(comp)

    if not shape_candidates:
        return None

    if green_bbox is None:
        return shape_candidates[0]

    # Step2: prefer candidates close to the green bar region.
    max_gap_x = max(12, int(green_bbox["w"] * 0.25))
    max_gap_y = max(8, int(green_bbox["h"] * 4))
    nearby = []
    for comp in shape_candidates:
        gap_x, gap_y = _bbox_distance(comp["bbox"], green_bbox)
        if gap_x <= max_gap_x and gap_y <= max_gap_y:
            score = comp["area"] - (gap_x + gap_y) * 0.2
            nearby.append((score, comp))

    if nearby:
        nearby.sort(key=lambda item: item[0], reverse=True)
        return nearby[0][1]

    _, img_w = yellow_mask.shape
    edge_margin = max(12, int(img_w * 0.03))

    def _is_edge_candidate(comp: dict[str, Any]) -> bool:
        x = comp["bbox"]["x"]
        w = comp["bbox"]["w"]
        return x <= edge_margin or (x + w) >= (img_w - edge_margin)

    non_edge = [comp for comp in shape_candidates if not _is_edge_candidate(comp)]
    if non_edge:
        return non_edge[0]

    top = shape_candidates[0]
    gap_x, _ = _bbox_distance(top["bbox"], green_bbox)
    if _is_edge_candidate(top) and gap_x > max_gap_x:
        return None

    # Fallback: keep the strongest vertical yellow candidate even when it is far
    # from the green region. In real scenes, cursor and green bar may be distant.
    return top


def _rect_intersection(
    rect1: dict[str, int], rect2: dict[str, int]
) -> dict[str, int | bool]:
    x1 = max(rect1["x"], rect2["x"])
    y1 = max(rect1["y"], rect2["y"])
    x2 = min(rect1["x"] + rect1["w"], rect2["x"] + rect2["w"])
    y2 = min(rect1["y"] + rect1["h"], rect2["y"] + rect2["h"])
    w = max(0, x2 - x1)
    h = max(0, y2 - y1)
    return {"intersects": w > 0 and h > 0, "x": x1, "y": y1, "w": w, "h": h}


def detect_green_and_yellow(image_path: str | Path) -> dict[str, Any]:
    """
    Detect green region and yellow cursor in image.

    Args:
        image_path: Path of source image.

    Returns:
        Minimal JSON-style dict with x/y/w/h and intersects only.
    """
    img = Image.open(image_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)

    # Thresholds tuned for bright UI greens and yellows in screenshot bars.
    green_mask = _build_mask(rgb, low=(50, 160, 60), high=(130, 255, 170))
    # Yellow cursor has anti-aliased edges, so keep blue channel upper bound looser.
    yellow_mask = _build_mask(rgb, low=(190, 150, 70), high=(255, 255, 190))

    green = _extract_green_region(green_mask)
    yellow = _extract_yellow_cursor(yellow_mask, green["bbox"] if green else None)

    green_bbox = green["bbox"] if green else None
    yellow_bbox = yellow["bbox"] if yellow else None
    intersects = False
    if green_bbox and yellow_bbox:
        intersects = bool(_rect_intersection(green_bbox, yellow_bbox)["intersects"])

    return {
        "green_region": green_bbox,
        "yellow_cursor": yellow_bbox,
        "intersects": intersects,
    }


def detect_green_and_yellow_json(image_path: str | Path) -> str:
    """
    Helper method for direct JSON string output.
    """
    return json.dumps(detect_green_and_yellow(image_path), ensure_ascii=False)

