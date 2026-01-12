# -*- coding: utf-8 -*-
"""
Vues pour le module Maintenance - Sauvegarde et Optimisation
"""

import os
import json
import subprocess
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST, require_GET
from django.conf import settings
from django.db import connection
from django.core.cache import cache
from django.utils import timezone
from django.core.management import call_command
from io import StringIO

logger = logging.getLogger(__name__)


# =============================================================================
# DÉCORATEURS
# =============================================================================

def admin_required(view_func):
    """Décorateur pour restreindre l'accès aux administrateurs"""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Vous devez être connecté.")
            return redirect('login')
        
        try:
            profil = request.user.profilutilisateur
            if profil.type_profil not in ['ADMIN', 'SUPERUSER']:
                messages.error(request, "Accès réservé aux administrateurs.")
                return redirect('index')
        except:
            if not request.user.is_superuser:
                messages.error(request, "Accès réservé aux administrateurs.")
                return redirect('index')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def log_action(user, action, details=""):
    """Logger une action de maintenance"""
    try:
        from .models import JournalAction
        JournalAction.objects.create(
            utilisateur=user,
            action=action,
            details=details,
            ip_address=None
        )
    except Exception as e:
        logger.warning(f"Impossible de logger l'action: {e}")


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def get_database_info():
    """Récupérer les informations sur la base de données"""
    info = {
        'engine': 'Inconnu',
        'name': 'Inconnu',
        'size': 'N/A',
        'tables_count': 0,
        'total_rows': 0,
    }
    
    try:
        db_settings = settings.DATABASES['default']
        info['engine'] = db_settings.get('ENGINE', '').split('.')[-1]
        info['name'] = db_settings.get('NAME', 'Inconnu')
        
        with connection.cursor() as cursor:
            # Compter les tables
            if 'sqlite' in info['engine'].lower():
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                info['tables_count'] = len(tables)
                
                # Taille du fichier SQLite
                if os.path.exists(info['name']):
                    size_bytes = os.path.getsize(info['name'])
                    info['size'] = format_size(size_bytes)
                    info['size_bytes'] = size_bytes
                
                # Compter les lignes
                total_rows = 0
                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                        total_rows += cursor.fetchone()[0]
                    except:
                        pass
                info['total_rows'] = total_rows
                
            elif 'postgresql' in info['engine'].lower():
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                info['tables_count'] = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT pg_size_pretty(pg_database_size(current_database()))
                """)
                info['size'] = cursor.fetchone()[0]
                
            elif 'mysql' in info['engine'].lower():
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = DATABASE()
                """)
                info['tables_count'] = cursor.fetchone()[0]
                
    except Exception as e:
        logger.error(f"Erreur récupération info DB: {e}")
    
    return info


