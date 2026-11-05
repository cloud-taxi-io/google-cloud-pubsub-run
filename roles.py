"""User roles, stored as a custom claim ("role") in the Firebase / Identity Platform ID token."""

CLIENT_VTC_CLASSIQUE = "client-vtc-classique"
TAXI = "taxi"

ROLES = {CLIENT_VTC_CLASSIQUE, TAXI}

# Role given to a user until an admin changes it. Taxi is never the default: it must be granted.
DEFAULT_ROLE = CLIENT_VTC_CLASSIQUE

CLAIM_NAME = "role"


def is_valid_role(role):
    return role in ROLES
