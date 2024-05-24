import os
import logging
from flask import Flask, request, redirect, url_for, render_template, send_from_directory, session, flash
from pytube import YouTube
import instaloader
from datetime import datetime
from functools import wraps
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'your_secret_key_here'  # Adding a secret key

logging.basicConfig(level=logging.DEBUG)

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Create a new SQLite database (if it doesn't exist) and tables
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    ''')
    
    # Create videos table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        title TEXT,
        description TEXT,
        date TEXT,
        restricted INTEGER DEFAULT 0
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# Helper function to get a database connection
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Decorator to check if the user is logged in
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrap

def download_youtube_video(url):
    try:
        yt = YouTube(url)
        streams = yt.streams.filter(progressive=True, file_extension='mp4')
        if streams:
            stream = streams.order_by('resolution').desc().first()
            filename = f"youtube_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            stream.download(output_path=app.config['UPLOAD_FOLDER'], filename=filename)
            return filename
        else:
            raise ValueError("No suitable stream found")
    except Exception as e:
        app.logger.error(f"Error downloading YouTube video: {e}")
        raise

def download_instagram_video(url):
    loader = instaloader.Instaloader(download_videos=True)
    shortcode = url.split('/')[-2]
    try:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        video_url = post.video_url
        if video_url:
            filename = f"instagram_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            loader.download_post(post, target=filepath)
            # Insert video details into database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO videos (filename, title, description, date) VALUES (?, ?, ?, ?)', 
                           (filename, post.title, post.caption, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
            return filename
        else:
            raise ValueError("No video URL found")
    except Exception as e:
        app.logger.error(f"Error downloading Instagram video: {e}")
        raise

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form['url']
        try:
            if 'youtube.com/shorts' in url or 'youtu.be' in url:
                filename = download_youtube_video(url)
            elif 'instagram.com/reel' in url:
                filename = download_instagram_video(url)
            else:
                return "Unsupported URL"
            return redirect(url_for('uploaded_file', filename=filename))
        except Exception as e:
            app.logger.error(f"Error processing URL: {e}")
            return str(e)
    return render_template('index.html')

@app.route('/videos')
def videos():
    uploaded_videos = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template('videos.html', videos=uploaded_videos)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return render_template('uploaded.html', filename=filename)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        hashed_password = generate_password_hash(password, method='sha256')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
            conn.commit()
            conn.close()
            flash('Registration successful, please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Username already exists.')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            return redirect(url_for('admin'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        if 'delete' in request.form:
            video_id = request.form['video_id']
            cursor.execute('DELETE FROM videos WHERE id = ?', (video_id,))
            conn.commit()
        elif 'update' in request.form:
            video_id = request.form['video_id']
            title = request.form['title']
            description = request.form['description']
            date = request.form['date']
            restricted = 1 if 'restricted' in request.form else 0
            cursor.execute('UPDATE videos SET title = ?, description = ?, date = ?, restricted = ? WHERE id = ?', 
                           (title, description, date, restricted, video_id))
            conn.commit()
    cursor.execute('SELECT * FROM videos')
    uploaded_videos = cursor.fetchall()
    conn.close()
    return render_template('admin.html', videos=uploaded_videos)



if __name__ == '__main__':
    app.run(debug=True)
