import bcrypt
from datetime import datetime

# Import your existing MongoDB users collection
from mongodb import users


EMAIL = "inoutx.testing@gmail.com"
PASSWORD = "inoutx@01"


existing = users.find_one({
    "email": EMAIL.lower()
})

if existing:
    print("A user with this email already exists.")
else:

    password_hash = bcrypt.hashpw(
        PASSWORD.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user = {
        "name": "INOUTX Configuration Admin",
        "email": EMAIL.lower(),
        "password": password_hash,
        "role": "config_admin",
        "active": True,
        "email_verified": True,
        "created_at": datetime.now()
    }

    result = users.insert_one(user)

    print("========================================")
    print("Configuration admin created successfully")
    print("Email:", EMAIL)
    print("Role: config_admin")
    print("ID:", result.inserted_id)
    print("========================================")