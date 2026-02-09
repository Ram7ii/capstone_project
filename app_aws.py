from flask import Flask, render_template, request, redirect, url_for, session, flash

import pandas as pd
import os
import boto3
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from boto3.dynamodb.conditions import Key


app = Flask(__name__)
application = app
app.secret_key = "dev_secret_key"

DATA_FOLDER = "data"

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
}

# ---------- AWS ----------
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
users_table = dynamodb.Table("Users")
portfolio_table = dynamodb.Table("Portfolio")
watchlist_table = dynamodb.Table("Watchlist")

# ---------- HELPERS ----------
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

# ---------- MAIN ----------
@app.route("/")
def main():
    return render_template("main.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------- AUTH ----------
@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        users_table.put_item(Item={
            "email": request.form["email"],
            "name": request.form["name"],
            "password": generate_password_hash(request.form["password"]),
            "balance": Decimal("100000")
        })
        return redirect("/login")
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        user = next(
            (u for u in users if u["email"] == request.form["email"]),
            None
        )

        if user and check_password_hash(user["password"], request.form["password"]):
            session["user"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("❌ Invalid email or password")

        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "email" not in session:
        return redirect("/login")

    stocks = get_all_prices()
    user = users_table.get_item(Key={"email": session["email"]}).get("Item")

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

# ---------- BUY ----------
@app.route("/buy/<company>", methods=["POST"])
def buy(company):
    qty = int(request.form["quantity"])
    price, _ = get_latest_price(company)
    total = price * Decimal(qty)

    user = users_table.get_item(Key={"email": session["email"]}).get("Item")

    if total > user["balance"]:
        return "Insufficient balance"

    users_table.update_item(
        Key={"email": session["email"]},
        UpdateExpression="SET balance = balance - :amt",
        ExpressionAttributeValues={":amt": total}
    )

    portfolio_table.put_item(Item={
        "email": session["email"],
        "company": company,
        "quantity": qty,
        "buy_price": price
    })

    return redirect("/portfolio")

# ---------- PORTFOLIO ----------
@app.route("/portfolio")
def portfolio():
    response = portfolio_table.query(
        KeyConditionExpression=Key("email").eq(session["email"])
    )

    prices = {s["company"]: Decimal(str(s["price"])) for s in get_all_prices()}
    view = []

    for p in response.get("Items", []):
        cur = prices[p["company"]]
        pnl = (cur - p["buy_price"]) * Decimal(p["quantity"])

        view.append({
            "company": p["company"],
            "quantity": p["quantity"],
            "buy_price": float(p["buy_price"]),
            "current_price": float(cur),
            "pnl": float(pnl)
        })

    user = users_table.get_item(Key={"email": session["email"]}).get("Item")

    return render_template(
        "portfolio.html",
        portfolio=view,
        balance=float(user["balance"]),
        user=session["user"]
    )

# ---------- WATCHLIST ----------
@app.route("/add_to_watchlist/<company>")
def add_to_watchlist(company):
    watchlist_table.put_item(Item={
        "email": session["email"],
        "company": company
    })
    return redirect("/dashboard")

@app.route("/watchlist")
def watchlist():
    wl = watchlist_table.query(
        KeyConditionExpression=Key("email").eq(session["email"])
    ).get("Items", [])

    prices = get_all_prices()
    data = [p for p in prices if p["company"] in [i["company"] for i in wl]]

    user = users_table.get_item(Key={"email": session["email"]}).get("Item")

    return render_template(
        "watchlist.html",
        watchlist=data,
        balance=float(user["balance"]),
        user=session["user"]
    )

# ---------- CHART ----------
@app.route("/chart/<company>")
def chart(company):
    df = pd.read_csv(os.path.join(DATA_FOLDER, COMPANIES[company]))
    return render_template(
        "chart.html",
        company=company,
        data=df.tail(30).to_dict("records")
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
