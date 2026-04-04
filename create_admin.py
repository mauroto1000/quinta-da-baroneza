"""
Run this script once to create the first admin user.
Usage:  python create_admin.py
"""
from app.database import SessionLocal, engine
from app import models
from app.auth import hash_password

models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

full_name = input("Nome completo: ").strip()
email = input("E-mail: ").strip().lower()
whatsapp = input("WhatsApp: ").strip()
password = input("Senha (min 6 chars): ").strip()

if len(password) < 6:
    print("Senha muito curta.")
    exit(1)

existing = db.query(models.User).filter(models.User.email == email).first()
if existing:
    print(f"E-mail {email} já cadastrado.")
    exit(1)

admin = models.User(
    full_name=full_name,
    email=email,
    whatsapp=whatsapp,
    password_hash=hash_password(password),
    role=models.UserRole.ADMIN,
)
db.add(admin)

# Seed default configs
from app.models import DEFAULT_CONFIGS
for key, (value, description) in DEFAULT_CONFIGS.items():
    if not db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first():
        db.add(models.SystemConfig(key=key, value=value, description=description))

db.commit()
print(f"\nAdmin '{full_name}' criado com sucesso! Acesse com {email}.")
db.close()
