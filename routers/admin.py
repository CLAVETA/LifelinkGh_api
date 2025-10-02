# In routers/admin.py
from fastapi import APIRouter, Depends, HTTPException, status
from bson.objectid import ObjectId
from typing import Annotated
from db import users_collection
from utils import replace_mongo_id
from dependencies.authz import has_roles

admin_router = APIRouter()

@admin_router.get("/volunteers/pending", tags=["Admin"])
def get_pending_applications(
    user_admin: Annotated[dict, Depends(has_roles(["admin"]))]
):
    pending_users = users_collection.find({
        "role": "volunteer",
        "application_status": "pending"
    })
    return [replace_mongo_id(user) for user in pending_users]

@admin_router.put(
    "/admin/volunteers/{user_id}/approve",
    tags=["Admin"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["admin"]))] 
)
def approve_volunteer(user_id: str):
    result = users_collection.update_one(
        {"_id": ObjectId(user_id), "role": "volunteer"},
        {"$set": {"application_status": "approved"}}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Volunteer not found.")

    return {"message": "Volunteer application approved successfully."}

@admin_router.put(
    "/admin/volunteers/{user_id}/reject",
    tags=["Admin"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles(["admin"]))] 
)
def reject_volunteer(user_id: str):
    result = users_collection.update_one(
        {"_id": ObjectId(user_id), "role": "volunteer"},
        {"$set": {"application_status": "rejected"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Volunteer not found.")
    return {"message": "Volunteer application rejected."}
