import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-only-change-me')
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() == 'true'
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','corsheaders','catalogue','console']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware','django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware']
ROOT_URLCONF='asaan.urls'; WSGI_APPLICATION='asaan.wsgi.application'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
# SQLite by default; set POSTGRES_DB to use an existing PostgreSQL server.
if os.getenv('POSTGRES_DB'):
    DATABASES={'default':{
        'ENGINE':'django.db.backends.postgresql',
        'NAME':os.getenv('POSTGRES_DB'),
        'USER':os.getenv('POSTGRES_USER','asaan'),
        'PASSWORD':os.getenv('POSTGRES_PASSWORD',''),
        'HOST':os.getenv('POSTGRES_HOST','127.0.0.1'),
        'PORT':os.getenv('POSTGRES_PORT','5432'),
        'CONN_MAX_AGE':60,
        'OPTIONS':{'connect_timeout':5},
    }}
else:
    DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.getenv('DATABASE_PATH',str(BASE_DIR/'db.sqlite3'))}}
LANGUAGE_CODE='en-in'; TIME_ZONE='Asia/Kolkata'; USE_I18N=True; USE_TZ=True; STATIC_URL='static/'; STATIC_ROOT=BASE_DIR/'staticfiles'; MEDIA_URL='/media/'; MEDIA_ROOT=Path(os.getenv('MEDIA_ROOT',str(BASE_DIR/'media'))); DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS=os.getenv('CORS_ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',')
CSRF_TRUSTED_ORIGINS=[origin for origin in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS','').split(',') if origin]
LOGIN_URL='/admin/login/'
LOGIN_REDIRECT_URL='/console/'
# TLS terminates at the reverse proxy; trust its forwarded protocol header.
SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
# Enable only when the console is served over HTTPS.
SESSION_COOKIE_SECURE=os.getenv('DJANGO_SECURE_COOKIES','false').lower()=='true'
CSRF_COOKIE_SECURE=SESSION_COOKIE_SECURE
