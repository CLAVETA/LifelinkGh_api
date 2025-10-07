import re
from fastapi import APIRouter, Depends, HTTPException, status, Form
from typing import Annotated, Optional
from datetime import datetime, timezone
from routers.users import UserRole
import bcrypt
from pydantic import EmailStr
from bson.objectid import ObjectId
from pydantic import BaseModel
from db import hospital_requests_collection
from db import donation_responses_collection
from db import donations_records_collection
from db import users_collection
from utils import replace_mongo_id
from dependencies.authn import authenticated_user
from dependencies.authz import has_roles

class DonationConfirmation(BaseModel):
    donation_date: str
    recipient_info: str 

hospital_requests_router = APIRouter()

@hospital_requests_router.post(
    "/hospitals/register", 
    tags=["Hospitals"], 
    status_code=status.HTTP_201_CREATED
)
def register_hospital(
    hospital_name: Annotated[str, Form()], 
    email: Annotated[EmailStr, Form()],    
    password: Annotated[str, Form(min_length=8)], 
):
    # Check if a user with the given email already exists
    if users_collection.count_documents({"email": email}) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )

    # Hash the hospital's password securely using bcrypt
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    # Create the user document for the database
    user_data = {
        "full_name": hospital_name, 
        "email": email,
        "password": hashed_password,
        "role": UserRole.HOSPITAL.value, 
        "created_at": datetime.now(timezone.utc)
    }

    # Save the new hospital user into the database
    users_collection.insert_one(user_data)

    return {"message": f"Hospital '{hospital_name}' registered successfully."}

# Create a new request (Hospital role only) ---
@hospital_requests_router.post(
    "/requests",
    tags=["Hospitals"],
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

    inserted = hospital_requests_collection.insert_one(request_data)
    return {
        "message": "Blood request created successfully.",
        "id": str(inserted.inserted_id),
    }

# Get all requests
@hospital_requests_router.get("/requests/all", tags=["Hospitals"])
def get_all_requests(
    search: str | None = None,
    blood_type: str | None = None,
    status: str | None = None,
    quantity_min: int | None = None,
    quantity_max: int | None = None,
    limit: int = 10,
    skip: int = 0,
):
    print(f"Received blood_type parameter: '{blood_type}'")
    query_filter = {}
    if search:
        query_filter["$or"] = [
            {"blood_type": {"$regex": search, "$options": "i"}},
            {"status": {"$regex": search, "$options": "i"}},
        ]
    if blood_type:
        escaped_blood_type = re.escape(blood_type)
        query_filter["blood_type"] = {
            "$regex": f"^{escaped_blood_type}$",
            "$options": "i",
        }
    if status:
        query_filter["status"] = {"$regex": f"^{status}$", "$options": "i"}
    quantity_filter = {}
    if quantity_min is not None:
        quantity_filter["$gte"] = quantity_min
    if quantity_max is not None:
        quantity_filter["$lte"] = quantity_max
    if quantity_filter:
        query_filter["quantity"] = quantity_filter
    print(f"Constructed MongoDB query filter: {query_filter}")
    requests = list(
        hospital_requests_collection.find(
            filter=query_filter,
            limit=int(limit),
            skip=int(skip),
        )
    )
    return {"data": list(map(replace_mongo_id, requests))}


# Get specific request by ID
@hospital_requests_router.get("/requests/{request_id}", tags=["Hospitals"])
def get_request_by_id(request_id):
    # check if reuest id is valid
    if not ObjectId.is_valid(request_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid request ID."
        )
    request_doc = hospital_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request_doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return replace_mongo_id(request_doc)

# Update a request
@hospital_requests_router.put(
    "/requests/{request_id}",
    tags=["Hospitals"],
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

    result = hospital_requests_collection.update_one(
        {"_id": ObjectId(request_id)}, {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")

    return {"message": "Request updated successfully."}


#Delete a request 
@hospital_requests_router.delete(
    "/requests/{request_id}",
    tags=["Hospitals"],
    dependencies=[Depends(has_roles(["hospital", "admin"]))],
)
def delete_request(request_id: str):
    result = hospital_requests_collection.delete_one({"_id": ObjectId(request_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    return {"message": "Request deleted successfully."}

@hospital_requests_router.post(
    "/responses/{response_id}/confirm-donation",
    tags=["Hospitals"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_roles(["hospital"]))],
)
def confirm_donation(
    response_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
    donation_date: Annotated[str, Form()],
    recipient_info: Annotated[str, Form()] = "Patient Matched"
):
    if not ObjectId.is_valid(response_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid response ID.")

    # Find the original donation response from the donor
    response = donation_responses_collection.find_one({"_id": ObjectId(response_id)})
    if not response:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donation response not found.")

    donor_id = response["donor_id"]

    # Check to prevent creating duplicate donation records
    existing_record = donations_records_collection.find_one({
        "original_response_id": ObjectId(response_id)
    })
    if existing_record:
        raise HTTPException(status.HTTP_409_CONFLICT, "A donation record for this response already exists.")

    # Create the new donation record document
    donation_record_data = {
        "donor_id": donor_id,
        "hospital_id": current_user["id"],
        "hospital_name": current_user.get("hospital_name") or current_user.get("full_name"), 
        "donation_date": donation_date,
        "recipient_info": recipient_info,
        "status": "Completed",
        "original_response_id": ObjectId(response_id) 
    }

    # 4. Insert the record into the database
    donations_records_collection.insert_one(donation_record_data)
    
    #  Update the original response status
    donation_responses_collection.update_one(
        {"_id": ObjectId(response_id)},
        {"$set": {"status": "completed"}}
    )

    return {"message": "Donation successfully recorded and added to donor's history."}

@hospital_requests_router.get(
    "/requests/{request_id}/responses",
    tags=["Hospitals"],
    dependencies=[Depends(has_roles(["hospital"]))],
)
def get_responses_for_request(request_id: str):
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid request ID.")

    responses = donation_responses_collection.find({"request_id": ObjectId(request_id)})
    
    return [replace_mongo_id(r) for r in responses]