def format_size(size_bytes):
    """Formater une taille en bytes en format lisible"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_backup_directory():
    """Obtenir le répertoire de sauvegarde"""
    backup_dir = getattr(settings, 'BACKUP_DIR', None)
    if not backup_dir:
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    
    # Créer le répertoire s'il n'existe pas
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def get_backups_list():
    """Lister les sauvegardes existantes"""
    backup_dir = get_backup_directory()
    backups = []
    
    try:
        for filename in os.listdir(backup_dir):
            filepath = os.path.join(backup_dir, filename)
            if os.path.isfile(filepath) and (filename.endswith('.sql') or filename.endswith('.json') or filename.endswith('.sqlite3') or filename.endswith('.zip')):
                stat = os.stat(filepath)
                backups.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size': format_size(stat.st_size),
                    'size_bytes': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_mtime),
                    'type': get_backup_type(filename),
                })
        
        # Trier par date décroissante
        backups.sort(key=lambda x: x['created'], reverse=True)
    except Exception as e:
        logger.error(f"Erreur listage sauvegardes: {e}")
    
    return backups


def get_backup_type(filename):
    """Déterminer le type de sauvegarde"""
    if filename.endswith('.sql'):
        return 'SQL'
    elif filename.endswith('.json'):
        return 'JSON (Interim365)'
    elif filename.endswith('.zip'):
        return 'Archive complète'
    return 'Inconnu'


def get_system_stats():
    """Récupérer les statistiques système"""
    stats = {
        'disk_usage': None,
        'memory_usage': None,
        'cpu_usage': None,
        'uptime': None,
    }
    
    try:
        import psutil
        
        # Utilisation disque
        disk = psutil.disk_usage('/')
        stats['disk_usage'] = {
            'total': format_size(disk.total),
            'used': format_size(disk.used),
            'free': format_size(disk.free),
            'percent': disk.percent,
        }
        
        # Utilisation mémoire
        memory = psutil.virtual_memory()
        stats['memory_usage'] = {
            'total': format_size(memory.total),
            'used': format_size(memory.used),
            'available': format_size(memory.available),
            'percent': memory.percent,
        }
        
        # CPU
        stats['cpu_usage'] = psutil.cpu_percent(interval=1)
        
        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        stats['uptime'] = str(uptime).split('.')[0]
        
    except ImportError:
        logger.warning("psutil non installé - statistiques système limitées")
    except Exception as e:
        logger.error(f"Erreur stats système: {e}")
    
    return stats


def get_cache_stats():
    """Récupérer les statistiques du cache"""
    stats = {
        'backend': 'Inconnu',
        'keys_count': 'N/A',
        'status': 'Inconnu',
    }
    
    try:
        cache_backend = settings.CACHES.get('default', {}).get('BACKEND', '')
        stats['backend'] = cache_backend.split('.')[-1]
        
        # Test du cache
        test_key = '_maintenance_cache_test_'
        cache.set(test_key, 'test', 10)
        if cache.get(test_key) == 'test':
            stats['status'] = 'Opérationnel'
            cache.delete(test_key)
        else:
            stats['status'] = 'Problème détecté'
            
    except Exception as e:
        stats['status'] = f'Erreur: {str(e)}'
    
    return stats


# =============================================================================
# VUES PRINCIPALES
# =============================================================================

@login_required
@admin_required
def admin_maintenance(request):
    """Vue principale du module Maintenance"""
    context = {
        'page_title': 'Maintenance Système',
        'db_info': get_database_info(),
        'backups': get_backups_list()[:10],  # 10 dernières sauvegardes
        'system_stats': get_system_stats(),
        'cache_stats': get_cache_stats(),
        'backup_dir': get_backup_directory(),
    }
    
    # Statistiques supplémentaires
    try:
        from .models import JournalAction
        context['recent_actions'] = JournalAction.objects.order_by('-date_action')[:20]
    except:
        context['recent_actions'] = []
    
    return render(request, 'maintenance/dashboard.html', context)


# =============================================================================
# SAUVEGARDES
# =============================================================================

@login_required
@admin_required
def backup_liste(request):
    """Liste des sauvegardes"""
    backups = get_backups_list()
    
    context = {
        'page_title': 'Gestion des Sauvegardes',
        'backups': backups,
        'backup_dir': get_backup_directory(),
        'total_size': format_size(sum(b['size_bytes'] for b in backups)),
        'db_info': get_database_info(),
    }
    
    return render(request, 'maintenance/backup_liste.html', context)


@login_required
@admin_required
@require_POST
def backup_creer(request):
    """Créer une nouvelle sauvegarde"""
    backup_type = request.POST.get('backup_type', 'json')
    
    try:
        backup_dir = get_backup_directory()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if backup_type == 'json':
            # Sauvegarde Django JSON (dumpdata)
            filename = f"backup_interim365_{timestamp}.json"
            filepath = os.path.join(backup_dir, filename)
            
            output = StringIO()
            call_command('dumpdata', '--natural-foreign', '--natural-primary', 
                        '--exclude=contenttypes', '--exclude=auth.permission',
                        '--indent=2', stdout=output)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(output.getvalue())
            
            message = f"Sauvegarde JSON créée: {filename}"
            
        elif backup_type == 'sqlite':
            # Copie directe SQLite
            db_path = settings.DATABASES['default'].get('NAME')
            if db_path and os.path.exists(db_path):
                filename = f"backup_sqlite_{timestamp}.sqlite3"
                filepath = os.path.join(backup_dir, filename)
                shutil.copy2(db_path, filepath)
                message = f"Sauvegarde SQLite créée: {filename}"
            else:
                raise Exception("Base de données SQLite non trouvée")
                
        elif backup_type == 'full':
            # Archive complète (DB + media)
            filename = f"backup_full_{timestamp}.zip"
            filepath = os.path.join(backup_dir, filename)
            
            import zipfile
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Ajouter la base de données
                db_path = settings.DATABASES['default'].get('NAME')
                if db_path and os.path.exists(db_path):
                    zipf.write(db_path, os.path.basename(db_path))
                
                # Ajouter les fichiers media
                media_root = getattr(settings, 'MEDIA_ROOT', None)
                if media_root and os.path.exists(media_root):
                    for root, dirs, files in os.walk(media_root):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.join('media', os.path.relpath(file_path, media_root))
                            zipf.write(file_path, arcname)
            
            message = f"Archive complète créée: {filename}"
        
        else:
            raise Exception(f"Type de sauvegarde inconnu: {backup_type}")
        
        log_action(request.user, "Création sauvegarde", message)
        messages.success(request, message)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': message, 'filename': filename})
        
    except Exception as e:
        logger.error(f"Erreur création sauvegarde: {e}")
        error_msg = f"Erreur lors de la création de la sauvegarde: {str(e)}"
        messages.error(request, error_msg)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg}, status=500)
    
    return redirect('backup_liste')


@login_required
@admin_required
def backup_telecharger(request, filename):
    """Télécharger une sauvegarde"""
    backup_dir = get_backup_directory()
    filepath = os.path.join(backup_dir, filename)
    
    # Sécurité: vérifier que le fichier est dans le répertoire de backup
    if not os.path.commonpath([filepath, backup_dir]) == backup_dir:
        messages.error(request, "Accès non autorisé.")
        return redirect('backup_liste')
    
    if not os.path.exists(filepath):
        messages.error(request, "Fichier de sauvegarde non trouvé.")
        return redirect('backup_liste')
    
    try:
        log_action(request.user, "Téléchargement sauvegarde", filename)
        response = FileResponse(open(filepath, 'rb'), as_attachment=True, filename=filename)
        return response
    except Exception as e:
        logger.error(f"Erreur téléchargement sauvegarde: {e}")
        messages.error(request, f"Erreur: {str(e)}")
        return redirect('backup_liste')


@login_required
@admin_required
@require_POST
def backup_supprimer(request, filename):
    """Supprimer une sauvegarde"""
    backup_dir = get_backup_directory()
    filepath = os.path.join(backup_dir, filename)
    
    # Sécurité
    if not os.path.commonpath([filepath, backup_dir]) == backup_dir:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    
    if not os.path.exists(filepath):
        return JsonResponse({'success': False, 'error': 'Fichier non trouvé'}, status=404)
    
    try:
        os.remove(filepath)
        log_action(request.user, "Suppression sauvegarde", filename)
        return JsonResponse({'success': True, 'message': f'Sauvegarde {filename} supprimée'})
    except Exception as e:
        logger.error(f"Erreur suppression sauvegarde: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
@require_POST
def backup_restaurer(request, filename):
    """Restaurer une sauvegarde (avec confirmation)"""
    backup_dir = get_backup_directory()
    filepath = os.path.join(backup_dir, filename)
    
    # Sécurité
    if not os.path.commonpath([filepath, backup_dir]) == backup_dir:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    
    if not os.path.exists(filepath):
        return JsonResponse({'success': False, 'error': 'Fichier non trouvé'}, status=404)
    
    try:
        if filename.endswith('.json'):
            # Restauration Django loaddata
            call_command('loaddata', filepath)
            message = f"Restauration JSON effectuée: {filename}"
            
        elif filename.endswith('.sqlite3'):
            # Restauration SQLite (copie)
            db_path = settings.DATABASES['default'].get('NAME')
            if db_path:
                # Créer une sauvegarde avant restauration
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_before = os.path.join(backup_dir, f"pre_restore_{timestamp}.sqlite3")
                shutil.copy2(db_path, backup_before)
                
                # Restaurer
                shutil.copy2(filepath, db_path)
                message = f"Restauration SQLite effectuée: {filename}"
            else:
                raise Exception("Chemin de la base de données non trouvé")
        else:
            raise Exception("Type de fichier non supporté pour la restauration")
        
        log_action(request.user, "Restauration sauvegarde", message)
        return JsonResponse({'success': True, 'message': message})
        
    except Exception as e:
        logger.error(f"Erreur restauration: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# OPTIMISATION
# =============================================================================

@login_required
@admin_required
def optimisation_dashboard(request):
    """Dashboard d'optimisation"""
    context = {
        'page_title': 'Optimisation Système',
        'db_info': get_database_info(),
        'system_stats': get_system_stats(),
        'cache_stats': get_cache_stats(),
    }
    
    # Analyser les tables
    context['tables_analysis'] = analyze_tables()
    
    # Suggestions d'optimisation
    context['suggestions'] = get_optimization_suggestions()
    
    return render(request, 'maintenance/optimisation.html', context)


