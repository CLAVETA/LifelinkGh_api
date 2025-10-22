from fastapi import APIRouter, Form, status, Depends, HTTPException, Query
from datetime import datetime, timezone
from dependencies.authn import authenticated_user
from typing import Annotated, List,Optional
from pydantic import EmailStr, BaseModel
from db import donation_responses_collection
from db import donations_records_collection
from dependencies.authz import has_roles
from db import users_collection
from bson.objectid import ObjectId
from routers.users import create_user_in_db, UserRole
import math
import random
from geopy.geocoders import Nominatim

# GLOBAL GEOLOCATOR INITIALIZATION
geolocator = Nominatim(user_agent="BloodDonationApp_FastAPI")


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


# HELPER FUNCTION FOR GEOSPATIAL DISTANCE (Haversine Formula Approximation)
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371  # Radius of Earth in kilometers

    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance


# Blood Compatibility Mapping
def get_compatible_donor_types(requested_type: str) -> list[str]:
    """
    Determines which donor blood types are compatible for donation to the requested recipient type.
    """
    requested_type = requested_type.upper().strip().replace(" ", "")

    # Compatibility map: Recipient Type: [List of acceptable Donor Types]
    compatibility_map = {
        "O-": ["O-"],
        "O+": ["O-", "O+"],
        "A-": ["O-", "A-"],
        "A+": ["O-", "O+", "A-", "A+"],
        "B-": ["O-", "B-"],
        "B+": ["O-", "O+", "B-", "B+"],
        "AB-": ["O-", "A-", "B-", "AB-"],
        "AB+": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    }
    # Return the list of compatible types, defaulting to exact match if not found
    return compatibility_map.get(requested_type, [requested_type])


def find_nearby_donors(
    hospital_lat: float,
    hospital_lon: float,
    requested_blood_type: str,
    radius_km: float = 50.0,
):
    """Finds available donors compatible with the requested blood type within a radius."""

    # Determine all compatible donor types acceptable for the request
    compatible_donor_types = get_compatible_donor_types(requested_blood_type)

    # 1. Update the database query to use the list of compatible types
    potential_donors = users_collection.find(
        {
            "role": UserRole.DONOR.value,
            "blood_type": {"$in": compatible_donor_types},  # Use $in operator
            "availability_status": "available",
        }
    )

    matched_donors = []

    # 2. Geospatial filtering (Haversine)
    for donor in potential_donors:
        lat_value = donor.get("lat")
        lon_value = donor.get("lon")

        if lat_value is None or lon_value is None:
            continue

        try:
            donor_lat = float(lat_value)
            donor_lon = float(lon_value)
            distance_km = haversine_distance(
                hospital_lat, hospital_lon, donor_lat, donor_lon
            )

            if distance_km <= radius_km:
                matched_donors.append(
                    {
                        "id": str(donor["_id"]),
                        "full_name": donor["full_name"],
                        "phone_number": donor["phone_number"],
                        "email": donor["email"],
                        "blood_type": donor["blood_type"],  # Donor's actual type
                        "distance_km": round(distance_km, 2),
                    }
                )
        except ValueError:
            continue

    return matched_donors


def generate_4_digit_token():
    """Generates a simple 4-digit numerical token string."""
    return str(random.randint(1000, 9999))


