from fastapi import APIRouter, Depends, HTTPException, status, Form, Query
from typing import Annotated, Optional
from bson.objectid import ObjectId
from db import requests_collection
from utils import replace_mongo_id
from dependencies.authn import authenticated_user
from dependencies.authz import has_roles

requests_router = APIRouter()

# --- 1. Create a new request (Hospital role only) ---
@requests_router.post(
    "/requests",
    tags=["Requests"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_roles(["hospital"]))],
)
def create_request(
    current_user: Annotated[dict, Depends(authenticated_user)],
    blood_type: Annotated[str, Form()],
    quantity: Annotated[int, Form()],
    patient_condition: Annotated[str, Form()],
):
    request_data = {
        "blood_type": blood_type,
        "quantity": quantity,
        "patient_condition": patient_condition,
        "hospital_id": current_user["id"],
        "status": "active",
    }

    inserted = requests_collection.insert_one(request_data)
    return {
        "message": "Blood request created successfully.",
        "id": str(inserted.inserted_id),
    }

# --- 2. Get all requests (no filters) ---
@requests_router.get("/requests/all", tags=["Requests"])
def get_all_requests():
    cursor = requests_collection.find({})
    return [replace_mongo_id(r) for r in cursor]

# --- 3. Get all requests by blood group ---
@requests_router.get("/requests/by-blood-group", tags=["Requests"])
def get_requests_by_blood_group(
    blood_type: str = Query(..., description="Blood group to filter requests by")
):
    cursor = requests_collection.find({"blood_type": blood_type})
    results = [replace_mongo_id(r) for r in cursor]
    if not results:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No requests found for blood type {blood_type}",
        )
    return results

# --- 4. Get specific request by ID ---
@requests_router.get("/requests/{request_id}", tags=["Requests"])
def get_request_by_id(request_id: str):
    request_doc = requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request_doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return replace_mongo_id(request_doc)

# --- 5. Update a request (Hospital only) ---
@requests_router.put(
    "/requests/{request_id}",
    tags=["Requests"],
    dependencies=[Depends(has_roles(["hospital"]))],
)
def update_request(
    request_id: str,
    blood_type_update: Optional[str] = Form(None),
    status_update: Optional[str] = Form(None),
    quantity_update: Optional[int] = Form(None),
    patient_condition_update: Optional[str] = Form(None),
):
    update_data = {}
    if blood_type_update:
        update_data["blood_type"] = blood_type_update
    if status_update:
        update_data["status"] = status_update
    if quantity_update is not None:
        update_data["quantity"] = quantity_update
    if patient_condition_update:
        update_data["patient_condition"] = patient_condition_update

    if not update_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No update fields provided.")

    result = requests_collection.update_one(
        {"_id": ObjectId(request_id)}, {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")

    return {"message": "Request updated successfully."}

# --- 6. Delete a request (Hospital or Admin only) ---
@requests_router.delete(
    "/requests/{request_id}",
    tags=["Requests"],
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def delete_request(request_id: str):
    result = requests_collection.delete_one({"_id": ObjectId(request_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return {"message": "Request deleted successfully."}
