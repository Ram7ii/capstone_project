from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import boto3
import pandas as pd
import random
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# --------------------------------------------------
# APP CONFIG
# --------------------------------------------------

app = Flask(__name__)
application = app   # for gunicorn / AWS
app.secret_key = os.environ.get("FLASK_SECRET", "nebula_secret")

DATA_FOLDER = "data"
AWS_REGION = "us-east-1"

# --------------------------------------------------
# AWS CLIENTS
# --------------------------------------------------

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)

USERS_TABLE = "Users"
PORTFOLIO_TABLE = "Portfolio"
WATCHLIST_TABLE = "Watchlist"

SNS_TOPIC_ARN = os.environ.get(
    "SNS_TOPIC_ARN",
    "arn:aws:sns:us-east-1:242201268861:aws-capstone-topic"
)

users_table = dynamodb.Table(USERS_TABLE)
portfolio_table = dynamodb.Table(PORTFOLIO_TABLE)
watchlist_table = dynamodb.Table(WATCHLIST_TABLE)

# --------------------------------------------------
# STOCK DATA
# --------------------------------------------------

COMPANIES = {
    "Apple": "Apple.csv",
    "Google": "Google.csv",
    "Amazon": "Amazon.csv",
    "Netflix": "Netflix.csv",
    "Facebook": "Facebook.csv",
    "Microsoft": "Microsoft.csv",
    "Tesla": "Tesla.csv",
    "Uber": "Uber.csv",
    "Walmart": "Walmart.csv",
    "Zoom": "Zoom.csv"
}

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def send_notification(subject, message):
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
    except ClientError as e:
        print("SNS ERROR:", e)


def get_latest_price(company):
    df = pd.read_csv(os.path.join(DATA_FOLDER, COMPANIES[company]))
    row = df.iloc[-1]
    return Decimal(str(round(float(row["Close"]), 2))), row["Date"]


def get_all_prices():
    data = []
    for c in COMPANIES:
        price, date = get_latest_price(c)
        data.append({
            "company": c,
            "price": float(price),
            "date": date
        })
    return data


def get_user():
    if "email" not in session:
        return None

    res = users_table.get_item(Key={"email": session["email"]})
    return res.get("Item")


# --------------------------------------------------
# PUBLIC ROUTES
# --------------------------------------------------

@app.route("/")
def main():
    return render_template("main.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# --------------------------------------------------
# AUTH
# --------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        email = request.form["email"]

        existing = users_table.get_item(Key={"email": email})
        if "Item" in existing:
            flash("Account already exists. Please login.")
            return redirect(url_for("login"))

        users_table.put_item(Item={
            "email": email,
            "name": request.form["name"],
            "password": generate_password_hash(request.form["password"]),
            "balance": Decimal("100000")
        })

        send_notification("New Signup", f"User {email} registered.")

        flash("Signup successful. Login now.")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        res = users_table.get_item(Key={"email": email})
        user = res.get("Item")

        if not user or not check_password_hash(user["password"], password):
            flash("User not registered or incorrect password.")
            return redirect(url_for("login"))

        session["email"] = email
        session["user"] = user["name"]

        send_notification("User Login", f"{email} logged in.")

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():

    if "email" not in session:
        flash("Login required.")
        return redirect(url_for("login"))

    user = get_user()
    if not user:
        session.clear()
        flash("Session expired.")
        return redirect(url_for("login"))

    stocks = get_all_prices()

    wl = watchlist_table.query(
        KeyConditionExpression=Key("email").eq(session["email"])
    ).get("Items", [])

    watchlist = [i["company"] for i in wl]

    return render_template(
        "dashboard.html",
        stocks=stocks,
        user=session["user"],
        balance=float(user["balance"]),
        user_watchlist=watchlist
    )


# --------------------------------------------------
# BUY STOCK
# --------------------------------------------------

@app.route("/buy/<company>", methods=["POST"])
def buy_stock(company):

    if "email" not in session:
        return redirect(url_for("login"))

    qty = int(request.form["quantity"])

    price, _ = get_latest_price(company)
    total_cost = price * Decimal(qty)

    user = get_user()

    if total_cost > user["balance"]:
        flash("❌ Insufficient balance")
        return redirect(url_for("dashboard"))

    users_table.update_item(
        Key={"email": session["email"]},
        UpdateExpression="SET balance = balance - :amt",
        ExpressionAttributeValues={":amt": total_cost}
    )

    portfolio_table.put_item(Item={
        "email": session["email"],
        "company": company,
        "quantity": qty,
        "buy_price": price
    })

    send_notification(
        "Stock Purchased",
        f"{session['email']} bought {qty} shares of {company}"
    )

    flash(f"✅ Bought {qty} shares of {company}")
    return redirect(url_for("portfolio_page"))


# --------------------------------------------------
# PORTFOLIO
# --------------------------------------------------

@app.route("/portfolio")
def portfolio_page():

    if "email" not in session:
        return redirect(url_for("login"))

    response = portfolio_table.query(
        KeyConditionExpression=Key("email").eq(session["email"])
    )

    prices = {s["company"]: Decimal(str(s["price"])) for s in get_all_prices()}

    view = []
    total_pnl = 0

    for p in response.get("Items", []):

        cur = prices[p["company"]] * Decimal(str(random.uniform(0.97, 1.03)))
        pnl = (cur - p["buy_price"]) * Decimal(p["quantity"])

        total_pnl += pnl

        view.append({
            "company": p["company"],
            "quantity": p["quantity"],
            "buy_price": float(p["buy_price"]),
            "current_price": float(cur),
            "pnl": float(pnl)
        })

    user = get_user()

    return render_template(
        "portfolio.html",
        portfolio=view,
        balance=float(user["balance"]),
        total_pnl=round(float(total_pnl), 2),
        user=session["user"]
    )


# --------------------------------------------------
# WATCHLIST
# --------------------------------------------------

@app.route("/add_to_watchlist/<company>")
def add_to_watchlist(company):

    watchlist_table.put_item(Item={
        "email": session["email"],
        "company": company
    })

    return redirect(url_for("dashboard"))


@app.route("/watchlist")
def watchlist():

    wl = watchlist_table.query(
        KeyConditionExpression=Key("email").eq(session["email"])
    ).get("Items", [])

    companies = [i["company"] for i in wl]

    prices = get_all_prices()
    data = [p for p in prices if p["company"] in companies]

    user = get_user()

    return render_template(
        "watchlist.html",
        watchlist=data,
        balance=float(user["balance"]),
        user=session["user"]
    )


# --------------------------------------------------
# CHART
# --------------------------------------------------

@app.route("/chart/<company>")
def chart(company):

    df = pd.read_csv(os.path.join(DATA_FOLDER, COMPANIES[company]))

    return render_template(
        "chart.html",
        company=company,
        data=df.tail(30).to_dict("records")
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
