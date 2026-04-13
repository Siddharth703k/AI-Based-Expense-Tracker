# ==========================
# AI-Based Expense Tracker
# ==========================

from flask import Flask, request, redirect, render_template_string
import sqlite3
from datetime import datetime,timedelta
import statistics
app = Flask(__name__)

# =========================
# DATABASE SETUP
# =========================
def init_db():
    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL,
        category TEXT,
        description TEXT,
        date TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS budget (
        id INTEGER PRIMARY KEY,
        amount REAL
    )''')

    conn.commit()
    conn.close()

init_db()

# =========================
# AI SUGGESTIONS
# =========================
def get_suggestions(expenses, budget):
    suggestions = []
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')

    # ── helpers ──────────────────────────────────────────────────────────────
    def parse_date(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d')
        except:
            return None

    def cat_lower(e):
        return e[2].lower() if e[2] else 'other'

    # ── group by date ────────────────────────────────────────────────────────
    by_date = {}
    for e in expenses:
        by_date.setdefault(e[4], []).append(e)

    today_expenses = by_date.get(today_str, [])
    total_today    = sum(e[1] for e in today_expenses)
    total_all      = sum(e[1] for e in expenses)

    # ── 1. today's summary ───────────────────────────────────────────────────
    if total_today == 0:
        suggestions.append(("info", "No expenses recorded today — great start!"))
    else:
        suggestions.append(("info", f"Today's total: ₹{total_today:.2f}"))

    # ── 2. budget burn-rate ──────────────────────────────────────────────────
    if budget:
        day_of_month  = today.day
        days_in_month = 30
        days_left     = days_in_month - day_of_month + 1
        daily_burn    = total_all / day_of_month if day_of_month else 0
        projected     = daily_burn * days_in_month

        if projected > budget:
            runout_day = int(budget / daily_burn) if daily_burn else days_in_month
            suggestions.append(("danger",
                f"At this rate your budget runs out around day {runout_day}."))
        else:
            pct_used   = (total_all / budget) * 100
            pct_month  = (day_of_month / days_in_month) * 100
            if pct_used < pct_month - 10:
                suggestions.append(("success",
                    f"You've used {pct_used:.0f}% of budget with {pct_month:.0f}% of the month gone — well done!"))
            else:
                budget_left = budget - total_all
                suggestions.append(("info",
                    f"₹{budget_left:.2f} remaining for {days_left} days (~₹{budget_left/days_left:.0f}/day)."))

    # ── 3. spending velocity (monthly projection) ────────────────────────────
    if len(expenses) >= 3:
        dates = [parse_date(e[4]) for e in expenses if parse_date(e[4])]
        if dates:
            days_tracked = max((max(dates) - min(dates)).days + 1, 1)
            daily_avg    = total_all / days_tracked
            projected_30 = daily_avg * 30
            suggestions.append(("info",
                f"Spending pace: ₹{daily_avg:.0f}/day → ₹{projected_30:.0f} estimated this month."))
    else:
        suggestions.append(("info", "Add a few more expenses for monthly projections."))

    # ── 4. anomaly detection ─────────────────────────────────────────────────
    amounts = [e[1] for e in expenses]
    if len(amounts) >= 5:
        mean   = statistics.mean(amounts)
        stdev  = statistics.stdev(amounts)
        recent = expenses[0]  # most recent (already sorted DESC)
        if stdev > 0 and recent[1] > mean + 2 * stdev:
            suggestions.append(("warning",
                f"Your latest ₹{recent[1]:.0f} ({recent[2]}) is unusually high vs your avg ₹{mean:.0f}."))

    # ── 5. category balance ───────────────────────────────────────────────────
    if total_all > 0:
        cat_totals = {}
        for e in expenses:
            cat_totals[e[2]] = cat_totals.get(e[2], 0) + e[1]

        top_cat     = max(cat_totals, key=cat_totals.get)
        top_pct     = (cat_totals[top_cat] / total_all) * 100

        if top_pct > 70:
            suggestions.append(("warning",
                f"{top_cat} is {top_pct:.0f}% of all spending — heavily unbalanced."))
        elif len(cat_totals) >= 3:
            suggestions.append(("success",
                f"Spending spread across {len(cat_totals)} categories — nicely balanced."))

    # ── 6. savings streak (days under daily budget) ──────────────────────────
    if budget:
        daily_budget = budget / 30
        streak = 0
        for d in sorted(by_date.keys(), reverse=True):
            day_total = sum(e[1] for e in by_date[d])
            if day_total <= daily_budget:
                streak += 1
            else:
                break
        if streak >= 2:
            suggestions.append(("success",
                f"🔥 {streak}-day streak of staying under your daily budget!"))

    # ── 7. day-of-week pattern ────────────────────────────────────────────────
    if len(expenses) >= 10:
        dow_totals   = {}
        dow_counts   = {}
        for e in expenses:
            d = parse_date(e[4])
            if d:
                name = d.strftime('%A')
                dow_totals[name] = dow_totals.get(name, 0) + e[1]
                dow_counts[name] = dow_counts.get(name, 0) + 1

        dow_avgs = {k: dow_totals[k] / dow_counts[k] for k in dow_totals}
        heaviest = max(dow_avgs, key=dow_avgs.get)
        lightest = min(dow_avgs, key=dow_avgs.get)
        if dow_avgs[heaviest] > 1.5 * dow_avgs[lightest]:
            suggestions.append(("info",
                f"You tend to spend most on {heaviest}s and least on {lightest}s."))

    # ── 8. weekend vs weekday ────────────────────────────────────────────────
    if len(expenses) >= 7:
        wkend, wkday = [], []
        for e in expenses:
            d = parse_date(e[4])
            if d:
                (wkend if d.weekday() >= 5 else wkday).append(e[1])

        if wkend and wkday:
            avg_wkend = statistics.mean(wkend)
            avg_wkday = statistics.mean(wkday)
            if avg_wkend > avg_wkday * 1.3:
                suggestions.append(("warning",
                    f"Weekend avg ₹{avg_wkend:.0f} vs weekday ₹{avg_wkday:.0f} — weekends cost more."))
            elif avg_wkday > avg_wkend * 1.3:
                suggestions.append(("info",
                    f"You actually spend more on weekdays (₹{avg_wkday:.0f}) than weekends (₹{avg_wkend:.0f})."))

    # ── 9. week-over-week most improved ─────────────────────────────────────
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)

    this_week_cat = {}
    last_week_cat = {}
    for e in expenses:
        d = parse_date(e[4])
        if d:
            if d >= this_week_start:
                this_week_cat[e[2]] = this_week_cat.get(e[2], 0) + e[1]
            elif d >= last_week_start:
                last_week_cat[e[2]] = last_week_cat.get(e[2], 0) + e[1]

    if this_week_cat and last_week_cat:
        improvements = {}
        for cat in last_week_cat:
            if cat in this_week_cat:
                drop = last_week_cat[cat] - this_week_cat[cat]
                if drop > 0:
                    improvements[cat] = drop

        if improvements:
            best = max(improvements, key=improvements.get)
            suggestions.append(("success",
                f"Most improved: {best} is down ₹{improvements[best]:.0f} vs last week!"))

    # ── 10. contextual tip on latest entry ───────────────────────────────────
    if expenses:
        latest = expenses[0]
        cat, amt = latest[2], latest[1]
        tips = {
            'Food':     f"Tip: meal prepping 2x/week can cut food costs by ~30%.",
            'Travel':   f"Tip: booking transport a day ahead often saves 15–20%.",
            'Shopping': f"Tip: wait 24 hrs before non-essential purchases — reduces impulse buys.",
        }
        tip = tips.get(cat)
        if tip:
            suggestions.append(("info", tip))

    return suggestions


# =========================
# HOME PAGE
# =========================
@app.route('/')
def index():
    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute("SELECT * FROM expenses ORDER BY date DESC")
    expenses = c.fetchall()

    c.execute("SELECT amount FROM budget WHERE id=1")
    b = c.fetchone()
    budget = b[0] if b else None

    conn.close()

    total = sum([e[1] for e in expenses])
    remaining = budget - total if budget else None

    # Calculate category breakdown
    category_totals = {}
    for e in expenses:
        cat = e[2]
        category_totals[cat] = category_totals.get(cat, 0) + e[1]

    suggestions = get_suggestions(expenses, budget)

    return render_template_string(TEMPLATE,
                                  expenses=expenses,
                                  total=total,
                                  budget=budget,
                                  remaining=remaining,
                                  suggestions=suggestions,
                                  category_totals=category_totals)


# =========================
# ADD EXPENSE
# =========================
@app.route('/add', methods=['POST'])
def add():
    amount = float(request.form['amount'])
    category = request.form['category']

    if category == "Other":
        category = request.form['other_category']

    description = request.form['description']
    date = request.form['date'] or datetime.now().strftime('%Y-%m-%d')

    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute("INSERT INTO expenses (amount, category, description, date) VALUES (?, ?, ?, ?)",
              (amount, category, description, date))

    conn.commit()
    conn.close()

    return redirect('/')


# =========================
# DELETE
# =========================
@app.route('/delete/<int:id>')
def delete(id):
    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute("DELETE FROM expenses WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect('/')


# =========================
# RESET
# =========================
@app.route('/reset')
def reset():
    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute("DELETE FROM expenses")
    c.execute("DELETE FROM sqlite_sequence WHERE name='expenses'")

    conn.commit()
    conn.close()

    return redirect('/')


# =========================
# SET BUDGET
# =========================
@app.route('/budget', methods=['POST'])
def set_budget():
    amount = float(request.form['budget'])

    conn = sqlite3.connect('expenses.db')
    c = conn.cursor()

    c.execute("INSERT OR REPLACE INTO budget (id, amount) VALUES (1, ?)", (amount,))

    conn.commit()
    conn.close()

    return redirect('/')


# =========================
# HTML TEMPLATE
# =========================
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Expense Tracker</title>
    <link href="[fonts.googleapis.com](https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap)" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        /* Header */
        .header {
            text-align: center;
            padding: 30px 0;
            color: white;
        }

        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 8px;
            text-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }

        .header p {
            font-size: 1rem;
            opacity: 0.9;
        }

        /* Cards Grid */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }

        .card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 50px rgba(0,0,0,0.15);
        }

        .card-title {
            font-size: 0.85rem;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .card-title .icon {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
        }

        /* Stats Cards */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            position: relative;
            overflow: hidden;
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
        }

        .stat-card.total::before { background: linear-gradient(90deg, #667eea, #764ba2); }
        .stat-card.budget::before { background: linear-gradient(90deg, #10b981, #34d399); }
        .stat-card.remaining::before { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
        .stat-card.remaining.negative::before { background: linear-gradient(90deg, #ef4444, #f87171); }

        .stat-label {
            font-size: 0.8rem;
            font-weight: 500;
            color: #6b7280;
            margin-bottom: 4px;
        }

        .stat-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: #1f2937;
        }

        .stat-card.remaining.negative .stat-value {
            color: #ef4444;
        }

        /* Form Styles */
        .form-group {
            margin-bottom: 16px;
        }

        .form-label {
            display: block;
            font-size: 0.85rem;
            font-weight: 500;
            color: #374151;
            margin-bottom: 6px;
        }

        .form-input, .form-select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            font-size: 0.95rem;
            font-family: inherit;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
            background: #f9fafb;
        }

        .form-input:focus, .form-select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            background: white;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 12px 24px;
            border: none;
            border-radius: 10px;
            font-size: 0.95rem;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            width: 100%;
        }

        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
        }

        .btn-secondary {
            background: #f3f4f6;
            color: #374151;
        }

        .btn-secondary:hover {
            background: #e5e7eb;
        }

        .btn-danger {
            background: #fee2e2;
            color: #dc2626;
        }

        .btn-danger:hover {
            background: #fecaca;
        }

        /* Suggestions */
        .suggestion-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .suggestion-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            border-radius: 10px;
            font-size: 0.9rem;
        }

        .suggestion-item.info {
            background: #eff6ff;
            color: #1e40af;
        }

        .suggestion-item.warning {
            background: #fef3c7;
            color: #92400e;
        }

        .suggestion-item.success {
            background: #d1fae5;
            color: #065f46;
        }

        .suggestion-item.danger {
            background: #fee2e2;
            color: #991b1b;
        }

        .suggestion-icon {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.75rem;
            flex-shrink: 0;
        }

        .suggestion-item.info .suggestion-icon { background: #dbeafe; }
        .suggestion-item.warning .suggestion-icon { background: #fde68a; }
        .suggestion-item.success .suggestion-icon { background: #a7f3d0; }
        .suggestion-item.danger .suggestion-icon { background: #fecaca; }

        /* Category Breakdown */
        .category-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .category-item {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .category-icon {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
        }

        .category-icon.food { background: #fef3c7; }
        .category-icon.travel { background: #dbeafe; }
        .category-icon.shopping { background: #fce7f3; }
        .category-icon.other { background: #e5e7eb; }

        .category-info {
            flex: 1;
        }

        .category-name {
            font-weight: 600;
            color: #1f2937;
            font-size: 0.95rem;
        }

        .category-bar {
            height: 6px;
            background: #e5e7eb;
            border-radius: 3px;
            margin-top: 6px;
            overflow: hidden;
        }

        .category-bar-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s ease;
        }

        .category-bar-fill.food { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
        .category-bar-fill.travel { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
        .category-bar-fill.shopping { background: linear-gradient(90deg, #ec4899, #f472b6); }
        .category-bar-fill.other { background: linear-gradient(90deg, #6b7280, #9ca3af); }

        .category-amount {
            font-weight: 600;
            color: #1f2937;
            font-size: 0.95rem;
        }

        /* Expenses Table */
        .table-container {
            overflow-x: auto;
            margin-top: 8px;
        }

        .expenses-table {
            width: 100%;
            border-collapse: collapse;
        }

        .expenses-table th {
            text-align: left;
            padding: 12px 16px;
            font-size: 0.75rem;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #e5e7eb;
        }

        .expenses-table td {
            padding: 16px;
            border-bottom: 1px solid #f3f4f6;
            font-size: 0.9rem;
            color: #374151;
        }

        .expenses-table tr:hover {
            background: #f9fafb;
        }

        .expense-amount {
            font-weight: 600;
            color: #1f2937;
        }

        .expense-category {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
        }

        .expense-category.food { background: #fef3c7; color: #92400e; }
        .expense-category.travel { background: #dbeafe; color: #1e40af; }
        .expense-category.shopping { background: #fce7f3; color: #9d174d; }
        .expense-category.other { background: #f3f4f6; color: #374151; }

        .delete-btn {
            background: none;
            border: none;
            color: #9ca3af;
            cursor: pointer;
            padding: 8px;
            border-radius: 8px;
            transition: all 0.2s ease;
        }

        .delete-btn:hover {
            background: #fee2e2;
            color: #dc2626;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #6b7280;
        }

        .empty-state .icon {
            font-size: 3rem;
            margin-bottom: 16px;
        }

        .empty-state p {
            font-size: 0.95rem;
        }

        /* Footer Actions */
        .footer-actions {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-top: 20px;
            padding-bottom: 40px;
        }

        /* Animations */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .card, .stat-card {
            animation: fadeIn 0.4s ease;
        }

        /* Responsive */
        @media (max-width: 640px) {
            .header h1 {
                font-size: 1.75rem;
            }

            .form-row {
                grid-template-columns: 1fr;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }

            .expenses-table th:nth-child(4),
            .expenses-table td:nth-child(4) {
                display: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <h1>💰 Expense Tracker</h1>
            <p>Track your spending with AI-powered insights</p>
        </header>

        <!-- Stats Cards -->
        <div class="stats-grid">
            <div class="stat-card total">
                <div class="stat-label">Total Spent</div>
                <div class="stat-value">₹{{ "%.2f"|format(total) }}</div>
            </div>
            {% if budget %}
            <div class="stat-card budget">
                <div class="stat-label">Monthly Budget</div>
                <div class="stat-value">₹{{ "%.2f"|format(budget) }}</div>
            </div>
            <div class="stat-card remaining {% if remaining < 0 %}negative{% endif %}">
                <div class="stat-label">Remaining</div>
                <div class="stat-value">₹{{ "%.2f"|format(remaining) }}</div>
            </div>
            {% endif %}
        </div>

        <!-- Main Grid -->
        <div class="grid">
            <!-- Add Expense Card -->
            <div class="card">
                <div class="card-title">
                    <span class="icon" style="background: #eff6ff;">➕</span>
                    Add Expense
                </div>
                <form action="/add" method="post">
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Amount (₹)</label>
                            <input type="number" step="0.01" name="amount" class="form-input" placeholder="0.00" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Date</label>
                            <input type="date" name="date" class="form-input">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Category</label>
                        <select name="category" id="category" class="form-select" onchange="handleCategory()">
                            <option value="Food">🍔 Food</option>
                            <option value="Travel">✈️ Travel</option>
                            <option value="Shopping">🛍️ Shopping</option>
                            <option value="Other">📦 Other</option>
                        </select>
                    </div>
                    <div class="form-group" id="otherCategoryGroup" style="display: none;">
                        <label class="form-label">Custom Category</label>
                        <input type="text" name="other_category" id="otherInput" class="form-input" placeholder="Enter category name">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Description</label>
                        <input type="text" name="description" class="form-input" placeholder="What did you spend on?">
                    </div>
                    <button type="submit" class="btn btn-primary">Add Expense</button>
                </form>
            </div>

            <!-- Budget Card -->
            <div class="card">
                <div class="card-title">
                    <span class="icon" style="background: #d1fae5;">🎯</span>
                    Set Budget
                </div>
                <form action="/budget" method="post">
                    <div class="form-group">
                        <label class="form-label">Monthly Budget (₹)</label>
                        <input type="number" step="0.01" name="budget" class="form-input" placeholder="Enter your budget" value="{{ budget if budget else '' }}" required>
                    </div>
                    <button type="submit" class="btn btn-primary">Update Budget</button>
                </form>

                {% if category_totals %}
                <div style="margin-top: 24px;">
                    <div class="card-title" style="margin-bottom: 12px;">
                        <span class="icon" style="background: #fef3c7;">📊</span>
                        Spending by Category
                    </div>
                    <div class="category-list">
                        {% for cat, amount in category_totals.items() %}
                        <div class="category-item">
                            <div class="category-icon {{ cat.lower() if cat.lower() in ['food', 'travel', 'shopping'] else 'other' }}">
                                {% if cat == 'Food' %}🍔
                                {% elif cat == 'Travel' %}✈️
                                {% elif cat == 'Shopping' %}🛍️
                                {% else %}📦{% endif %}
                            </div>
                            <div class="category-info">
                                <div class="category-name">{{ cat }}</div>
                                <div class="category-bar">
                                    <div class="category-bar-fill {{ cat.lower() if cat.lower() in ['food', 'travel', 'shopping'] else 'other' }}" 
                                         style="width: {{ (amount / total * 100) if total > 0 else 0 }}%"></div>
                                </div>
                            </div>
                            <div class="category-amount">₹{{ "%.2f"|format(amount) }}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
            </div>

            <!-- AI Suggestions Card -->
            <div class="card">
                <div class="card-title">
                    <span class="icon" style="background: #ede9fe;">🤖</span>
                    AI Insights
                </div>
                <div class="suggestion-list">
                    {% for type, message in suggestions %}
                    <div class="suggestion-item {{ type }}">
                        <span class="suggestion-icon">
                            {% if type == 'info' %}💡
                            {% elif type == 'warning' %}⚠️
                            {% elif type == 'success' %}✅
                            {% elif type == 'danger' %}🚨{% endif %}
                        </span>
                        {{ message }}
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <!-- Expenses Table Card -->
        <div class="card">
            <div class="card-title">
                <span class="icon" style="background: #f3f4f6;">📋</span>
                Recent Expenses
            </div>
            {% if expenses %}
            <div class="table-container">
                <table class="expenses-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Amount</th>
                            <th>Category</th>
                            <th>Description</th>
                            <th>Date</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for e in expenses %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td class="expense-amount">₹{{ "%.2f"|format(e[1]) }}</td>
                            <td>
                                <span class="expense-category {{ e[2].lower() if e[2].lower() in ['food', 'travel', 'shopping'] else 'other' }}">
                                    {% if e[2] == 'Food' %}🍔
                                    {% elif e[2] == 'Travel' %}✈️
                                    {% elif e[2] == 'Shopping' %}🛍️
                                    {% else %}📦{% endif %}
                                    {{ e[2] }}
                                </span>
                            </td>
                            <td>{{ e[3] or '-' }}</td>
                            <td>{{ e[4] }}</td>
                            <td>
                                <a href="/delete/{{ e[0] }}" class="delete-btn" title="Delete">
                                    🗑️
                                </a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty-state">
                <div class="icon">📭</div>
                <p>No expenses yet. Add your first expense above!</p>
            </div>
            {% endif %}
        </div>

        <!-- Footer Actions -->
        <div class="footer-actions">
            <a href="/reset" class="btn btn-danger" onclick="return confirm('Are you sure you want to reset all data?')">
                🔄 Reset All Data
            </a>
        </div>
    </div>

    <script>
        function handleCategory() {
            const cat = document.getElementById("category").value;
            const group = document.getElementById("otherCategoryGroup");
            const input = document.getElementById("otherInput");

            if (cat === "Other") {
                group.style.display = "block";
                input.required = true;
            } else {
                group.style.display = "none";
                input.required = false;
            }
        }
    </script>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(debug=True)
