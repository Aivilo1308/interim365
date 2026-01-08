from pathlib import Path
import os
from decouple import config
#from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='unsafe-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

# Convertir la chaîne ALLOWED_HOSTS en liste
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1').split(',')
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='http://127.0.0.1').split(',')

SITE_URL = config('SITE_URL', default='http://localhost:8000')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    'django_crontab',

    'mainapp',  # TEMPORAIREMENT COMMENTÉ pour déboguer
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'interim365.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR,'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                # Ajouter le context processor des jours fériés
                'mainapp.context_processors.jours_feries_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'interim365.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

'''
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': config('DB_NAME', default='interim365'),
        'USER': config('DB_USER', default=''),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='1433'),
        'OPTIONS': {
            'driver': 'ODBC Driver 17 for SQL Server',
            # Options supplémentaires si nécessaire
            'extra_params': 'TrustServerCertificate=yes',
        },
    }
}
'''

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOGIN_URL = 'connexion'
LOGIN_REDIRECT_URL = '/'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
MEDIA_ROOT = os.path.join(BASE_DIR,'media/')
MEDIA_URL = "/media/"

# Add these new lines
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'static'),
)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Clé de cryptage pour les mots de passe Kelio (optionnel)
KELIO_ENCRYPTION_KEY = 'X9k#L2m@P5q$W8r!Z3v&N7b*F4g%H6j+'

# settings.py - Configuration MINIMALE
CELERY_BROKER_URL = 'django-db'  # Utilise votre DB existante
CELERY_TIMEZONE = 'Africa/Abidjan'
CELERY_ENABLE_UTC = False

# Configuration django-crontab
CRONJOBS = [
    # Synchronisation Kelio à 8h00
    ('0 8 * * *', 'mainapp.cron.sync_kelio_global', '>> /var/log/cron_kelio_8h.log 2>&1'),
    
    # Synchronisation Kelio à 12h00
    ('0 12 * * *', 'mainapp.cron.sync_kelio_global', '>> /var/log/cron_kelio_12h.log 2>&1'),
    
    # Synchronisation Kelio à 18h00
    ('0 18 * * *', 'mainapp.cron.sync_kelio_global', '>> /var/log/cron_kelio_18h.log 2>&1'),
    
    # Vérification jours fériés à 8h30
    ('30 8 * * *', 'mainapp.cron.verifier_jours_feries', '>> /var/log/cron_jours_feries.log 2>&1'),
]

# Préfixe pour les logs cron (optionnel)
CRONTAB_LOCK_JOBS = True  # Évite les exécutions simultanées
CRONTAB_COMMAND_PREFIX = 'cd /opt/interim365 && '
CRONTAB_COMMAND_SUFFIX = ''
CRONTAB_DJANGO_SETTINGS_MODULE = 'interim365.settings'

# ================================================================
# CONFIGURATION LOGGING SIMPLIFIÉE (sans imports)
# ================================================================

# Créer le répertoire logs de manière sécurisée
LOGS_DIR = BASE_DIR / 'logs'
try:
    LOGS_DIR.mkdir(exist_ok=True)
except:
    LOGS_DIR = BASE_DIR  # Fallback

# Configuration de logging simplifiée
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': str(LOGS_DIR / 'django.log'),
            'formatter': 'verbose',
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console'],
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}

# ================================================================
# CLASSES UTILITAIRES SIMPLES (sans imports complexes)
# ================================================================

class SimpleSafeLogger:
    """Logger simple sans dépendances circulaires"""
    
    def __init__(self, name='django'):
        self.name = name
    
    def _log(self, level, message):
        import logging
        try:
            logger = logging.getLogger(self.name)
            getattr(logger, level.lower())(message)
        except Exception:
            print(f"{level.upper()}: {message}")
    
    def info(self, message):
        self._log('INFO', message)
    
    def error(self, message):
        self._log('ERROR', message)
    
    def warning(self, message):
        self._log('WARNING', message)
    
    def debug(self, message):
        self._log('DEBUG', message)

def get_safe_kelio_logger():
    """Retourne un logger sécurisé"""
    return SimpleSafeLogger('kelio')


'''
# Ajouter les tâches cron au système
python manage.py crontab add

# Voir les tâches actives
python manage.py crontab show

# Supprimer toutes les tâches
python manage.py crontab remove

# Exécuter une tâche manuellement (test)
python manage.py crontab run <hash_de_la_tache>
'''