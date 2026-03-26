from __future__ import annotations

from uuid import uuid4

import orjson
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from chatbot.src.api.v1.endpoints.chat import (
    OrjsonResponse,
    SHARED_WIDGET_SITE_ID,
    _get_session_logger,
    _normalize_image_extension,
)
from chatbot.src.schemas.chat import FeedbackRequest, ReviewDraftRequest
from chatbot.src.tools.service_tools import generate_review_draft
from ecommerce.backend.app.core.auth import get_current_user, get_current_user_optional
from ecommerce.backend.app.router.users.models import User
from ecommerce.backend.app.uploads import CHATBOT_UPLOAD_DIR


router = APIRouter(default_response_class=OrjsonResponse)
UPLOAD_ROOT = CHATBOT_UPLOAD_DIR


@router.post("/upload-image")
async def upload_chat_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """이미지 업로드 후 챗봇 접근 가능한 URL 반환."""
    _ = current_user
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드할 수 있습니다.")

    filename = f"{uuid4().hex}{_normalize_image_extension(file.filename, content_type)}"
    target_path = UPLOAD_ROOT / filename

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="빈 이미지 파일은 업로드할 수 없습니다.")
        target_path.write_bytes(contents)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="이미지를 저장하는 중 오류가 발생했습니다.",
        ) from exc

    image_url = request.url_for("chatbot_uploads", path=filename)
    return {"url": str(image_url)}


@router.post("/auth-token")
async def chat_auth_token(
    request: Request,
    current_user: User | None = Depends(get_current_user_optional),
):
    access_token = request.cookies.get("access_token") or request.cookies.get("session_token")
    if not access_token or current_user is None:
        return {
            "authenticated": False,
            "site_id": SHARED_WIDGET_SITE_ID,
            "access_token": "",
            "user": None,
        }

    return {
        "authenticated": True,
        "site_id": SHARED_WIDGET_SITE_ID,
        "access_token": access_token,
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "name": current_user.name,
        },
    }


@router.post("/feedback")
async def submit_chat_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
):
    session_logger = _get_session_logger(current_user, request.conversation_id)

    if not session_logger.file_path.exists():
        raise HTTPException(status_code=404, detail="대화 로그를 찾을 수 없습니다.")

    finalized = session_logger.record_feedback(request.feedback_label)
    return {
        "conversation_id": finalized["conversation_id"],
        "status": finalized["status"],
        "feedback_label": finalized["feedback_label"],
        "reset_required": finalized["reset_required"],
        "state": None,
        "messages": [],
    }


@router.post("/review-draft")
async def generate_review_draft_endpoint(
    request: ReviewDraftRequest,
    current_user: User = Depends(get_current_user),
):
    """만족도 + 상품명 기반 리뷰 초안 생성."""
    _ = current_user
    try:
        result = await generate_review_draft.ainvoke(
            {
                "product_name": request.product_name,
                "satisfaction": request.satisfaction,
                "keywords": request.keywords or [],
            }
        )
        if isinstance(result, str):
            try:
                result = orjson.loads(result)
            except Exception:
                pass
        if isinstance(result, dict) and "drafts" in result:
            return result
        return {"success": True, "drafts": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
