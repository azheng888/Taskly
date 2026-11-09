import csv
import io
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

from flask import (Flask, abort, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case, func, inspect, or_, text
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-only-insecure-key'
if 'SECRET_KEY' not in os.environ and os.environ.get('DATABASE_URL'):
    app.logger.warning('SECRET_KEY is not set; sessions are not secure in production.')

database_url = os.environ.get('DATABASE_URL')
if os.environ.get('TASKLY_DATABASE_URI'):  # explicit override, used by the tests
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['TASKLY_DATABASE_URI']
elif database_url:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(instance_path, "tasks.db")}'

app.config.update(
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
)
if os.environ.get('DATABASE_URL'):
    app.config.update(SESSION_COOKIE_SECURE=True, REMEMBER_COOKIE_SECURE=True)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to continue.'
login_manager.login_message_category = 'info'

MAX_TASK_LENGTH = 200
MAX_NOTES_LENGTH = 2000
MIN_PASSWORD_LENGTH = 8
VALID_PRIORITIES = ('high', 'medium', 'low')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,80}$')

VIEWS = {
    'all': 'All',
    'today': 'Today',
    'upcoming': 'Upcoming',
    'overdue': 'Overdue',
    'completed': 'Done',
}
SORTS = {
    'smart': 'Smart order',
    'due': 'Due date',
    'priority': 'Priority',
    'newest': 'Newest',
    'oldest': 'Oldest',
    'alpha': 'A → Z',
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    tasks = db.relationship('Task', backref='owner', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(MAX_TASK_LENGTH), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    date_created = db.Column(db.DateTime, default=utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    priority = db.Column(db.String(10), nullable=False, default='medium')

    def __repr__(self):
        return f'<Task {self.id}>'

    def due_status(self, today):
        """Return 'overdue', 'today', 'soon' (within 7 days), 'later' or None."""
        if not self.due_date or self.completed:
            return None
        d = self.due_date.date()
        if d < today:
            return 'overdue'
        if d == today:
            return 'today'
        if d <= today + timedelta(days=7):
            return 'soon'
        return 'later'

    def to_dict(self):
        return {
            'id': self.id,
            'content': self.content,
            'notes': self.notes or '',
            'completed': self.completed,
            'priority': self.priority,
            'due_date': self.due_date.strftime('%Y-%m-%d') if self.due_date else None,
        }


# Columns added after the first release. db.create_all() never alters existing
# tables, so add any that are missing (works on SQLite and PostgreSQL).
LATE_COLUMNS = {
    'task': {
        'priority': "VARCHAR(10) NOT NULL DEFAULT 'medium'",
        'notes': 'TEXT',
        'completed_at': 'TIMESTAMP',
    },
}


def ensure_schema():
    db.create_all()
    inspector = inspect(db.engine)
    with db.engine.begin() as conn:
        for table, columns in LATE_COLUMNS.items():
            existing = {c['name'] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}'))
                    app.logger.info('Added column %s.%s', table, name)


with app.app_context():
    ensure_schema()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def csrf_token():
    token = session.get('_csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf'] = token
    return token


@app.before_request
def check_csrf():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not app.config.get('TESTING_DISABLE_CSRF'):
        sent = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
        expected = session.get('_csrf', '')
        if not expected or not secrets.compare_digest(sent, expected):
            if wants_json():
                return jsonify(error='Your session expired. Refresh the page and try again.'), 400
            flash('Your session expired. Please try again.', 'error')
            return redirect(request.referrer if is_safe_url(request.referrer) else url_for('index'))


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    return response


def is_safe_url(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target if '://' in target else request.host_url.rstrip('/') + '/' + target.lstrip('/'))
    return test.scheme in ('http', 'https') and ref.netloc == test.netloc and not target.startswith('//')


def wants_json():
    return request.headers.get('Accept', '').startswith('application/json')


# ---------------------------------------------------------------------------
# Time zone handling: the browser stores its IANA zone in a cookie so that
# "today" and "overdue" match the user's clock rather than the server's.
# ---------------------------------------------------------------------------

def user_now():
    tz_name = request.cookies.get('tz', '')
    if ZoneInfo and tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    return datetime.now()


def user_today():
    return user_now().date()


def to_local(value):
    """Convert a naive UTC timestamp to the user's time zone."""
    if value is None:
        return None
    tz = user_now().tzinfo
    if tz is None:
        return value
    return value.replace(tzinfo=timezone.utc).astimezone(tz)


def greeting():
    hour = user_now().hour
    if hour < 5:
        return 'Good evening'
    if hour < 12:
        return 'Good morning'
    if hour < 18:
        return 'Good afternoon'
    return 'Good evening'


@app.context_processor
def inject_globals():
    return dict(csrf_token=csrf_token, current_user=current_user, VIEWS=VIEWS, SORTS=SORTS)


# ---------------------------------------------------------------------------
# Form parsing
# ---------------------------------------------------------------------------

def parse_priority(value):
    p = (value or 'medium').strip().lower()
    return p if p in VALID_PRIORITIES else 'medium'


def parse_task_form(form):
    """Validate task fields. Returns (data, error)."""
    content = (form.get('content') or '').strip()
    notes = (form.get('notes') or '').strip()
    due_str = (form.get('due_date') or '').strip()

    if not content:
        return None, 'Task cannot be empty.'
    if len(content) > MAX_TASK_LENGTH:
        return None, f'Task is too long (max {MAX_TASK_LENGTH} characters).'
    if len(notes) > MAX_NOTES_LENGTH:
        return None, f'Notes are too long (max {MAX_NOTES_LENGTH} characters).'

    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str, '%Y-%m-%d')
        except ValueError:
            return None, 'Invalid due date.'

    return {
        'content': content,
        'notes': notes or None,
        'due_date': due_date,
        'priority': parse_priority(form.get('priority')),
    }, None


def list_url(**overrides):
    """URL for the task list that keeps the current view, sort and search."""
    args = {
        'view': request.args.get('view', 'all'),
        'sort': request.args.get('sort', 'smart'),
        'q': request.args.get('q', ''),
    }
    args.update(overrides)
    args = {k: v for k, v in args.items() if v and not (k == 'view' and v == 'all') and not (k == 'sort' and v == 'smart')}
    return url_for('index', **args)


def due_label(task, today):
    if not task.due_date:
        return ''
    d = task.due_date.date()
    delta = (d - today).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Tomorrow'
    if delta == -1:
        return 'Yesterday'
    if 1 < delta < 7:
        return d.strftime('%A')
    fmt = '%b %-d' if d.year == today.year else '%b %-d, %Y'
    try:
        return d.strftime(fmt)
    except ValueError:  # Windows has no %-d
        return d.strftime(fmt.replace('%-d', '%d'))


app.jinja_env.globals.update(list_url=list_url, due_label=due_label, to_local=to_local)


def back_to_list():
    nxt = request.form.get('next')
    if nxt and is_safe_url(nxt):
        return redirect(nxt)
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = {}
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        form = {'username': username, 'email': email}

        error = None
        if not username or not email or not password:
            error = 'All fields are required.'
        elif not USERNAME_RE.match(username):
            error = 'Usernames are 3–80 characters: letters, numbers, dots, dashes or underscores.'
        elif not EMAIL_RE.match(email):
            error = 'Enter a valid email address.'
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'
        elif User.query.filter(func.lower(User.username) == username.lower()).first():
            error = 'That username is taken.'
        elif User.query.filter(func.lower(User.email) == email).first():
            error = 'That email is already registered.'

        if error:
            flash(error, 'error')
            return render_template('register.html', form=form), 400

        user = User(username=username, email=email)
        user.set_password(password)
        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Error creating account')
            flash('Something went wrong creating your account. Please try again.', 'error')
            return render_template('register.html', form=form), 500

        login_user(user, remember=True)
        flash(f'Welcome to Taskly, {user.username}.', 'success')
        return redirect(url_for('index'))

    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    identifier = ''
    if request.method == 'POST':
        identifier = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        remember = bool(request.form.get('remember'))

        user = User.query.filter(or_(
            func.lower(User.username) == identifier.lower(),
            func.lower(User.email) == identifier.lower(),
        )).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page if is_safe_url(next_page) else url_for('index'))

        flash('Incorrect username or password.', 'error')
        return render_template('login.html', identifier=identifier), 401

    return render_template('login.html', identifier=identifier)


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('You have been signed out.', 'success')
    return redirect(url_for('login'))


@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    if request.method == 'POST':
        action = request.form.get('action')
        password = request.form.get('current_password') or ''

        if not current_user.check_password(password):
            flash('Your current password is incorrect.', 'error')
            return render_template('account.html'), 400

        if action == 'change_password':
            new = request.form.get('new_password') or ''
            if len(new) < MIN_PASSWORD_LENGTH:
                flash(f'New password must be at least {MIN_PASSWORD_LENGTH} characters.', 'error')
                return render_template('account.html'), 400
            current_user.set_password(new)
            db.session.commit()
            flash('Password updated.', 'success')
            return redirect(url_for('account'))

        if action == 'delete_account':
            user = db.session.get(User, current_user.id)
            logout_user()
            db.session.delete(user)
            db.session.commit()
            flash('Your account and tasks have been deleted.', 'success')
            return redirect(url_for('register'))

        abort(400)

    stats = task_stats(current_user.id, user_today())
    return render_template('account.html', stats=stats)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def task_stats(user_id, today):
    tasks = Task.query.filter_by(user_id=user_id).all()
    active = [t for t in tasks if not t.completed]
    done = len(tasks) - len(active)
    week_ago = utcnow() - timedelta(days=7)
    return {
        'total': len(tasks),
        'active': len(active),
        'completed': done,
        'today': sum(1 for t in active if t.due_status(today) == 'today'),
        'overdue': sum(1 for t in active if t.due_status(today) == 'overdue'),
        'upcoming': sum(1 for t in active if t.due_status(today) in ('soon', 'later')),
        'done_this_week': sum(1 for t in tasks if t.completed and t.completed_at and t.completed_at >= week_ago),
        'percent': round(done / len(tasks) * 100) if tasks else 0,
    }


@app.route('/', methods=['GET'])
@login_required
def index():
    today = user_today()
    view = request.args.get('view', 'all')
    if view not in VIEWS:
        view = 'all'
    sort = request.args.get('sort', 'smart')
    if sort not in SORTS:
        sort = 'smart'
    q = request.args.get('q', '').strip()

    query = Task.query.filter_by(user_id=current_user.id)
    start_of_today = datetime.combine(today, datetime.min.time())
    start_of_tomorrow = start_of_today + timedelta(days=1)

    if view == 'today':
        query = query.filter(Task.completed.is_(False), Task.due_date < start_of_tomorrow)
    elif view == 'upcoming':
        query = query.filter(Task.completed.is_(False), Task.due_date >= start_of_tomorrow)
    elif view == 'overdue':
        query = query.filter(Task.completed.is_(False), Task.due_date < start_of_today)
    elif view == 'completed':
        query = query.filter(Task.completed.is_(True))

    if q:
        like = f'%{q}%'
        query = query.filter(or_(Task.content.ilike(like), Task.notes.ilike(like)))

    priority_rank = case(
        (Task.priority == 'high', 1),
        (Task.priority == 'medium', 2),
        (Task.priority == 'low', 3),
        else_=2,
    )
    no_due_last = case((Task.due_date.is_(None), 1), else_=0)

    if sort == 'due':
        order = [no_due_last, Task.due_date.asc(), priority_rank]
    elif sort == 'priority':
        order = [priority_rank, no_due_last, Task.due_date.asc()]
    elif sort == 'newest':
        order = [Task.date_created.desc()]
    elif sort == 'oldest':
        order = [Task.date_created.asc()]
    elif sort == 'alpha':
        order = [func.lower(Task.content)]
    else:  # smart: open tasks first, then by due date, then priority
        order = [Task.completed.asc(), no_due_last, Task.due_date.asc(), priority_rank, Task.date_created.desc()]

    tasks = query.order_by(*order, Task.id.desc()).all()

    return render_template(
        'index.html',
        tasks=tasks,
        view=view,
        sort=sort,
        q=q,
        today=today,
        stats=task_stats(current_user.id, today),
        greeting=greeting(),
        max_length=MAX_TASK_LENGTH,
    )


@app.route('/tasks', methods=['POST'])
@login_required
def create_task():
    data, error = parse_task_form(request.form)
    if error:
        flash(error, 'error')
        return back_to_list()

    task = Task(user_id=current_user.id, **data)
    try:
        db.session.add(task)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Error adding task')
        flash('Could not add the task. Please try again.', 'error')
        return back_to_list()

    flash('Task added.', 'success')
    return back_to_list()


@app.route('/tasks/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def update(id):
    task = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        data, error = parse_task_form(request.form)
        if error:
            flash(error, 'error')
            return render_template('update.html', task=task, form=request.form), 400
        for key, value in data.items():
            setattr(task, key, value)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Error updating task')
            flash('Could not save the task. Please try again.', 'error')
            return render_template('update.html', task=task, form=request.form), 500
        flash('Task saved.', 'success')
        return back_to_list()

    return render_template('update.html', task=task, form=None)


@app.route('/tasks/<int:id>/toggle', methods=['POST'])
@login_required
def toggle(id):
    task = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    task.completed = not task.completed
    task.completed_at = utcnow() if task.completed else None
    db.session.commit()

    if wants_json():
        return jsonify(task=task.to_dict(), stats=task_stats(current_user.id, user_today()))
    return back_to_list()


@app.route('/tasks/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    task = Task.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(task)
    db.session.commit()

    if wants_json():
        return jsonify(ok=True, stats=task_stats(current_user.id, user_today()))
    flash('Task deleted.', 'success')
    return back_to_list()


@app.route('/tasks/clear-completed', methods=['POST'])
@login_required
def clear_completed():
    count = Task.query.filter_by(user_id=current_user.id, completed=True).delete()
    db.session.commit()
    flash(f'Cleared {count} completed task{"s" if count != 1 else ""}.' if count else 'Nothing to clear.', 'success')
    return back_to_list()


def csv_safe(value):
    """Stop spreadsheet apps from evaluating cell text as a formula."""
    value = '' if value is None else str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


@app.route('/export')
@login_required
def export():
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.date_created.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Task', 'Notes', 'Priority', 'Status', 'Created', 'Due date', 'Completed'])
    for task in tasks:
        writer.writerow([
            csv_safe(task.content),
            csv_safe(task.notes),
            task.priority.capitalize(),
            'Completed' if task.completed else 'Active',
            task.date_created.strftime('%Y-%m-%d') if task.date_created else '',
            task.due_date.strftime('%Y-%m-%d') if task.due_date else '',
            task.completed_at.strftime('%Y-%m-%d') if task.completed_at else '',
        ])
    response = make_response(output.getvalue())
    filename = f'taskly-{user_today().isoformat()}.csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return response


# Old URLs from the previous version, kept so bookmarks still work.
@app.route('/update/<int:id>')
@login_required
def legacy_update(id):
    return redirect(url_for('update', id=id))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, title='Nothing here',
                           message="That page doesn't exist, or the task was removed."), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return render_template('error.html', code=405, title='Not allowed',
                           message='That action needs to come from a button in the app.'), 405


@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template('error.html', code=500, title='Something broke',
                           message='An unexpected error occurred. Please try again.'), 500


if __name__ == '__main__':
    app.run(debug=True)
