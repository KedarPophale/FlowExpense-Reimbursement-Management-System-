# app.py - Main Flask Application
import os
import json
import uuid
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.secret_key = 'reimbursement_secret_key_2024'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== Data Storage (JSON Files) ====================
DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)

def load_data(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_data(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# ==================== Helper Functions ====================
def get_country_currency(country_code='IN'):
    """Fetch currency from API"""
    try:
        response = requests.get('https://restcountries.com/v3.1/all?fields=name,currencies', timeout=5)
        if response.status_code == 200:
            countries = response.json()
            for country in countries:
                if country_code.upper() in country.get('name', {}).get('common', ''):
                    curr = country.get('currencies', {})
                    if curr:
                        return list(curr.keys())[0], list(curr.values())[0].get('symbol', '$')
        return 'USD', '$'
    except:
        return 'USD', '$'

def get_exchange_rate(base_currency, target_currency):
    """Fetch exchange rate"""
    try:
        response = requests.get(f'https://api.exchangerate-api.com/v4/latest/{base_currency}', timeout=5)
        if response.status_code == 200:
            rates = response.json().get('rates', {})
            return rates.get(target_currency, 1)
        return 1
    except:
        return 1

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please login first', 'error')
                return redirect(url_for('login'))
            user = get_user_by_id(session['user_id'])
            if role and user and user.get('role') != role and user.get('role') != 'Admin':
                flash('Access denied', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_user_by_id(user_id):
    users = load_data('users.json')
    return users.get(user_id)

def get_company():
    companies = load_data('companies.json')
    return list(companies.values())[0] if companies else None

# ==================== Authentication Routes ====================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        users = load_data('users.json')
        for user_id, user in users.items():
            if user.get('email') == email and check_password_hash(user.get('password', ''), password):
                session['user_id'] = user_id
                session['user_name'] = user.get('name')
                session['user_role'] = user.get('role')
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        country = request.form.get('country', 'India')
        
        companies = load_data('companies.json')
        users = load_data('users.json')
        
        if not companies:
            # Auto-create company on first signup
            currency_code, currency_symbol = get_country_currency(country[:2])
            company_id = str(uuid.uuid4())
            companies[company_id] = {
                'id': company_id,
                'name': f"{name}'s Company",
                'country': country,
                'currency': currency_code,
                'currency_symbol': currency_symbol,
                'created_at': datetime.now().isoformat()
            }
            save_data('companies.json', companies)
        
        # Create Admin user
        user_id = str(uuid.uuid4())
        users[user_id] = {
            'id': user_id,
            'name': name,
            'email': email,
            'password': generate_password_hash(password),
            'role': 'Admin',
            'company_id': list(companies.keys())[0] if companies else None,
            'manager_id': None,
            'created_at': datetime.now().isoformat()
        }
        save_data('users.json', users)
        
        # Initialize approval rules
        rules = load_data('approval_rules.json')
        if not rules:
            rules['default'] = {
                'type': 'sequential',
                'approvers': [],
                'conditional': None
            }
            save_data('approval_rules.json', rules)
        
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

# ==================== Dashboard ====================
@app.route('/dashboard')
@login_required()
def dashboard():
    user = get_user_by_id(session['user_id'])
    company = get_company()
    expenses = load_data('expenses.json')
    
    user_expenses = []
    pending_approvals = []
    
    if user.get('role') == 'Admin':
        user_expenses = [e for e in expenses.values() if e.get('user_id') == session['user_id']]
        pending_approvals = [e for e in expenses.values() if e.get('status') == 'pending']
    elif user.get('role') == 'Manager':
        user_expenses = [e for e in expenses.values() if e.get('user_id') == session['user_id']]
        # Get team expenses
        users = load_data('users.json')
        team_ids = [uid for uid, u in users.items() if u.get('manager_id') == session['user_id']]
        pending_approvals = [e for e in expenses.values() if e.get('user_id') in team_ids and e.get('status') == 'pending']
    else:  # Employee
        user_expenses = [e for e in expenses.values() if e.get('user_id') == session['user_id']]
    
    stats = {
        'total': len(user_expenses),
        'approved': len([e for e in user_expenses if e.get('status') == 'approved']),
        'rejected': len([e for e in user_expenses if e.get('status') == 'rejected']),
        'pending': len([e for e in user_expenses if e.get('status') == 'pending']),
        'pending_approvals': len(pending_approvals)
    }
    
    return render_template('dashboard.html', user=user, company=company, stats=stats, expenses=user_expenses[:5])

# ==================== Expense Management ====================
@app.route('/expenses/submit', methods=['GET', 'POST'])
@login_required()
def submit_expense():
    user = get_user_by_id(session['user_id'])
    company = get_company()
    
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        category = request.form.get('category')
        description = request.form.get('description')
        expense_date = request.form.get('expense_date')
        receipt_file = request.files.get('receipt')
        
        receipt_path = None
        if receipt_file and receipt_file.filename:
            filename = secure_filename(f"{uuid.uuid4()}_{receipt_file.filename}")
            receipt_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            receipt_file.save(receipt_path)
            receipt_path = filename
        
        expense_id = str(uuid.uuid4())
        expenses = load_data('expenses.json')
        
        # Get manager for approval
        users = load_data('users.json')
        manager_id = None
        if user.get('manager_id'):
            manager_id = user.get('manager_id')
        else:
            # Find manager for this employee
            for uid, u in users.items():
                if u.get('role') == 'Manager' and u.get('company_id') == user.get('company_id'):
                    manager_id = uid
                    break
        
        expenses[expense_id] = {
            'id': expense_id,
            'user_id': session['user_id'],
            'user_name': user.get('name'),
            'amount': amount,
            'original_currency': company.get('currency', 'USD'),
            'category': category,
            'description': description,
            'expense_date': expense_date,
            'submitted_at': datetime.now().isoformat(),
            'status': 'pending',
            'current_approver': manager_id,
            'approval_history': [],
            'receipt_path': receipt_path,
            'comments': []
        }
        save_data('expenses.json', expenses)
        
        flash('Expense submitted successfully!', 'success')
        return redirect(url_for('view_expenses'))
    
    return render_template('submit_expense.html', user=user, company=company)

@app.route('/expenses')
@login_required()
def view_expenses():
    user = get_user_by_id(session['user_id'])
    expenses = load_data('expenses.json')
    company = get_company()
    
    if user.get('role') == 'Admin':
        user_expenses = list(expenses.values())
    elif user.get('role') == 'Manager':
        users = load_data('users.json')
        team_ids = [uid for uid, u in users.items() if u.get('manager_id') == session['user_id']]
        user_expenses = [e for e in expenses.values() if e.get('user_id') in team_ids or e.get('user_id') == session['user_id']]
    else:
        user_expenses = [e for e in expenses.values() if e.get('user_id') == session['user_id']]
    
    user_expenses.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
    return render_template('expenses.html', expenses=user_expenses, user=user, company=company)

# ==================== Approval Management ====================
@app.route('/approvals')
@login_required()
def approvals():
    user = get_user_by_id(session['user_id'])
    expenses = load_data('expenses.json')
    company = get_company()
    
    pending = []
    if user.get('role') == 'Admin':
        pending = [e for e in expenses.values() if e.get('status') == 'pending']
    elif user.get('role') == 'Manager':
        users = load_data('users.json')
        team_ids = [uid for uid, u in users.items() if u.get('manager_id') == session['user_id']]
        pending = [e for e in expenses.values() if e.get('status') == 'pending' and e.get('user_id') in team_ids]
        # Also expenses directly assigned to this manager
        pending += [e for e in expenses.values() if e.get('current_approver') == session['user_id'] and e.get('status') == 'pending']
        pending = list({e['id']: e for e in pending}.values())
    
    return render_template('approvals.html', expenses=pending, user=user, company=company)

@app.route('/approvals/<expense_id>/action', methods=['POST'])
@login_required()
def approval_action(expense_id):
    user = get_user_by_id(session['user_id'])
    expenses = load_data('expenses.json')
    expense = expenses.get(expense_id)
    
    if not expense:
        flash('Expense not found', 'error')
        return redirect(url_for('approvals'))
    
    action = request.form.get('action')
    comment = request.form.get('comment', '')
    
    if action == 'approve':
        expense['status'] = 'approved'
        expense['approved_by'] = session['user_id']
        expense['approved_at'] = datetime.now().isoformat()
        expense['approval_history'].append({
            'approver_id': session['user_id'],
            'approver_name': user.get('name'),
            'action': 'approved',
            'comment': comment,
            'timestamp': datetime.now().isoformat()
        })
        flash('Expense approved!', 'success')
    elif action == 'reject':
        expense['status'] = 'rejected'
        expense['rejected_by'] = session['user_id']
        expense['rejected_at'] = datetime.now().isoformat()
        expense['approval_history'].append({
            'approver_id': session['user_id'],
            'approver_name': user.get('name'),
            'action': 'rejected',
            'comment': comment,
            'timestamp': datetime.now().isoformat()
        })
        flash('Expense rejected!', 'warning')
    
    expenses[expense_id] = expense
    save_data('expenses.json', expenses)
    
    return redirect(url_for('approvals'))

# ==================== User Management (Admin) ====================
@app.route('/admin/users')
@login_required(role='Admin')
def manage_users():
    users = load_data('users.json')
    company = get_company()
    return render_template('manage_users.html', users=users.values(), company=company)

@app.route('/admin/users/create', methods=['GET', 'POST'])
@login_required(role='Admin')
def create_user():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        manager_id = request.form.get('manager_id')
        
        users = load_data('users.json')
        company = get_company()
        
        user_id = str(uuid.uuid4())
        users[user_id] = {
            'id': user_id,
            'name': name,
            'email': email,
            'password': generate_password_hash(password),
            'role': role,
            'company_id': company.get('id'),
            'manager_id': manager_id if manager_id else None,
            'created_at': datetime.now().isoformat()
        }
        save_data('users.json', users)
        flash('User created successfully!', 'success')
        return redirect(url_for('manage_users'))
    
    users = load_data('users.json')
    managers = [u for u in users.values() if u.get('role') == 'Manager']
    return render_template('create_user.html', managers=managers)

@app.route('/admin/users/<user_id>/delete', methods=['POST'])
@login_required(role='Admin')
def delete_user(user_id):
    if user_id == session['user_id']:
        flash('Cannot delete yourself', 'error')
        return redirect(url_for('manage_users'))
    
    users = load_data('users.json')
    if user_id in users:
        del users[user_id]
        save_data('users.json', users)
        flash('User deleted', 'success')
    return redirect(url_for('manage_users'))

# ==================== Approval Rules (Admin) ====================
@app.route('/admin/rules', methods=['GET', 'POST'])
@login_required(role='Admin')
def approval_rules():
    rules = load_data('approval_rules.json')
    users = load_data('users.json')
    
    if request.method == 'POST':
        rule_type = request.form.get('rule_type')
        approvers = request.form.getlist('approvers')
        conditional_type = request.form.get('conditional_type')
        threshold = request.form.get('threshold')
        
        rules['default'] = {
            'type': rule_type,
            'approvers': approvers,
            'conditional': {
                'type': conditional_type,
                'threshold': int(threshold) if threshold else None,
                'special_approver': request.form.get('special_approver')
            } if conditional_type else None
        }
        save_data('approval_rules.json', rules)
        flash('Approval rules updated!', 'success')
        return redirect(url_for('approval_rules'))
    
    managers = [u for u in users.values() if u.get('role') == 'Manager']
    directors = [u for u in users.values() if u.get('role') == 'Admin']
    return render_template('approval_rules.html', rules=rules.get('default', {}), managers=managers, directors=directors)

# ==================== OCR Receipt Scanning ====================
@app.route('/scan-receipt', methods=['POST'])
@login_required()
def scan_receipt():
    """Simulate OCR - In production, integrate with actual OCR service"""
    if 'receipt_image' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['receipt_image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Simulated OCR extraction
    import random
    categories = ['Meals', 'Travel', 'Office Supplies', 'Transport', 'Accommodation']
    merchants = ['Starbucks', 'Uber', 'Amazon', 'Marriott', 'Local Restaurant']
    
    extracted = {
        'amount': round(random.uniform(10, 500), 2),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'merchant': random.choice(merchants),
        'category': random.choice(categories),
        'description': f"Expense at {random.choice(merchants)}"
    }
    
    return jsonify(extracted)

# ==================== Currency Conversion ====================
@app.route('/api/convert', methods=['GET'])
def convert_currency():
    amount = float(request.args.get('amount', 1))
    from_curr = request.args.get('from', 'USD')
    to_curr = request.args.get('to', 'USD')
    
    rate = get_exchange_rate(from_curr, to_curr)
    converted = amount * rate
    
    return jsonify({
        'original': amount,
        'from': from_curr,
        'to': to_curr,
        'rate': rate,
        'converted': round(converted, 2)
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)