def analyze_tables():
    """Analyser les tables de la base de données"""
    tables = []
    
    try:
        with connection.cursor() as cursor:
            db_engine = settings.DATABASES['default'].get('ENGINE', '')
            
            if 'sqlite' in db_engine.lower():
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                table_names = [row[0] for row in cursor.fetchall()]
                
                for table_name in table_names:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row_count = cursor.fetchone()[0]
                        
                        tables.append({
                            'name': table_name,
                            'rows': row_count,
                            'status': 'ok' if row_count < 100000 else 'warning',
                        })
                    except:
                        pass
                        
            elif 'postgresql' in db_engine.lower():
                cursor.execute("""
                    SELECT relname, n_live_tup 
                    FROM pg_stat_user_tables 
                    ORDER BY n_live_tup DESC
                """)
                for row in cursor.fetchall():
                    tables.append({
                        'name': row[0],
                        'rows': row[1],
                        'status': 'ok' if row[1] < 100000 else 'warning',
                    })
                    
    except Exception as e:
        logger.error(f"Erreur analyse tables: {e}")
    
    return sorted(tables, key=lambda x: x['rows'], reverse=True)[:20]


def get_optimization_suggestions():
    """Générer des suggestions d'optimisation"""
    suggestions = []
    
    # Vérifier la taille de la base
    db_info = get_database_info()
    if db_info.get('size_bytes', 0) > 500 * 1024 * 1024:  # > 500 MB
        suggestions.append({
            'type': 'warning',
            'title': 'Base de données volumineuse',
            'description': f"La base de données fait {db_info['size']}. Envisagez un archivage des anciennes données.",
            'action': 'archive_old_data',
        })
    
    # Vérifier le cache
    cache_stats = get_cache_stats()
    if cache_stats['status'] != 'Opérationnel':
        suggestions.append({
            'type': 'error',
            'title': 'Problème de cache',
            'description': "Le système de cache n'est pas opérationnel.",
            'action': 'check_cache',
        })
    
    # Vérifier les sauvegardes
    backups = get_backups_list()
    if not backups:
        suggestions.append({
            'type': 'error',
            'title': 'Aucune sauvegarde',
            'description': "Aucune sauvegarde n'a été trouvée. Créez une sauvegarde immédiatement.",
            'action': 'create_backup',
        })
    elif backups[0]['created'] < datetime.now() - timedelta(days=7):
        suggestions.append({
            'type': 'warning',
            'title': 'Sauvegarde ancienne',
            'description': f"La dernière sauvegarde date de {backups[0]['created'].strftime('%d/%m/%Y')}.",
            'action': 'create_backup',
        })
    
    # Statistiques système
    system_stats = get_system_stats()
    if system_stats.get('disk_usage') and system_stats['disk_usage'].get('percent', 0) > 85:
        suggestions.append({
            'type': 'warning',
            'title': 'Espace disque limité',
            'description': f"Utilisation disque à {system_stats['disk_usage']['percent']}%.",
            'action': 'clean_disk',
        })
    
    return suggestions


