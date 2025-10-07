from fastapi import APIRouter, Form, status, Depends, HTTPException
from datetime import datetime, timezone
from dependencies.authn import authenticated_user
from typing import Annotated, List
from pydantic import EmailStr, BaseModel
from db import donation_responses_collection
from db import donations_records_collection
from bson.objectid import ObjectId
from routers.users import create_user_in_db, UserRole 

class DonationResponse(BaseModel):
    id: str
    request_id: str
    donor_id: str
    status: str
    responded_at: str

class DonationRecord(BaseModel):
    id: str
    donation_date: str
    location: str 
    recipient_info: str 
    status: str

donors_router = APIRouter()

@donors_router.post("/donors/register", tags=["Donors"], status_code=status.HTTP_201_CREATED)
def register_donor(
    full_name: Annotated[str, Form()],
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
    phone_number: Annotated[str, Form()],
    blood_type: Annotated[str, Form()],
    date_of_birth: Annotated[str, Form()],
    location: Annotated[str, Form()],
):
    user_data = {
        "full_name": full_name,
        "email": email,
        "password": password,
        "role": UserRole.DONOR.value,
        "phone_number": phone_number,
        "blood_type": blood_type,
        "date_of_birth": date_of_birth,
        "location": location,
        "availability_status": "available" 
    }
    # create the user
    create_user_in_db(user_data)

    return {"message": f"Donor '{full_name}' registered successfully."}


@donors_router.post(
    "/donors/requests/{request_id}/respond",
    tags=["Donors"],
    status_code=status.HTTP_201_CREATED
)
def respond_to_request(
    request_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
    commitment_status: Annotated[str, Form()] = "committed" 
):
    # Check if the request ID is valid
    if not ObjectId.is_valid(request_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid request ID."
        )

    # Check if the donor has already responded to this request
    existing_response = donation_responses_collection.find_one({
        "request_id": ObjectId(request_id),
        "donor_id": current_user["id"]
    })
    if existing_response:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You have already responded to this request."
        )

    # Create the new response document
    response_data = {
        "request_id": ObjectId(request_id),
        "donor_id": current_user["id"],
        "status": commitment_status,
        "responded_at": datetime.now(timezone.utc)
    }
    inserted = donation_responses_collection.insert_one(response_data)
    
    return {
        "message": "Your response has been recorded. The hospital will be notified.",
        "response_id": str(inserted.inserted_id)
    }

@donors_router.get(
    "/donors/me/history",
    tags=["Donors"],
    response_model=List[DonationRecord]
)
def get_my_donation_history(current_user: Annotated[dict, Depends(authenticated_user)]):
    # Fetch donation records for the current donor
    donation_records = donations_records_collection.find({
        "donor_id": current_user["id"],
        "status": "Completed"
    }).sort("donation_date", -1)

    history = []
    for record in donation_records:
        history.append({
            "id": str(record["_id"]),
            "donation_date": record["donation_date"],
            "location": record["hospital_name"],
            "recipient_info": record.get("recipient_info", "N/A"),
            "status": record["status"]
        })
    return history
