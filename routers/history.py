"""Read-only, authenticated scan history. Local saves never delete server scans."""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db_connection
from services.sessions import require_user

router = APIRouter()


@router.get('/scans')
def list_scans(before: int | None = Query(None, gt=0),
               limit: int = Query(20, ge=1, le=100),
               user=Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = ('SELECT scan_id, status, translated_text, created_at FROM scans '
               'WHERE user_id = %s')
        params = [user['user_id']]
        if before is not None:
            sql += ' AND scan_id < %s'
            params.append(before)
        sql += ' ORDER BY scan_id DESC LIMIT %s'
        params.append(limit + 1)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {'scans': rows, 'next_before': rows[-1]['scan_id'] if more else None}
    except Exception as error:
        raise HTTPException(500, 'Unable to load scan history.') from error
    finally:
        cursor.close()
        conn.close()
