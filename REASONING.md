# REASONING.md

## 1. Understanding the Problem

The main goal of this project is to build a café loyalty points system where every member's points balance remains accurate.

The system allows staff to:

* Search members using their phone number.
* Record purchases.
* Calculate points according to the member's tier.
* Automatically update the points balance.
* Redeem points when sufficient points are available.
* Maintain transaction history.
* Handle a large member list efficiently.

### Important Edge Cases

The following cases were considered while designing the system:

* Member does not exist.
* Purchase amount is zero or negative.
* Redemption amount is zero or negative.
* Member tries to redeem more points than available.
* Duplicate transactions.
* Tier upgrade timing.
* Points balance becoming negative.
* Incorrect balance after multiple transactions.

---

## 2. Approach & Design Decisions

### Technology Stack

The project uses:

* **Backend:** Flask
* **Frontend:** Jinja2 Templates
* **Styling:** Bootstrap
* **Database:** SQLite
* **Version Control:** Git and GitHub

Flask and SQLite were chosen because they are lightweight, easy to set up, and sufficient for the requirements of this project. Jinja templates were used to keep the frontend closely integrated with the Flask backend, while Bootstrap helped create a clean and responsive interface quickly.

### Database Design

The main entities are:

#### Member

Stores information about café members.

```text
id
name
phone
tier
points_balance
created_at
```

#### Transaction

Stores purchase and redemption activity.

```text
id
member_id
transaction_type
amount
points
created_at
```

Keeping transactions separately provides a history of point changes and makes it easier to verify how a member's current balance was generated.

### Tier Logic

The system supports three membership tiers:

```text
Regular
Silver
Gold
```

Each tier has its own points earning rate.

The tier is checked when processing purchases so that the correct earning rate is applied.

Tier upgrades are also checked after eligible purchases.

### Maintaining Correct Balances

The points balance is updated only after validating the operation.

For a purchase:

```text
Current Balance + Earned Points = New Balance
```

For redemption:

```text
Current Balance - Redeemed Points = New Balance
```

Before redemption, the system verifies that the member has enough points.

Database transactions are used so that the transaction record and balance update remain consistent. If an operation fails, the database changes can be rolled back.

---

## 3. How I Used AI Assistance

AI assistance was used during development for:

* Creating the initial project structure.
* Generating Flask routes and templates.
* Suggesting database schema ideas.
* Improving the dashboard UI.
* Identifying possible edge cases.
* Debugging development issues.
* Generating test scenarios.
* Improving documentation and UI copy.

AI-generated output was reviewed rather than accepted blindly.

I manually checked important parts of the application, especially:

* Point calculation.
* Tier-based earning.
* Redemption validation.
* Balance updates.
* Member search.
* UI behavior.
* Transaction history.

The final implementation decisions were made based on the actual project requirements and testing.

---

## 4. Bugs Faced & How I Fixed Them

### Bug 1: Missing "What's Next" Section

After creating the landing page, I reviewed the page against the expected project requirements and noticed that the mandatory **"What's Next"** section was missing.

I specifically asked the coding agent to add this section.

The landing page was then updated with a **"What's Next"** block containing three planned future features:

* QR Member Cards
* Reward Catalogue
* Store Insights

This made the landing page better aligned with the expected product roadmap.

### Bug 2: UI/Requirement Review

During development, I also reviewed the generated UI against the project requirements instead of assuming that the first generated version was complete.

This review helped identify missing or incomplete sections and allowed them to be corrected before finalizing the application.

---

## 5. Testing

The following functionality was tested during development.

### Authentication

* Login works with valid credentials.
* Invalid credentials are rejected.
* Registration validation works correctly.

### Purchase

* Purchase points are calculated according to the member's tier.
* Regular, Silver, and Gold earning rates were checked.
* Invalid purchase amounts are rejected.
* Points are added to the member's balance after a successful purchase.

### Redemption

* Valid redemption decreases the balance correctly.
* Redemption greater than the available balance is blocked.
* Zero or negative redemption values are rejected.
* The points balance cannot become negative.

### Member Search

* Members can be searched using their phone number.
* Correct member details are displayed.
* Unknown phone numbers are handled correctly.
* Search works with a large member list.

### Tier System

* Tier information is displayed correctly.
* Tier upgrades are checked after eligible purchases.
* The appropriate earning rate is applied based on the member's tier.

### Transactions

* Purchases create transaction records.
* Redemptions create transaction records.
* Balance changes correspond to the recorded transactions.
* Failed operations do not incorrectly change the balance.

---

## 6. What I Would Improve With More Time

With more development time, I would consider adding:

* QR-code based member lookup.
* A reward catalogue.

## 7. Extension 2: Deterministic Points Expiry

The expiry feature stores the last simulated date in a singleton `ClockState` row. `POST /clock` updates that value and runs the expiry job using the submitted date, so grading and tests do not depend on the real system clock.

The simpler full-balance policy is used: if the latest transaction is more than 90 days before the simulated date, a member's positive `points_balance` becomes zero and an `expire` transaction records the negative change. Lifetime points are not reduced.

Expiry is idempotent. The update requires a positive balance, and the newly created expiry transaction becomes the member's latest activity. Calling `/clock` again with the same date therefore cannot create a second expiry transaction.
* Store-level analytics and insights.
* Automated unit and integration tests.
* More detailed transaction filters.
* Role-based access for staff and administrators.
* Better error messages and notifications.
* PostgreSQL for a larger production deployment.
* Audit logs for important account changes.

---

## 7. Key Design Principle

The most important principle of this project is:

> **The member's points balance must always remain correct.**

Every purchase and redemption should therefore be validated, recorded, and reflected in the member's balance consistently.

The transaction history also provides a way to verify how the current balance was produced.

user id = demo
user Password = demo@123

## 8. Extension 3: Tier-Change Notifications

Tier upgrades use an internal outbox pattern because there is no external notification provider. Each upgrade inserts an `Outbox` row containing the member ID, old tier, new tier, event type, message payload, creation time, and pending status.

The notification insert happens inside the same database transaction as the purchase balance update and earn transaction. If the purchase fails, the tier change and notification are both rolled back. The startup Platinum migration also creates a notification for members promoted during that one-time qualification check.

`GET /outbox` returns pending and processed records in newest-first order with pagination. Repeated expiry runs do not create tier notifications because expiry does not change a member's tier, and purchases that do not cross a tier threshold do not create outbox records.
