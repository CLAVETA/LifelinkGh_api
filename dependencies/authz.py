from dependencies.authn import authenticated_user
from fastapi import Depends, HTTPException, status
from typing import Annotated


permissions = [
    {
        "role":"admin",
        "permissions":["*"]
    },
    {
        "role":"volunteer",
        "permissions":["submit_volunteer_application",
                       "get_volunteer_dashboard",
                       "get_all_approved_volunteers",
                       ]
    }
]


def has_roles(roles):
    def check_roles(user: Annotated[any, Depends(authenticated_user)]):
        if user["role"] not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Access denied!"
            )

    return check_roles

def has_permission(permission):
    def check_permission(user: Annotated[any, Depends(authenticated_user)]):
        role = user.get("role")
        for entry in permissions:
            if entry["role"] == role:
                perms = entry.get("permissions", [])
                if "*" in perms or permission in perms:
                    return user
                break
            raise HTTPException(status. HTTP_403_FORBIDDEN,"Permission denied")
        return check_permission
    
def require_approved_volunteer(user: Annotated[dict, Depends(authenticated_user)]):
    if user.get("role") != "volunteer" or user.get("application_status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Volunteer role and approved status required."
        )
    return user