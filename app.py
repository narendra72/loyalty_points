import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for, flash
from sqlalchemy import func, inspect, or_, text, update
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import ClockState, Member, Outbox, RewardTransaction, User


TIER_RATES = {"Regular": Decimal("1"), "Silver": Decimal("1.5"), "Gold": Decimal("2")}
TIER_THRESHOLDS = {"Regular": 0, "Silver": 500, "Gold": 1000, "Platinum": 5000}
SORT_FIELDS = {"name": Member.name, "phone": Member.phone, "tier": Member.tier, "points": Member.points_balance, "created_at": Member.created_at}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///loyalty.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        run_member_migrations()

    register_routes(app)
    return app


def json_error(message, status=400):
    return jsonify({"error": message}), status


def payload():
    return request.get_json(silent=True) or request.form


def get_member(member_id):
    return db.session.get(Member, member_id)


def get_clock_date():
    clock = db.session.get(ClockState, 1)
    return clock.current_date if clock else None


def transaction_timestamp():
    clock_date = get_clock_date()
    if clock_date:
        return datetime.combine(clock_date, time(hour=12), tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def run_expiry_job(simulated_date):
    expired_count = 0
    members = db.session.scalars(db.select(Member).where(Member.points_balance > 0)).all()
    for member in members:
        last_transaction = db.session.scalar(
            db.select(func.max(RewardTransaction.timestamp)).where(RewardTransaction.member_id == member.id)
        )
        if not last_transaction or simulated_date - last_transaction.date() <= timedelta(days=90):
            continue
        points_to_expire = member.points_balance
        updated = db.session.execute(
            update(Member)
            .where(Member.id == member.id, Member.points_balance == points_to_expire, Member.points_balance > 0)
            .values(points_balance=0)
        )
        if updated.rowcount == 1:
            db.session.add(RewardTransaction(
                member_id=member.id,
                type="expire",
                amount=Decimal("0.00"),
                points_change=-points_to_expire,
                timestamp=transaction_timestamp(),
            ))
            expired_count += 1
    return expired_count


def parse_clock_date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("date must use YYYY-MM-DD format")


def serialize_member(member):
    return {
        "id": member.id, "name": member.name, "phone": member.phone,
        "tier": member.tier, "points_balance": member.points_balance,
        "lifetime_points": member.lifetime_points,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


def serialize_transaction(transaction):
    return {
        "id": transaction.id, "member_id": transaction.member_id, "type": transaction.type,
        "amount": float(transaction.amount), "points_change": transaction.points_change,
        "timestamp": transaction.timestamp.isoformat() if transaction.timestamp else None,
    }


def serialize_outbox(event):
    return {
        "id": event.id,
        "member_id": event.member_id,
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "status": event.status,
    }


def parse_amount(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("amount must be a valid number")
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    return amount


def calculate_earned_points(amount, tier):
    amount = Decimal(str(amount))
    if tier == "Platinum":
        return int((amount * Decimal("0.3")).to_integral_value(rounding=ROUND_FLOOR))
    return int((amount / Decimal("10") * TIER_RATES[tier]).to_integral_value(rounding=ROUND_FLOOR))


def run_member_migrations():
    """Backfill legacy databases without changing existing balances or tiers."""
    columns = {column["name"] for column in inspect(db.engine).get_columns("member")}
    if "lifetime_points" not in columns:
        db.session.execute(text("ALTER TABLE member ADD COLUMN lifetime_points INTEGER NOT NULL DEFAULT 0"))
        db.session.commit()
        db.session.execute(text("""
            UPDATE member
            SET lifetime_points = COALESCE((
                SELECT SUM(points_change)
                FROM transactions
                WHERE transactions.member_id = member.id
                  AND transactions.type = 'earn'
            ), 0)
            WHERE lifetime_points = 0
        """))
        db.session.commit()

    qualified_members = db.session.scalars(
        db.select(Member).where(Member.lifetime_points >= TIER_THRESHOLDS["Platinum"], Member.tier != "Platinum")
    ).all()
    for member in qualified_members:
        old_tier = member.tier
        member.tier = "Platinum"
        add_tier_notification(member, old_tier, member.tier)
    if qualified_members:
        db.session.commit()


def update_tier(member):
    old_tier = member.tier
    if member.lifetime_points >= TIER_THRESHOLDS["Platinum"]:
        member.tier = "Platinum"
    elif member.lifetime_points >= TIER_THRESHOLDS["Gold"]:
        member.tier = "Gold"
    elif member.lifetime_points >= TIER_THRESHOLDS["Silver"]:
        member.tier = "Silver"
    return old_tier, member.tier


def add_tier_notification(member, old_tier, new_tier):
    if old_tier == new_tier:
        return
    db.session.add(Outbox(
        member_id=member.id,
        event_type="member.tier_upgraded",
        payload={
            "member_id": member.id,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "message": f"Congrats, you've been upgraded to {new_tier}!",
        },
        status="pending",
    ))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return json_error("authentication required", 401)
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def register_routes(app):
    @app.get("/")
    def landing():
        return render_template("landing.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            user = db.session.scalar(db.select(User).where(User.username == username))
            if user and user.check_password(request.form.get("password", "")):
                session.clear()
                session["user_id"] = user.id
                session["username"] = user.username
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if len(username) < 3 or len(password) < 8:
                flash("Username must be 3+ characters and password 8+ characters.", "danger")
            else:
                user = User(username=username, role="staff")
                user.set_password(password)
                db.session.add(user)
                try:
                    db.session.commit()
                    flash("Registration successful. Please log in.", "success")
                    return redirect(url_for("login"))
                except IntegrityError:
                    db.session.rollback()
                    flash("That username is already in use.", "danger")
        return render_template("register.html")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("landing"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/members/<int:member_id>")
    @login_required
    def member_detail(member_id):
        member = get_member(member_id)
        if not member:
            return render_template("404.html"), 404
        transactions = db.session.scalars(db.select(RewardTransaction).where(RewardTransaction.member_id == member_id).order_by(RewardTransaction.timestamp.desc())).all()
        return render_template("member_detail.html", member=member, transactions=transactions)

    @app.post("/api/auth/register")
    def api_register():
        data = payload()
        username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
        if len(username) < 3 or len(password) < 8:
            return json_error("username must be 3+ characters and password 8+ characters")
        user = User(username=username, role="staff")
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return json_error("username already exists", 409)
        return jsonify({"id": user.id, "username": user.username, "role": user.role}), 201

    @app.post("/api/auth/login")
    def api_login():
        data = payload()
        user = db.session.scalar(db.select(User).where(User.username == str(data.get("username", "")).strip()))
        if not user or not user.check_password(str(data.get("password", ""))):
            return json_error("invalid username or password", 401)
        session["user_id"], session["username"] = user.id, user.username
        return jsonify({"message": "logged in", "user": {"id": user.id, "username": user.username, "role": user.role}})

    @app.get("/api/members")
    @login_required
    def api_members():
        page = request.args.get("page", 1, type=int)
        limit = min(request.args.get("limit", 10, type=int), 100)
        if page < 1 or limit < 1:
            return json_error("page and limit must be positive")
        query = db.select(Member)
        search = request.args.get("search", "").strip()
        if search:
            query = query.where(or_(Member.name.ilike(f"%{search}%"), Member.phone.ilike(f"%{search}%")))
        sort_column = SORT_FIELDS.get(request.args.get("sort", "created_at"), Member.created_at)
        query = query.order_by(sort_column.desc() if request.args.get("order", "desc").lower() == "desc" else sort_column.asc())
        pagination = db.paginate(query, page=page, per_page=limit, error_out=False)
        return jsonify({"members": [serialize_member(m) for m in pagination.items], "page": page, "limit": limit, "total": pagination.total, "pages": pagination.pages})

    @app.get("/api/members/<int:member_id>")
    @login_required
    def api_member(member_id):
        member = get_member(member_id)
        return jsonify(serialize_member(member)) if member else json_error("member not found", 404)

    @app.post("/api/members")
    @login_required
    def api_create_member():
        data = payload()
        name, phone = str(data.get("name", "")).strip(), str(data.get("phone", "")).strip()
        if not name or not phone:
            return json_error("name and phone are required")
        member = Member(name=name, phone=phone)
        db.session.add(member)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return json_error("phone already belongs to a member", 409)
        return jsonify(serialize_member(member)), 201

    @app.post("/api/members/<int:member_id>/purchase")
    @login_required
    def api_purchase(member_id):
        data = payload()
        try:
            amount = parse_amount(data.get("amount"))
        except ValueError as error:
            return json_error(str(error))
        member = get_member(member_id)
        if not member:
            return json_error("member not found", 404)
        points = calculate_earned_points(amount, member.tier)
        if points < 1:
            return json_error("purchase is too small to earn a point")
        try:
            with db.session.begin_nested():
                db.session.execute(update(Member).where(Member.id == member_id).values(
                    points_balance=Member.points_balance + points,
                    lifetime_points=Member.lifetime_points + points,
                ))
                db.session.refresh(member)
                old_tier, new_tier = update_tier(member)
                add_tier_notification(member, old_tier, new_tier)
                db.session.add(RewardTransaction(member_id=member.id, type="earn", amount=amount, points_change=points, timestamp=transaction_timestamp()))
            db.session.commit()
        except Exception:
            db.session.rollback()
            return json_error("purchase could not be recorded", 500)
        return jsonify({"member": serialize_member(member), "points_earned": points}), 201

    @app.post("/api/members/<int:member_id>/redeem")
    @login_required
    def api_redeem(member_id):
        data = payload()
        try:
            points = int(data.get("points", 0))
            amount = parse_amount(data.get("amount", "0.01"))
        except (ValueError, TypeError):
            return json_error("points must be a positive whole number and amount must be valid")
        if points < 1:
            return json_error("points must be a positive whole number")
        member = get_member(member_id)
        if not member:
            return json_error("member not found", 404)
        try:
            with db.session.begin_nested():
                updated = db.session.execute(update(Member).where(Member.id == member_id, Member.points_balance >= points).values(points_balance=Member.points_balance - points))
                if updated.rowcount != 1:
                    db.session.rollback()
                    return json_error("insufficient points balance")
                db.session.add(RewardTransaction(member_id=member_id, type="redeem", amount=amount, points_change=-points, timestamp=transaction_timestamp()))
            db.session.commit()
            db.session.refresh(member)
        except Exception:
            db.session.rollback()
            return json_error("redemption could not be recorded", 500)
        return jsonify({"member": serialize_member(member), "points_redeemed": points}), 201

    @app.get("/api/members/<int:member_id>/transactions")
    @login_required
    def api_transactions(member_id):
        if not get_member(member_id):
            return json_error("member not found", 404)
        transactions = db.session.scalars(db.select(RewardTransaction).where(RewardTransaction.member_id == member_id).order_by(RewardTransaction.timestamp.desc())).all()
        return jsonify({"transactions": [serialize_transaction(item) for item in transactions]})

    @app.post("/clock")
    def set_clock():
        data = payload()
        try:
            simulated_date = parse_clock_date(data.get("date"))
        except ValueError as error:
            return json_error(str(error))
        clock = db.session.get(ClockState, 1)
        if not clock:
            clock = ClockState(id=1)
            db.session.add(clock)
        clock.current_date = simulated_date
        try:
            expired_count = run_expiry_job(simulated_date)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return json_error("expiry job could not be completed", 500)
        return jsonify({"current_date": simulated_date.isoformat(), "expired_members": expired_count})

    @app.get("/outbox")
    @login_required
    def outbox_events():
        page = request.args.get("page", 1, type=int)
        limit = min(request.args.get("limit", 10, type=int), 100)
        if page < 1 or limit < 1:
            return json_error("page and limit must be positive")
        pagination = db.paginate(
            db.select(Outbox).order_by(Outbox.created_at.desc(), Outbox.id.desc()),
            page=page,
            per_page=limit,
            error_out=False,
        )
        return jsonify({
            "outbox": [serialize_outbox(event) for event in pagination.items],
            "page": page,
            "limit": limit,
            "total": pagination.total,
            "pages": pagination.pages,
        })

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return json_error("resource not found", 404)
        return render_template("404.html"), 404


app = create_app()
