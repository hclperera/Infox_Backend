import os
import uuid
import shutil
import logging
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from database import get_db_connection

# ---------------------------------------------------------------------------
# Pipeline service imports.
# We import lazily inside the endpoint so that a missing service module
# (i.e., not yet implemented by teammates) doesn't crash the whole server
# on startup.
# ---------------------------------------------------------------------------
from services.segmentation import run_vision_stages
# from services.grouping    import group_dots
# from services.translation import translate_codes

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_user_exists(user_id: int) -> None:
    """
    Verify that the given user_id exists in the users table.
    Raises HTTP 404 if the user is not found.
    Raises HTTP 500 on any database error.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {user_id} does not exist.",
            )
    except HTTPException:
        raise  # Re-raise intentional HTTP errors
    except Exception as e:
        logger.error("DB error while verifying user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while validating user.",
        )
    finally:
        cursor.close()
        conn.close()


def _save_uploaded_image(file: UploadFile, user_id: int) -> str:
    """
    Persist the uploaded image to:
        uploads/images/<user_id>/<YYYY-MM-DD>/<uuid>.jpg

    Returns the full path to the saved file.
    Raises HTTP 500 if saving fails.
    """
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    filename = f"{uuid.uuid4().hex}.jpg"
    dir_path = os.path.join("uploads", "images", str(user_id), date_str)

    try:
        os.makedirs(dir_path, exist_ok=True)
        image_path = os.path.join(dir_path, filename)

        # Reset stream position before reading (important for UploadFile)
        file.file.seek(0)
        with open(image_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)

        logger.info("Saved uploaded image to: %s", image_path)
        return image_path

    except Exception as e:
        logger.error("Failed to save image for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the uploaded image to disk.",
        )


def _insert_scan_record(user_id: int, image_path: str) -> int:
    """
    Insert a new row into the scans table with status='pending'.
    Returns the newly created scan_id.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scans (user_id, image_path, status) VALUES (%s, %s, 'pending')",
            (user_id, image_path),
        )
        conn.commit()
        scan_id = cursor.lastrowid
        logger.info("Created scan record id=%s for user %s", scan_id, user_id)
        return scan_id
    except Exception as e:
        logger.error("Failed to insert scan record for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while creating scan record.",
        )
    finally:
        cursor.close()
        conn.close()


def _update_scan_done(scan_id: int, translated_text: str) -> None:
    """Mark a scan as 'done' and store the translated text."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE scans SET status = 'done', translated_text = %s WHERE scan_id = %s",
            (translated_text, scan_id),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to mark scan %s as done: %s", scan_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while saving scan result.",
        )
    finally:
        cursor.close()
        conn.close()


def _update_scan_error(scan_id: int, error_message: str) -> None:
    """
    Mark a scan as 'error' and record the failure reason.
    This is a best-effort call — any DB error here is only logged,
    never raised, so it doesn't mask the original pipeline exception.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scans SET status = 'error', error_message = %s WHERE scan_id = %s",
            (error_message[:500], scan_id),  # Column is VARCHAR(500)
        )
        conn.commit()
    except Exception as db_err:
        logger.error("Could not record error state for scan %s: %s", scan_id, db_err)
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@router.post("/scan", status_code=status.HTTP_201_CREATED)
async def scan_braille_image(
    user_id: int = Form(..., description="ID of the authenticated app user"),
    file: UploadFile = File(..., description="JPEG image of the braille page"),
):
    """
    POST /scan
    ----------
    Orchestrates the full braille-to-text pipeline:

      1. Validate user exists in DB.
      2. Save the uploaded image permanently to disk.
      3. Insert a 'pending' scan record in the DB.
      4. Run the ML pipeline (Person 2 → Person 3 → Person 4).
      5. Update the scan record with the translated text and status 'done'.
      6. Return the result to the Flutter app.

    On any ML pipeline failure the scan record is marked 'error' and
    HTTP 500 is returned.
    """

    # ------------------------------------------------------------------
    # Step 1: Validate user_id
    # ------------------------------------------------------------------
    _ensure_user_exists(user_id)

    # ------------------------------------------------------------------
    # Step 2: Persist the uploaded file to disk
    # ------------------------------------------------------------------
    image_path = _save_uploaded_image(file, user_id)

    # ------------------------------------------------------------------
    # Step 3: Create a 'pending' database record
    # ------------------------------------------------------------------
    scan_id = _insert_scan_record(user_id, image_path)

    # ------------------------------------------------------------------
    # Step 4: Run the ML pipeline
    # ------------------------------------------------------------------
    try:
        logger.info("[Scan %s] Starting ML pipeline on %s", scan_id, image_path)

        # --- Person 2: Vision stages (page crop + dot detection) ---
        from services.segmentation import run_vision_stages
        vision_result = run_vision_stages(image_path)

        # --- Person 3: Spatial grouping of dots into braille codes ---
        from services.grouping import group_dots
        braille_codes = group_dots(
            vision_result["yolo_outputs"],
            vision_result["img_width"],
            vision_result["img_height"],
        )

        # --- Person 4: Translate braille codes to Sinhala text ---
        from services.translation import translate_codes
        sinhala_text = translate_codes(braille_codes)

        logger.info("[Scan %s] Pipeline complete. Output length: %s chars", scan_id, len(sinhala_text))

    except HTTPException:
        raise  # Already a well-formed HTTP error; let FastAPI handle it
    except Exception as pipeline_err:
        error_msg = str(pipeline_err)
        logger.error("[Scan %s] ML pipeline failed: %s", scan_id, error_msg, exc_info=True)
        # Best-effort: record the failure in the DB
        _update_scan_error(scan_id, error_msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ML pipeline failed: {error_msg}",
        )

    # ------------------------------------------------------------------
    # Step 5: Persist the result and mark scan as 'done'
    # ------------------------------------------------------------------
    _update_scan_done(scan_id, sinhala_text)

    # ------------------------------------------------------------------
    # Step 6: Return the response to the Flutter app
    # ------------------------------------------------------------------
    return {
        "success": True,
        "scan_id": scan_id,
        "status": "done",
        "translated_text": sinhala_text,
    }
