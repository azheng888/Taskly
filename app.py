from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os
from pathlib import Path

app = Flask(__name__)
instance_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance')
os.makedirs(instance_path, exist_ok=True)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secretdevkeyplaceholder')
basedir = os.path.abspath(os.path.dirname(__file__))

database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "tasks.db")}'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    tasks = db.relationship('Task', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return '<Task %r>' % self.id

with app.app_context():
    db.create_all()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username').strip()
        email = request.form.get('email').strip()
        password = request.form.get('password')
        
        if not username or not email or not password:
            flash('All fields are required', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        user = User(username=username, email=email)
        user.set_password(password)
        
        try:
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            flash('Error creating account', 'error')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/', methods=['POST', 'GET'])
@login_required
def index():
    if request.method == 'POST':
        task_content = request.form['content'].strip()
        due_date_str = request.form.get('due_date', '').strip()
        
        if not task_content:
            flash('Task cannot be empty', 'error')
        elif len(task_content) > 200:
            flash('Task is too long (max 200 characters)', 'error')
        else:
            new_task = Task(content=task_content, user_id=current_user.id)
            
            if due_date_str:
                try:
                    new_task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
                except ValueError:
                    flash('Invalid date format', 'error')
                    return redirect('/')
                
            try:
                db.session.add(new_task)
                db.session.commit()
                flash('Task added successfully!', 'success')
                
            except Exception as e:
                print (e)
                flash('Error adding task. Please try again.', 'error')
        
        return redirect('/')

    else:
        filter_type = request.args.get('filter', 'all')
        sort_by = request.args.get('sort', 'date')
        search_query = request.args.get('search', '').strip()

        if filter_type == 'completed':
            query = Task.query.filter_by(completed=True, user_id=current_user.id)
        elif filter_type == 'active':
            query = Task.query.filter_by(completed=False, user_id=current_user.id)
        else:
            query = Task.query.filter_by(user_id=current_user.id)

        if search_query:
            query = query.filter(Task.content.ilike(f'%{search_query}%'))

        if sort_by == 'date_desc':
            tasks = query.order_by(Task.date_created.desc()).all()
        elif sort_by == 'date_asc':
            tasks = query.order_by(Task.date_created.asc()).all()
        elif sort_by == 'alpha':
            tasks = query.order_by(Task.content).all()
        else:
            tasks = query.order_by(Task.date_created.desc()).all()
        
        return render_template('index.html', tasks=tasks, filter=filter_type, sort=sort_by, search=search_query, today=date.today())

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    task_to_delete = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    try:
        db.session.delete(task_to_delete)
        db.session.commit()
        flash('Task deleted successfully!', 'success')
    except Exception as e:
        flash('Error deleting task. Please try again.', 'error')
    
    return redirect('/')

@app.route('/update/<int:id>', methods=['GET', 'POST'])
@login_required
def update(id):
    task = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        task_content = request.form['content'].strip()
        due_date_str = request.form.get('due_date', '').strip()

        if not task_content:
            flash('Task cannot be empty', 'error')
            return render_template('update.html', task=task)
        elif len(task_content) > 200:
            flash('Task is too long (max 200 characters)', 'error')
            return render_template('update.html', task=task)

        task.content = task_content

        if due_date_str:
            try:
                task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format', 'error')
                return render_template('update.html', task=task)
        else:
            task.due_date = None

        try:
            db.session.commit()
            flash('Task updated successfully!', 'success')
            return redirect('/')
        except:
            flash('Error updating task. Please try again.', 'error')
            return render_template('update.html', task=task)
    
    return render_template('update.html', task=task)

@app.route('/complete/<int:id>')
@login_required
def complete(id):
    task = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    task.completed = not task.completed
    
    try:
        db.session.commit()
        status = "completed" if task.completed else "marked as incomplete"
        flash(f'Task {status}!', 'success')
    except Exception as e:
        flash('Error updating task status.', 'error')

    return redirect('/')

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)