"""
Announcement endpoints for the High School Management System API

Announcements are managed by signed-in teachers/admins and displayed to all
visitors as a banner while they are within their active date range.
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from ..database import announcements_collection, teachers_collection

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementInput(BaseModel):
    """Payload used to create or update an announcement"""
    message: str = Field(min_length=1, max_length=500)
    start_date: Optional[date] = None
    expiration_date: date

    @field_validator("expiration_date")
    @classmethod
    def expiration_must_be_after_start(cls, expiration_date, info):
        start_date = info.data.get("start_date")
        if start_date and expiration_date < start_date:
            raise ValueError(
                "expiration_date must be on or after start_date")
        return expiration_date


def _require_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Ensure the request is made by a signed-in teacher/admin account"""
    if not teacher_username:
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(
            status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize(announcement: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a MongoDB announcement document into a JSON-friendly dict"""
    announcement["id"] = str(announcement.pop("_id"))
    return announcement


def _to_object_id(announcement_id: str) -> ObjectId:
    try:
        return ObjectId(announcement_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=400, detail="Invalid announcement id")


@router.get("/active", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements currently visible to all site visitors"""
    today = date.today().isoformat()
    query = {
        "expiration_date": {"$gte": today},
        "$or": [{"start_date": None}, {"start_date": {"$lte": today}}]
    }

    return [_serialize(a) for a in announcements_collection.find(query)]


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get every announcement - requires teacher authentication"""
    _require_teacher(teacher_username)

    announcements = announcements_collection.find().sort("expiration_date", 1)
    return [_serialize(a) for a in announcements]


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement - requires teacher authentication"""
    teacher = _require_teacher(teacher_username)

    document = {
        "message": announcement.message,
        "start_date": announcement.start_date.isoformat() if announcement.start_date else None,
        "expiration_date": announcement.expiration_date.isoformat(),
        "created_by": teacher["username"]
    }

    try:
        result = announcements_collection.insert_one(document)
    except Exception:
        logger.exception("Failed to create announcement")
        raise HTTPException(
            status_code=500, detail="Failed to create announcement")

    document["_id"] = result.inserted_id
    return _serialize(document)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement - requires teacher authentication"""
    _require_teacher(teacher_username)
    object_id = _to_object_id(announcement_id)

    update = {
        "message": announcement.message,
        "start_date": announcement.start_date.isoformat() if announcement.start_date else None,
        "expiration_date": announcement.expiration_date.isoformat()
    }

    result = announcements_collection.find_one_and_update(
        {"_id": object_id}, {"$set": update}, return_document=ReturnDocument.AFTER)

    if not result:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return _serialize(result)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement - requires teacher authentication"""
    _require_teacher(teacher_username)
    object_id = _to_object_id(announcement_id)

    result = announcements_collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
