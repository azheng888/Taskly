import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

_db_fd, _db_path = tempfile.mkstemp(suffix='.db')
os.environ['TASKLY_DATABASE_URI'] = f'sqlite:///{_db_path}'
os.environ.pop('DATABASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

import app as taskly  # noqa: E402
from app import Task, User, db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    with taskly.app.app_context():
        db.drop_all()
        taskly.ensure_schema()
    yield


@pytest.fixture
def client():
    taskly.app.config['TESTING'] = True
    return taskly.app.test_client()


def token(client, path='/login'):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def register(client, username='alice', email='alice@example.com', password='password123'):
    return client.post('/register', data={
        'csrf_token': token(client, '/register'),
        'username': username, 'email': email, 'password': password,
    })


@pytest.fixture
def auth(client):
    register(client)
    return client


def post(client, path, **data):
    data['csrf_token'] = token(client, '/')
    return client.post(path, data=data)


def tasks():
    with taskly.app.app_context():
        return Task.query.order_by(Task.id).all()


# --------------------------------------------------------------------- auth

def test_register_logs_in_and_redirects(client):
    res = register(client)
    assert res.status_code == 302 and res.headers['Location'].endswith('/')
    assert client.get('/').status_code == 200


def test_register_rejects_short_password_and_duplicates(client):
    assert register(client, password='short').status_code == 400
    register(client)
    client.post('/logout', data={'csrf_token': token(client, '/')})
    assert register(client, username='ALICE', email='other@example.com').status_code == 400
    assert register(client, username='bob', email='Alice@Example.com').status_code == 400


def test_login_with_email_and_bad_password(client):
    register(client)
    client.post('/logout', data={'csrf_token': token(client, '/')})
    bad = client.post('/login', data={'csrf_token': token(client), 'username': 'alice', 'password': 'nope'})
    assert bad.status_code == 401
    ok = client.post('/login', data={'csrf_token': token(client), 'username': 'alice@example.com', 'password': 'password123'})
    assert ok.status_code == 302


def test_login_ignores_external_next(client):
    register(client)
    client.post('/logout', data={'csrf_token': token(client, '/')})
    res = client.post('/login?next=https://evil.example/', data={
        'csrf_token': token(client), 'username': 'alice', 'password': 'password123'})
    assert res.headers['Location'] == '/'


def test_pages_require_login(client):
    assert client.get('/').status_code == 302
    assert client.get('/export').status_code == 302


# --------------------------------------------------------------------- csrf

def test_post_without_csrf_is_rejected(auth):
    auth.post('/tasks', data={'content': 'sneaky'})
    assert tasks() == []


def test_destructive_actions_are_post_only(auth):
    post(auth, '/tasks', content='keep me')
    tid = tasks()[0].id
    assert auth.get(f'/tasks/{tid}/delete').status_code == 405
    assert auth.get(f'/tasks/{tid}/toggle').status_code == 405
    assert len(tasks()) == 1


# -------------------------------------------------------------------- tasks

def test_create_edit_toggle_delete(auth):
    post(auth, '/tasks', content='Write report', priority='high', due_date='2030-01-02', notes='Q4 numbers')
    t = tasks()[0]
    assert (t.content, t.priority, t.notes) == ('Write report', 'high', 'Q4 numbers')
    assert t.due_date == datetime(2030, 1, 2)

    post(auth, f'/tasks/{t.id}/edit', content='Write final report', priority='low', due_date='', notes='')
    t = tasks()[0]
    assert (t.content, t.priority, t.due_date, t.notes) == ('Write final report', 'low', None, None)

    post(auth, f'/tasks/{t.id}/toggle')
    t = tasks()[0]
    assert t.completed and t.completed_at is not None

    post(auth, f'/tasks/{t.id}/delete')
    assert tasks() == []


def test_validation(auth):
    post(auth, '/tasks', content='   ')
    post(auth, '/tasks', content='x' * 201)
    post(auth, '/tasks', content='ok', due_date='not-a-date')
    post(auth, '/tasks', content='weird priority', priority='urgent')
    assert [t.content for t in tasks()] == ['weird priority']
    assert tasks()[0].priority == 'medium'


def test_toggle_json(auth):
    post(auth, '/tasks', content='Ping')
    tid = tasks()[0].id
    res = auth.post(f'/tasks/{tid}/toggle', headers={
        'Accept': 'application/json', 'X-CSRF-Token': token(auth, '/')})
    data = res.get_json()
    assert data['task']['completed'] is True
    assert data['stats']['completed'] == 1 and data['stats']['percent'] == 100


def test_users_cannot_touch_each_others_tasks(client):
    register(client)
    post(client, '/tasks', content='private')
    tid = tasks()[0].id
    client.post('/logout', data={'csrf_token': token(client, '/')})

    register(client, username='mallory', email='m@example.com')
    assert post(client, f'/tasks/{tid}/delete').status_code == 404
    assert client.get(f'/tasks/{tid}/edit').status_code == 404
    assert 'private' not in client.get('/').get_data(as_text=True)
    assert len(tasks()) == 1


def test_views_and_search(auth):
    today = datetime.now().date()
    post(auth, '/tasks', content='late thing', due_date=(today - timedelta(days=2)).isoformat())
    post(auth, '/tasks', content='today thing', due_date=today.isoformat())
    post(auth, '/tasks', content='future thing', due_date=(today + timedelta(days=5)).isoformat())
    post(auth, '/tasks', content='someday thing', notes='buried keyword')

    def shown(qs):
        html = auth.get('/?' + qs).get_data(as_text=True)
        return {c for c in ['late', 'today', 'future', 'someday'] if f'{c} thing</a>' in html}

    assert shown('view=overdue') == {'late'}
    assert shown('view=today') == {'late', 'today'}
    assert shown('view=upcoming') == {'future'}
    assert shown('q=keyword') == {'someday'}
    for sort in taskly.SORTS:
        assert auth.get(f'/?sort={sort}').status_code == 200


def test_clear_completed(auth):
    post(auth, '/tasks', content='a')
    post(auth, '/tasks', content='b')
    post(auth, f'/tasks/{tasks()[0].id}/toggle')
    post(auth, '/tasks/clear-completed')
    assert [t.content for t in tasks()] == ['b']


def test_export_csv_neutralises_formulas(auth):
    post(auth, '/tasks', content='=HYPERLINK("http://x")')
    res = auth.get('/export')
    assert res.headers['Content-Type'].startswith('text/csv')
    assert "'=HYPERLINK" in res.get_data(as_text=True)


# ------------------------------------------------------------------ account

def test_change_password_and_delete_account(auth):
    res = post(auth, '/account', action='change_password', current_password='wrong', new_password='newpassword1')
    assert res.status_code == 400
    post(auth, '/account', action='change_password', current_password='password123', new_password='newpassword1')
    with taskly.app.app_context():
        assert User.query.first().check_password('newpassword1')

    post(auth, '/tasks', content='bye')
    post(auth, '/account', action='delete_account', current_password='newpassword1')
    with taskly.app.app_context():
        assert User.query.count() == 0 and Task.query.count() == 0


# ------------------------------------------------------------------- schema

def test_missing_columns_are_added_to_old_databases():
    with taskly.app.app_context():
        db.drop_all()
        with db.engine.begin() as conn:
            conn.execute(text('CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(80), '
                              'email VARCHAR(120), password_hash VARCHAR(200))'))
            conn.execute(text('CREATE TABLE task (id INTEGER PRIMARY KEY, content VARCHAR(200), '
                              'completed BOOLEAN, date_created DATETIME, due_date DATETIME, user_id INTEGER)'))
        taskly.ensure_schema()
        cols = {c['name'] for c in db.inspect(db.engine).get_columns('task')}
        assert {'priority', 'notes', 'completed_at'} <= cols


def test_404_page(auth):
    res = auth.get('/tasks/9999/edit')
    assert res.status_code == 404 and 'Nothing here' in res.get_data(as_text=True)
