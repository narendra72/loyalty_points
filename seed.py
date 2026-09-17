from decimal import Decimal

from app import create_app
from extensions import db
from models import Member, User

app = create_app()
with app.app_context():
    if not db.session.scalar(db.select(User).where(User.username == "demo")):
        user = User(username="demo", role="admin")
        user.set_password("demo1234")
        db.session.add(user)
    if not db.session.scalar(db.select(Member).where(Member.phone == "9876543210")):
        db.session.add_all([
            Member(name="Asha Menon", phone="9876543210", tier="Gold", points_balance=1240, lifetime_points=1420),
            Member(name="Rohan Shah", phone="9123456780", tier="Silver", points_balance=310, lifetime_points=620),
            Member(name="Meera Iyer", phone="9988776655", tier="Regular", points_balance=86, lifetime_points=86),
            Member(name="Platinum Preview", phone="9000000000", tier="Platinum", points_balance=500, lifetime_points=5000),
        ])
    db.session.commit()
    print("Seed complete. Login with demo / demo1234")