@login_required
@admin_required
@require_POST
def optimisation_vacuum(request):
    """Exécuter VACUUM sur la base de données"""
    try:
        db_engine = settings.DATABASES['default'].get('ENGINE', '')
        
        with connection.cursor() as cursor:
            if 'sqlite' in db_engine.lower():
                cursor.execute("VACUUM")
                message = "VACUUM SQLite exécuté avec succès"
            elif 'postgresql' in db_engine.lower():
                cursor.execute("VACUUM ANALYZE")
                message = "VACUUM ANALYZE PostgreSQL exécuté avec succès"
            else:
                message = "Optimisation non disponible pour ce type de base"
        
        log_action(request.user, "Optimisation VACUUM", message)
        return JsonResponse({'success': True, 'message': message})
        
    except Exception as e:
        logger.error(f"Erreur VACUUM: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
@require_POST
def optimisation_clear_cache(request):
    """Vider le cache"""
    try:
        cache.clear()
        log_action(request.user, "Vidage cache", "Cache vidé avec succès")
        return JsonResponse({'success': True, 'message': 'Cache vidé avec succès'})
    except Exception as e:
        logger.error(f"Erreur vidage cache: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
@require_POST
def optimisation_clear_sessions(request):
    """Nettoyer les sessions expirées"""
    try:
        output = StringIO()
        call_command('clearsessions', stdout=output)
        message = "Sessions expirées nettoyées"
        log_action(request.user, "Nettoyage sessions", message)
        return JsonResponse({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Erreur nettoyage sessions: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@admin_required
@require_POST
def optimisation_archive_logs(request):
    """Archiver les anciens logs"""
    try:
        days = int(request.POST.get('days', 90))
        cutoff_date = timezone.now() - timedelta(days=days)
        
        from .models import JournalAction
        old_logs = JournalAction.objects.filter(date_action__lt=cutoff_date)
        count = old_logs.count()
        
        # Créer une archive avant suppression
        if count > 0:
            backup_dir = get_backup_directory()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            archive_file = os.path.join(backup_dir, f"logs_archive_{timestamp}.json")
            
            logs_data = list(old_logs.values())
            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(logs_data, f, default=str, indent=2)
            
            old_logs.delete()
            message = f"{count} logs archivés et supprimés (> {days} jours)"
        else:
            message = "Aucun log à archiver"
        
        log_action(request.user, "Archivage logs", message)
        return JsonResponse({'success': True, 'message': message, 'archived_count': count})
        
    except Exception as e:
        logger.error(f"Erreur archivage logs: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# AJAX - STATISTIQUES EN TEMPS RÉEL
# =============================================================================

@login_required
@admin_required
def maintenance_stats_ajax(request):
    """Récupérer les statistiques de maintenance en AJAX"""
    try:
        data = {
            'success': True,
            'db_info': get_database_info(),
            'system_stats': get_system_stats(),
            'cache_stats': get_cache_stats(),
            'backups_count': len(get_backups_list()),
            'timestamp': timezone.now().isoformat(),
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Erreur stats maintenance: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