# DONOR MATCHING (GEOLOCATION)
@donors_router.get("/donors/search", tags=["Hospitals"], status_code=status.HTTP_200_OK)
def search_available_donors(
    current_user: Annotated[dict, Depends(authenticated_user)],
    blood_type: Annotated[
        str, Query(description="The blood type to search for (e.g., O+, AB-).")
    ],
    # MODIFICATION: Replaced 'lat' and 'lon' with 'location_name'
    location_name: Annotated[
        str,
        Query(
            description="The city or regional name of the hospital/request location."
        ),
    ],
    radius: Annotated[
        float,
        Query(description="The search radius in kilometers (km).", ge=1.0, le=100.0),
    ],
):
    # AUTHORIZATION CHECK (Hospital Role Required)
    if current_user["role"] != UserRole.HOSPITAL.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only users with the 'HOSPITAL' role can search for donors.",
        )

    # 1. GEOLOCATION STEP: Convert location name to coordinates
    try:
        geo_location = geolocator.geocode(location_name)

        if not geo_location:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not determine coordinates for '{location_name}'. Please be more specific or check spelling.",
            )

        # Coordinates of the hospital/request
        hospital_lat = geo_location.latitude
        hospital_lon = geo_location.longitude

    except Exception as e:
        print(f"Hospital Geocoding Error for {location_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing location data due to external service issue. Please try again later.",
        )

    # Determine compatible donor types
    compatible_donor_types = get_compatible_donor_types(blood_type)

    # 2. DATABASE QUERY & FILTERING
    potential_donors = users_collection.find(
        {
            "role": UserRole.DONOR.value,
            "blood_type": {"$in": compatible_donor_types},
            "availability_status": "available",
        }
    )

    found_donors = []

    # 3. GEOSPATIAL FILTERING (Manually filtering via Haversine)
    for donor in potential_donors:
        try:
            # Coordinates were saved as strings in 'register_donor' endpoint, so we retrieve them as such
            lat_value = donor.get("lat")
            lon_value = donor.get("lon")

            # Skip donor if coordinates are missing
            if lat_value is None or lon_value is None:
                # Optionally update donor to be 'unavailable' if data is consistently missing
                continue

            # Convert to float for calculation (coordinates are stored as strings)
            donor_lat = float(lat_value)
            donor_lon = float(lon_value)

            # Use the calculated hospital coordinates here
            distance_km = haversine_distance(
                hospital_lat, hospital_lon, donor_lat, donor_lon
            )

            if distance_km <= radius:
                # Donor is within the search radius
                found_donors.append(
                    {
                        "id": str(donor["_id"]),
                        "full_name": donor["full_name"],
                        "phone_number": donor["phone_number"],
                        "blood_type": donor["blood_type"],
                        "distance_km": round(distance_km, 2),
                        "location_details": donor.get("location"),
                        "Availability": donor.get("availability_status", "unknown"),
                    }
                )

        except ValueError:
            # Handle cases where 'lat' or 'lon' are not valid numbers
            print(
                f"!!!! ERROR: Coordinate values are not valid numbers for donor {donor.get('_id')}"
            )
            continue
        except Exception as e:
            print(
                f"!!!! ERROR: Failed to process donor {donor.get('_id')}. Reason: {e}"
            )
            continue

    # RESPONSE
    if not found_donors:
        return {
            "message": f"No available '{blood_type}' donors found within {radius}km of '{location_name}'."
        }

    return {
        "message": f"Found {len(found_donors)} available '{blood_type}' donors within {radius}km of '{location_name}'.",
        "donors": found_donors,
    }


@donors_router.post(
    "/donors/register", tags=["Donors"], status_code=status.HTTP_201_CREATED
)
def register_donor(
    full_name: Annotated[str, Form()],
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
    phone_number: Annotated[str, Form()],
    blood_type: Annotated[str, Form()],
    date_of_birth: Annotated[str, Form()],
    location: Annotated[str, Form()],
):
    # Convert location name to coordinates
    try:
        geo_location = geolocator.geocode(location)

        if not geo_location:
            # If the service cannot find the location (e.g., misspelling or vagueness)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not determine coordinates for '{location}'. Please be more specific or check spelling.",
            )

        # Extract and convert coordinates to strings for safe MongoDB storage
        donor_lat = str(geo_location.latitude)
        donor_lon = str(geo_location.longitude)

    except Exception as e:
        # Catch network or API-related errors from geopy/Nominatim
        print(f"Geocoding Error for {location}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing location data due to external service issue. Please try again later.",
        )

    user_data = {
        "full_name": full_name,
        "email": email,
        "password": password,
        "role": UserRole.DONOR.value,
        "phone_number": phone_number,
        "blood_type": blood_type,
        "date_of_birth": date_of_birth,
        "location": location,
        "availability_status": "available",
        "lat": donor_lat,
        "lon": donor_lon,
    }

    create_user_in_db(user_data)

    return {
        "message": f"Donor '{full_name}' registered successfully and coordinates for '{location}' were saved."
    }


