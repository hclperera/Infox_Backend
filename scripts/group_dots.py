"""Group arbitrary saved YOLO labels or detection JSON, individually or in batches."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grouping import GridConfig, group_dots_detailed
from services.translation import translate_detailed


def is_detection_file(path):
    """Recognize content, so metadata and previous translations are not labels."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() == '.json':
            value = json.loads(raw)
            return isinstance(value, dict) and 'yolo_outputs' in value
        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            return True  # Report an empty labels file as a failed page.
        first = [float(v) for v in lines[0].split()]
        return len(first) in (5,6) and first[0].is_integer()
    except (ValueError, OSError):
        return False


def process_file(path, output, args):
    settings = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        vision = json.loads(raw)
        rows = vision["yolo_outputs"]
        width = args.width if args.width is not None else vision["img_width"]
        height = args.height if args.height is not None else vision["img_height"]
        settings.setdefault("front_class_id", vision.get("front_class_id", 2))
    else:
        rows = [[float(v) for v in line.split()] for line in raw.splitlines() if line.strip()]
        width, height = args.width, args.height
        if width is None or height is None:
            if args.image:
                image = args.image
            else:
                images = [p for p in path.parent.iterdir()
                          if p.stem == path.stem and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")]
                if len(images) != 1:
                    raise ValueError("Provide --width/--height or one matching image alongside the labels")
                image = images[0]
            from PIL import Image
            with Image.open(image) as picture:
                width, height = picture.size
    if args.front_class_id is not None:
        settings["front_class_id"] = args.front_class_id
    if args.recover_classifications:
        settings['recover_back_dots'] = True
    if args.refine_segments:
        settings['refine_segments'] = True
        settings['refine_lines'] = True
    if args.review:
        settings["min_accepted_fraction"] = .80
        settings.setdefault("refine_lines", True)
    result = group_dots_detailed(rows, width, height, config=GridConfig(**settings))
    if not result["codes"]:
        raise ValueError("No usable front dots")
    translation = translate_detailed(result["codes"])
    review_only=bool(args.review or settings.get('refine_segments') or result.get('requires_review'))
    result["review_only"] = review_only
    translation["review_only"] = review_only
    files = [output / name for name in ("grouping.json", "codes.txt", "translation.json", "translated.txt")]
    inputs = {path.resolve()}
    if args.config:
        inputs.add(args.config.resolve())
    if args.image:
        inputs.add(args.image.resolve())
    if any(p.resolve() in inputs for p in files):
        raise ValueError("Output filenames must not overwrite input files")
    output.mkdir(parents=True, exist_ok=True)
    files[0].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    files[1].write_text(" ".join("NEWLINE" if c == "\n" else c for c in result["codes"])+"\n", encoding="utf-8")
    files[2].write_text(json.dumps(translation, ensure_ascii=False, indent=2), encoding="utf-8")
    files[3].write_text(translation["text"], encoding="utf-8")
    return {"input": str(path), "output": str(output.resolve()), "result": "review_only" if review_only else "complete",
            "cells": len(result["cells"]), "lines": result["codes"].count("\n"),
            "geometric_coverage": result["grid"]["accepted_fraction"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detections", type=Path, help="A labels/JSON file or a folder of files")
    parser.add_argument("--image", type=Path, help="Corresponding image for a single YOLO labels file")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--front-class-id", type=int)
    parser.add_argument("--config", type=Path, help="JSON GridConfig with optional measured calibration")
    parser.add_argument("--review", action="store_true", help="Export provisional text at 80% coverage for human review")
    parser.add_argument("--recover-classifications", action="store_true", help="Try auditable recovery of back-labelled dots on front sites")
    parser.add_argument("--refine-segments", action="store_true", help="Try guarded bends within lines; outputs require review")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    batch = args.detections.is_dir()
    if batch and (args.image or args.width is not None or args.height is not None):
        parser.error("Batch labels use each matching image's dimensions; omit --image/--width/--height")
    paths = sorted(p for p in args.detections.iterdir()
                   if p.is_file() and p.suffix.lower() in (".txt", ".json") and is_detection_file(p)) if batch else [args.detections]
    if not paths:
        parser.error("No detection files found")
    if batch and len({p.stem.casefold() for p in paths}) != len(paths):
        parser.error("Duplicate input stems would overwrite outputs; use separate output folders")
    if args.review:
        print("PROVISIONAL REVIEW OUTPUT: lower geometric threshold; text may be incorrect.")
    summary = []
    for path in paths:
        output = args.output / path.stem if batch else args.output
        try:
            record = process_file(path, output, args)
            print(f"{path.stem}: {record['lines']} lines, {record['cells']} cells, geometric coverage {record['geometric_coverage']:.1%}.")
        except (ValueError, TypeError, KeyError, OSError) as error:
            record = {"input": str(path), "result": "error", "error": str(error)}
            print(f"{path.stem}: grouping failed: {error}", file=sys.stderr)
        summary.append(record)
    if batch:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Geometric coverage is not translation accuracy. Review warnings in each JSON output.")
    return int(any(record["result"] == "error" for record in summary))


if __name__ == "__main__":
    raise SystemExit(main())
