from flask import Flask, render_template, request, redirect, url_for, session, flash
import pandas as pd
import os
from werkzeug.security import generate_password_hash, check_password_hash
import random

app = Flask(__name__)
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

# -------- In-memory storage --------
users = []
watchlists = []
portfolio = []


# ---------------- HELPERS ---------------- #

def load_latest_prices():
    prices = []
    for company, file in COMPANIES.items():
        df = pd.read_csv(os.path.join(DATA_FOLDER, file))
        latest = df.iloc[-1]

        prices.append({
            "company": company,
            "price": round(float(latest["Close"]), 2),
            "date": latest["Date"]
        })

    return prices


def get_user():
    username = session.get("user")
    if not username:
        return None

    return next((u for u in users if u["name"] == username), None)


# ---------------- ROUTES ---------------- #

@app.route("/")
def main():
    return render_template("main.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------------- SIGNUP ---------------- #

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        email = request.form["email"]

        # prevent duplicate users
        if any(u["email"] == email for u in users):
            flash("Email already registered. Please login.")
            return redirect(url_for("login"))

        users.append({
            "id": len(users) + 1,
            "name": request.form["name"],
            "email": email,
            "password": generate_password_hash(request.form["password"]),
            "balance": 100000
        })

        flash("Account created successfully. Please login.")
        return redirect(url_for("login"))

    return render_template("signup.html")


# ---------------- LOGIN ---------------- #

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        user = next((u for u in users if u["email"] == email), None)

        if user and check_password_hash(user["password"], password):
            session["user"] = user["name"]
            return redirect(url_for("dashboard"))

        flash("User not registered or incorrect password")

    return render_template("login.html")


# ---------------- DASHBOARD ---------------- #

@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect(url_for("login"))

    user = get_user()

    if not user:
        session.clear()
        flash("Session expired. Login again.")
        return redirect(url_for("login"))

    stocks = load_latest_prices()

    user_watchlist = [
        w["company"]
        for w in watchlists
        if w["user"] == session["user"]
    ]

    return render_template(
        "dashboard.html",
        stocks=stocks,
        user=session["user"],
        balance=user["balance"],
        user_watchlist=user_watchlist
    )


# ---------------- BUY ---------------- #

@app.route("/buy/<company>", methods=["POST"])
def buy_stock(company):

    if "user" not in session:
        flash("Login first")
        return redirect(url_for("login"))

    user = get_user()

    if not user:
        session.clear()
        flash("Session expired")
        return redirect(url_for("login"))

    try:
        qty = int(request.form["quantity"])
    except:
        flash("Invalid quantity")
        return redirect(url_for("dashboard"))

    stocks = load_latest_prices()

    stock = next((s for s in stocks if s["company"] == company), None)

    if not stock:
        flash("Stock not found")
        return redirect(url_for("dashboard"))

    total_cost = qty * stock["price"]

    if user["balance"] < total_cost:
        flash("Insufficient balance")
        return redirect(url_for("dashboard"))

    user["balance"] -= total_cost

    portfolio.append({
        "user": session["user"],
        "company": company,
        "quantity": qty,
        "buy_price": stock["price"]
    })

    flash(f"Bought {qty} shares of {company}")

    return redirect(url_for("portfolio_page"))


# ---------------- SELL ---------------- #

@app.route("/sell/<company>", methods=["POST"])
def sell_stock(company):

    if "user" not in session:
        return redirect(url_for("login"))

    qty_to_sell = int(request.form["quantity"])
    sell_price = float(request.form["sell_price"])

    user = get_user()

    holding = next(
        (p for p in portfolio
         if p["user"] == session["user"] and p["company"] == company),
        None
    )

    if not holding or holding["quantity"] < qty_to_sell:
        flash("Not enough quantity to sell")
        return redirect(url_for("portfolio_page"))

    user["balance"] += sell_price * qty_to_sell

    holding["quantity"] -= qty_to_sell

    if holding["quantity"] == 0:
        portfolio.remove(holding)

    flash("Stock sold successfully")

    return redirect(url_for("portfolio_page"))


# ---------------- PORTFOLIO ---------------- #

@app.route("/portfolio")
def portfolio_page():

    if "user" not in session:
        return redirect(url_for("login"))

    user = get_user()

    prices = load_latest_prices()

    user_portfolio = [
        p for p in portfolio
        if p["user"] == session["user"]
    ]

    portfolio_view = []
    total_pnl = 0

    for p in user_portfolio:

        stock_price = next(
            s["price"] for s in prices if s["company"] == p["company"]
        )

        current_price = round(stock_price * random.uniform(0.95, 1.05), 2)

        pnl = round((current_price - p["buy_price"]) * p["quantity"], 2)

        total_pnl += pnl

        portfolio_view.append({
            "company": p["company"],
            "quantity": p["quantity"],
            "buy_price": p["buy_price"],
            "current_price": current_price,
            "pnl": pnl
        })

    return render_template(
        "portfolio.html",
        portfolio=portfolio_view,
        balance=user["balance"],
        user=session["user"],
        total_pnl=round(total_pnl, 2)
    )


# ---------------- WATCHLIST ---------------- #

@app.route("/add_to_watchlist/<company>")
def add_to_watchlist(company):

    if not any(
        w["user"] == session["user"] and w["company"] == company
        for w in watchlists
    ):
        watchlists.append({
            "user": session["user"],
            "company": company
        })

    return redirect(url_for("dashboard"))


@app.route("/watchlist")
def watchlist():

    if "user" not in session:
        return redirect(url_for("login"))

    user = get_user()

    user_companies = [
        w["company"]
        for w in watchlists
        if w["user"] == session["user"]
    ]

    all_prices = load_latest_prices()

    watchlist_data = [
        s for s in all_prices
        if s["company"] in user_companies
    ]

    return render_template(
        "watchlist.html",
        watchlist=watchlist_data,
        user=session["user"],
        balance=user["balance"]
    )


# ---------------- LOGOUT ---------------- #

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
