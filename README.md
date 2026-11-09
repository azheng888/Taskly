# Taskly

A simple and clean task management web application built with Flask. Users can create accounts, manage their to-do lists, and track their productivity.

**Live Demo:** [https://taskly-ohlb.onrender.com](https://taskly-ohlb.onrender.com)

## Features

- Accounts with sign-in by username or email, "keep me signed in", password change and account deletion
- Tasks with priority (high / medium / low), due date and optional notes
- Views for **All**, **Today** (due today or overdue), **Upcoming**, **Overdue** and **Done**, with live counts
- Search across titles and notes; sort by smart order, due date, priority, newest, oldest or A → Z
- Progress panel: completion rate, open, due today, overdue and done in the last 7 days
- Complete and delete tasks without a page reload (everything still works without JavaScript)
- Keyboard shortcuts: `N` to add a task, `/` to search, `Esc` to leave a field
- Quick "Today" / "Tomorrow" due dates; due dates follow your browser's time zone
- Clear completed tasks and export to CSV
- CSRF protection, POST-only state changes, safe redirects and security headers
- Automatic database upgrades: new columns are added to existing databases on startup
- Responsive dark design based on the Serene template from [Modulify](https://modulify.ai/templates)

## Tech Stack

- **Backend:** Flask, SQLAlchemy
- **Frontend:** HTML, CSS, Jinja2
- **Database:** SQLite (development), PostgreSQL (production)
- **Authentication:** Flask-Login, Werkzeug (password hashing)
- **Deployment:** Render


## Installation

### Local Development

1. Clone the repository
```bash
git clone https://github.com/azheng888/taskly.git
cd taskly
```

2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Run the application
```bash
python app.py
```

5. Open your browser and go to `http://localhost:5000`

### Production Deployment

The app is configured to use PostgreSQL in production and SQLite for local development. When deploying to platforms like Render:

1. Create a PostgreSQL database
2. Set the `DATABASE_URL` environment variable
3. The app will automatically use PostgreSQL and create the necessary tables


### Running tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Usage

1. Register for a new account
2. Log in with your credentials
3. Add tasks in the Capture box (press `N` from anywhere)
4. Switch between All, Today, Upcoming, Overdue and Done
5. Search with `/`, and click a task to edit its notes, priority or due date
6. Tick tasks off as you finish them

## Project Structure

```
taskly/
├── app.py                # Application: models, routes, schema upgrades
├── requirements.txt
├── requirements-dev.txt  # Test dependencies
├── static/
│   ├── css/style.css     # Design system and layout
│   └── js/app.js         # Progressive enhancements
├── templates/
│   ├── base.html         # Shell: header, toasts, footer
│   ├── auth_base.html    # Split layout for sign in / register
│   ├── index.html        # Task list
│   ├── update.html       # Edit task
│   ├── account.html
│   ├── login.html
│   ├── register.html
│   └── error.html
└── tests/test_app.py
```

## Future Improvements

- Task categories/tags
- Email reminders for due dates
- Password reset by email
- Recurring tasks

## License

This project is open source and available under the MIT License.