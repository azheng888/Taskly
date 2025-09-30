from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secretdevkeyplaceholder'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Task %r>' % self.id

@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        task_content = request.form['content'].strip()
        
        if not task_content:
            flash('Task cannot be empty', 'error')
        elif len(task_content) > 200:
            flash('Task is too long (max 200 characters)', 'error')
        else:
            new_task = Task(content=task_content)
            
            try:
                db.session.add(new_task)
                db.session.commit()
                flash('Task added successfully!', 'success')
                
            except:
                flash('Error adding task. Please try again.', 'error')
        
        return redirect('/')

    else:
        tasks = Task.query.order_by(Task.date_created).all()
        return render_template('index.html', tasks=tasks)

@app.route('/delete/<int:id>')
def delete(id):
    task_to_delete = Task.query.get_or_404(id)

    try:
        db.session.delete(task_to_delete)
        db.session.commit()
        flash('Task deleted successfully!', 'success')
    except Exception as e:
        flash('Error deleting task. Please try again.', 'error')
    
    return redirect('/')

@app.route('/update/<int:id>', methods=['GET', 'POST'])
def update(id):
    task = Task.query.get_or_404(id)

    if request.method == 'POST':
        task_content = request.form['content'].strip()

        if not task_content:
            flash('Task cannot be empty', 'error')
            return render_template('update.html', task=task)
        elif len(task_content) > 200:
            flash('Task is too long (max 200 characters)', 'error')
            return render_template('update.html', task=task)

        task.content = task_content

        try:
            db.session.commit()
            flash('Task updated successfully!', 'success')
            return redirect('/')
        except:
            flash('Error updating task. Please try again.', 'error')
            return render_template('update.html', task=task)
    
    return render_template('update.html', task=task)

@app.route('/complete/<int:id>')
def complete(id):
    task = Task.query.get_or_404(id)
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