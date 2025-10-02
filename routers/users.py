# In routers/auth.py

from enum import Enum
from fastapi import APIRouter, Form, HTTPException, status
from typing import Annotated
from pydantic import EmailStr
from db import users_collection  
import bcrypt
import jwt
import os
from datetime import datetime, timezone, timedelta

# --- 1. Define User Roles for LIFELINK GH ---
# This enum provides clear, consistent roles across the application as per the guide.
class UserRole(str, Enum):
    DONOR = "donor"
    HOSPITAL = "hospital"
    VOLUNTEER = "volunteer"
    ADMIN = "admin"

# Create the authentication router
users_router = APIRouter()

# --- 2. User Registration Endpoint ---
@users_router.post("/users/register", tags=["Users"], status_code=status.HTTP_201_CREATED)
def register_user(
    full_name: Annotated[str, Form()],
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
    role: Annotated[UserRole, Form()] = UserRole.DONOR, # Defaults to 'donor' if not specified
):
  
    # Prevent direct registration as an admin
    if role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot register as admin. This role is assigned manually."
        )
    

    # Check if a user with the given email already exists
    if users_collection.count_documents({"email": email}) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )

    # Hash the user's password securely using bcrypt
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    # Create the user document to be inserted into the database
    user_data = {
        "full_name": full_name,
        "email": email,
        "password": hashed_password,
        "role": role.value, # Store the string value of the enum
        "created_at": datetime.now(timezone.utc)
    }
    # --- NEW LOGIC: Set initial status for volunteers ---
    if role == UserRole.VOLUNTEER:
        user_data["application_status"] = "not_applied"  # Initial status

    # Save the new user into the database
    users_collection.insert_one(user_data)

    return {"message": f"User '{full_name}' registered successfully as a {role.value}."}


# --- 3. User Login Endpoint ---
@users_router.post("/users/login", tags=["Users"])
def login_user(
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form(min_length=8)],
):
    # Find the user in the database by their email
    user_in_db = users_collection.find_one({"email": email})

    # Check if the user exists
    if not user_in_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incorrect email or password.",
        )

    # Verify the provided password against the stored hash
    if not bcrypt.checkpw(password.encode("utf-8"), user_in_db["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    #  Prepare the JWT Payload ---
    # The payload must include the user's ID and role for role-based access control.
    payload = {
        "user_id": str(user_in_db["_id"]),
        "role": user_in_db["role"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60) # Token expires in 60 minutes
    }

    # Encode the JWT using the secret key and algorithm from your .env file
    encoded_jwt = jwt.encode(
        payload,
        os.getenv("JWT_SECRET_KEY"),
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    )

    return {
        "message": "User logged in successfully!",
        "access_token": encoded_jwt
    }
