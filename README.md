# Taskly

A simple and clean task management web application built with Flask. Users can create accounts, manage their to-do lists, and track their productivity.

## Features

- User authentication (register/login)
- Create, edit, and delete tasks
- Mark tasks as complete/incomplete
- Set due dates
- Filter tasks (all/active/completed)
- Search functionality
- Sort tasks by date or alphabetically
- Responsive design

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


## Usage

1. Register for a new account
2. Log in with your credentials
3. Start adding tasks with the form at the top
4. Click on filters to view different task categories
5. Use the search bar to find specific tasks
6. Mark tasks as complete or delete them when done

## Project Structure

```
taskly/
├── app.py              # Main application file
├── requirements.txt    # Python dependencies
├── static/
│   └── css/
│       └── style.css   # Styling
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   └── update.html
└── instance/
    └── tasks.db        # SQLite database
```

## Future Improvements

- Add task categories/tags
- Email notifications for due dates
- Export tasks to CSV
- Dark mode
- Password reset functionality

## License

This project is open source and available under the MIT License.