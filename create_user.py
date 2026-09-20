import sys
import os
import getpass
import bcrypt

# =========================================================
# PROJECT ROOT
# =========================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# If this file is placed inside Frontend/, go one level up.
if os.path.basename(PROJECT_ROOT).lower() == "frontend":
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)

sys.path.insert(0, PROJECT_ROOT)

# =========================================================
# MONGODB
# =========================================================

from mongodb import users

# =========================================================
# CREATE USER
# =========================================================

print("=" * 50)
print("IN/OUT X - CREATE USER")
print("=" * 50)

name = input("User name: ").strip()
email = input("User email: ").strip().lower()
role = input("User role: ").strip().lower()
password = getpass.getpass("User password: ")
confirm_password = getpass.getpass("Confirm password: ")

# =========================================================
# VALIDATION
# =========================================================

if not name:
    print("Error: name is required.")
    raise SystemExit(1)

if len(name) > 100:
    print("Error: name must not exceed 100 characters.")
    raise SystemExit(1)

if not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
    print("Error: please enter a valid email address.")
    raise SystemExit(1)

if not role:
    print("Error: role is required.")
    raise SystemExit(1)

if len(email) > 254:
    print("Error: email address is too long.")
    raise SystemExit(1)

if len(password) < 6:
    print("Error: password must contain at least 6 characters.")
    raise SystemExit(1)

if password != confirm_password:
    print("Error: passwords do not match.")
    raise SystemExit(1)

# =========================================================
# DUPLICATE CHECK
# =========================================================

existing = users.find_one({"email": email})

if existing:
    print("Error: an account with this email already exists.")
    raise SystemExit(1)

# =========================================================
# HASH PASSWORD
# =========================================================

hashed_password = bcrypt.hashpw(
    password.encode("utf-8"),
    bcrypt.gensalt()
).decode("utf-8")

# =========================================================
# USER DOCUMENT
# =========================================================

user_document = {
    "name": name,
    "email": email,
    "password": hashed_password,
    "role": role,
    "active": True,
    "email_verified": True
}

# =========================================================
# SAVE
# =========================================================

result = users.insert_one(user_document)

# =========================================================
# SUCCESS
# =========================================================

print()
print("User account created successfully.")
print("User ID:", result.inserted_id)
print("Name:", name)
print("Email:", email)
print("Role:", role)
print("Active: True")
print()