@donors_router.post(
    "/donors/requests/{request_id}/respond",
    tags=["Donors"],
    status_code=status.HTTP_201_CREATED,
    dependencies= [Depends(has_roles([UserRole.DONOR.value]))],  # Ensures only donors can access
)
def respond_to_request(
    request_id: str,
    current_user: Annotated[dict, Depends(authenticated_user)],
    commitment_status: Annotated[str, Form()] = "committed",
):
    # Check if the request ID is valid
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid request ID.")
    try:
        from db import (
            hospital_requests_collection,
        )  # Import inside the function if necessary, or at the top level
    except ImportError:
        # Fallback if your db structure requires top-level imports: ensure it is at the top
        pass

    request_doc = hospital_requests_collection.find_one({"_id": ObjectId(request_id)})

    if not request_doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Blood request not found or is no longer active."
        )

    # Optional: Check if the request status allows for new responses (e.g., must be 'active')
    if request_doc.get("status") != "active":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot respond to request with status: {request_doc.get('status')}.",
        )

    # Check if the donor has already responded to this request
    existing_response = donation_responses_collection.find_one(
        {"request_id": ObjectId(request_id), "donor_id": current_user["id"]}
    )
    if existing_response:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You have already responded to this request."
        )
    # Generate Token ONLY if the donor commits
    if commitment_status == "committed":
        confirmation_token = generate_4_digit_token()
    else:
        confirmation_token = None

    # Create the new response document
    response_data = {
        "request_id": ObjectId(request_id),
        "donor_id": current_user["id"],
        "status": commitment_status,
        "responded_at": datetime.now(timezone.utc),
        "confirmation_token": confirmation_token,
    }
    inserted = donation_responses_collection.insert_one(response_data)

    return {
        "message": "Your response has been recorded. The hospital will be notified.",
        "response_id": str(inserted.inserted_id),
        "confirmation_token_if_committed": confirmation_token,
    }

@donors_router.get(
    "/donors/me/profile", tags=["Donors"],dependencies=[Depends(has_roles([UserRole.DONOR.value]))]
)
def get_my_donor_profile(current_user: Annotated[dict, Depends(authenticated_user)]):
    donor_id = ObjectId(current_user["id"])
    donor_profile = users_collection.find_one({"_id": donor_id}, {"password": 0})  # Exclude password

    if not donor_profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donor profile not found.")

    # Convert ObjectId to string for JSON serialization
    donor_profile["id"] = str(donor_profile["_id"])
    del donor_profile["_id"]

    return donor_profile


@donors_router.get(
    "/donors/me/history", tags=["Donors"], 
    response_model=List[DonationRecord],
    dependencies=[Depends(has_roles([UserRole.DONOR.value]))]
)
def get_my_donation_history(current_user: Annotated[dict, Depends(authenticated_user)]):
    # Fetch donation records for the current donor
    donation_records = donations_records_collection.find(
        {"donor_id": current_user["id"], "status": "Completed"}
    ).sort("donation_date", -1)

    history = []
    for record in donation_records:
        history.append(
            {
                "id": str(record["_id"]),
                "donation_date": record["donation_date"],
                "location": record["hospital_name"],
                "recipient_info": record.get("recipient_info", "N/A"),
                "status": record["status"],
            }
        )
    return history

# update donor profile
@donors_router.put(
    "/donors/me/profile",
    tags=["Donors"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles([UserRole.DONOR.value]))] # Ensures only donors can access
)
def update_donor_profile(
    current_user: Annotated[dict, Depends(authenticated_user)],
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    availability_status: Optional[str] = Form(None) # e.g., "available", "unavailable"
):
    """
    Allows an authenticated donor to update their own profile information.
    All fields are optional.
    """
    update_data = {}
    donor_id = ObjectId(current_user["id"])

    # Add provided fields to the update dictionary
    if full_name is not None:
        update_data["full_name"] = full_name
    if phone_number is not None:
        update_data["phone_number"] = phone_number
    if availability_status is not None:
        update_data["availability_status"] = availability_status

    # If location is updated, coordinates must be updated as well @23
    if location is not None:
        update_data["location"] = location
        try:
            geo_location = geolocator.geocode(location)
            if geo_location:
                update_data["lat"] = str(geo_location.latitude)
                update_data["lon"] = str(geo_location.longitude)
            else:
                # If new location can't be found, we can choose to fail or just update the name
                # Here, we will just update the name and nullify coordinates to be safe
                update_data["lat"] = None
                update_data["lon"] = None
        except Exception as e:
            print(f"Geocoding Error on profile update for {location}: {e}")
            # Do not block update if geocoding fails, just log it
            pass

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update fields provided."
        )

    # Perform the update in the database
    result = users_collection.update_one(
        {"_id": donor_id},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donor profile not found.")

    return {"message": "Donor profile updated successfully."}


# delete donor profile
@donors_router.delete(
    "/donors/me",
    tags=["Donors"],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(has_roles([UserRole.DONOR.value]))]
)
def delete_donor_profile(
    current_user: Annotated[dict, Depends(authenticated_user)]
):
    """
    Allows an authenticated donor to permanently delete their own account.
    """
    donor_id = ObjectId(current_user["id"])

    # Delete the user document
    result = users_collection.delete_one({"_id": donor_id})

    if result.deleted_count == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Donor profile not found to delete."
        )

    # Optional: Clean up related records (e.g., anonymize donation history)
    # For now, we only delete the user profile as a primary action.

    return {"message": "Donor account deleted successfully."}