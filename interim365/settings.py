from pathlib import Path
import os
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='unsafe-secret-key')

# Clé de cryptage Kelio
KELIO_CRYPTO_KEY = config('KELIO_CRYPTO_KEY', default='').encode('utf-8')

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

    'mainapp',
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
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
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
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Abidjan'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')
MEDIA_URL = "/media/"

STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'static'),
)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Clé de cryptage pour les mots de passe Kelio
KELIO_ENCRYPTION_KEY = config('KELIO_ENCRYPTION_KEY', default='')

# Configuration Celery
CELERY_BROKER_URL = 'django-db'
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

CRONTAB_LOCK_JOBS = True
CRONTAB_COMMAND_PREFIX = 'cd /opt/interim365 && '
CRONTAB_COMMAND_SUFFIX = ''
CRONTAB_DJANGO_SETTINGS_MODULE = 'interim365.settings'


# ================================================================
# CONFIGURATION LOGGING AVANCÉE
# ================================================================

# Créer le répertoire logs
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    
    # ================================================================
    # FORMATTERS - Formats des messages
    # ================================================================
    'formatters': {
        # Format détaillé pour les fichiers
        'verbose': {
            'format': '[{asctime}] [{levelname}] [{name}] [{module}:{lineno}] {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        # Format simple pour la console
        'simple': {
            'format': '[{levelname}] {message}',
            'style': '{',
        },
        # Format pour les actions utilisateurs
        'action': {
            'format': '[{asctime}] {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        # Format JSON pour analyse
        'json': {
            'format': '{{"timestamp": "{asctime}", "level": "{levelname}", "module": "{module}", "message": "{message}"}}',
            'style': '{',
            'datefmt': '%Y-%m-%dT%H:%M:%S',
        },
    },
    
    # ================================================================
    # FILTERS - Filtres de messages
    # ================================================================
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    
    # ================================================================
    # HANDLERS - Destinations des logs
    # ================================================================
    'handlers': {
        # Console - développement
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        
        # Console détaillée - debug
        'console_verbose': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        
        # Fichier principal Django
        'file_django': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'django.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier application intérim
        'file_interim': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'interim.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 10,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier actions utilisateurs
        'file_actions': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'actions.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 30,  # Garder 30 fichiers pour audit
            'formatter': 'action',
            'encoding': 'utf-8',
        },
        
        # Fichier anomalies
        'file_anomalies': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'anomalies.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 20,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier erreurs seulement
        'file_errors': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'errors.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 10,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier synchronisation Kelio
        'file_kelio': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'kelio_sync.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 15,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier API Kelio
        'file_kelio_api': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'kelio_api.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 5,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        
        # Fichier performance
        'file_performance': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'performance.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 7,
            'formatter': 'action',
            'encoding': 'utf-8',
        },
        
        # Fichier sécurité (connexions, accès)
        'file_security': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'security.log'),
            'maxBytes': 100 * 1024 * 1024,  # 100 MB
            'backupCount': 30,  # Garder longtemps pour audit
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
    },
    
    # ================================================================
    # LOGGERS - Configuration par module
    # ================================================================
    'loggers': {
        # Logger Django principal
        'django': {
            'handlers': ['console', 'file_django'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Requêtes Django
        'django.request': {
            'handlers': ['console', 'file_django', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Base de données
        'django.db.backends': {
            'handlers': ['file_django'],
            'level': 'WARNING',  # Mettre DEBUG pour voir les requêtes SQL
            'propagate': False,
        },
        
        # Logger principal application
        'interim': {
            'handlers': ['console', 'file_interim', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Logger actions utilisateurs
        'interim.actions': {
            'handlers': ['file_actions', 'file_interim'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Logger anomalies
        'interim.anomalies': {
            'handlers': ['file_anomalies', 'file_errors', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        
        # Logger performance
        'interim.performance': {
            'handlers': ['file_performance'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Logger Kelio sync
        'interim.kelio': {
            'handlers': ['file_kelio', 'file_kelio_api', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Logger sécurité
        'interim.security': {
            'handlers': ['file_security', 'file_anomalies'],
            'level': 'INFO',
            'propagate': False,
        },
        
        # Logger mainapp (votre application)
        'mainapp': {
            'handlers': ['console', 'file_interim', 'file_errors'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    
    # Logger racine
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'file_django'],
    },
}

# ================================================================
# RÉSUMÉ DES FICHIERS DE LOG
# ================================================================
"""
Fichiers de log créés dans /logs/:

1. django.log       - Logs Django généraux
2. interim.log      - Logs application principale (toutes les vues)
3. actions.log      - Actions utilisateurs (connexions, créations, validations)
4. anomalies.log    - Anomalies et warnings détectés
5. errors.log       - Erreurs uniquement (pour monitoring)
6. kelio_sync.log   - Synchronisation Kelio
7. kelio_api.log    - Appels API Kelio (debug)
8. performance.log  - Résumés d'opérations avec durées
9. security.log     - Événements de sécurité (connexions, accès refusés)

Rotation automatique:
- Taille max: 5-10 MB par fichier
- Fichiers conservés: 5-30 selon importance
- Encodage: UTF-8

Correspondance avec views.py:
- log_action()    → interim.actions + interim
- log_anomalie()  → interim.anomalies + interim
- log_resume()    → interim.performance + interim
- log_erreur()    → interim + interim.anomalies
"""


"""
# Commandes utiles django-crontab:

# Ajouter les tâches cron au système
python manage.py crontab add

# Voir les tâches actives
python manage.py crontab show

# Supprimer toutes les tâches
python manage.py crontab remove

# Exécuter une tâche manuellement (test)
python manage.py crontab run <hash_de_la_tache>
"""