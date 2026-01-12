# -*- coding: utf-8 -*-
"""
Vues pour le journal des logs et audits - Version adaptée au système de logging avancé
Lecture des fichiers de logs: actions.log, anomalies.log, performance.log, errors.log, interim.log
Affichage, filtrage par dates/heures, catégories, sévérités, export
"""

import os
import re
import logging
import time
import traceback
from datetime import datetime, timedelta
from collections import defaultdict
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.conf import settings

from .models import HistoriqueAction, ProfilUtilisateur

# ================================================================
# CONFIGURATION LOGGING AVANCÉ
# ================================================================

logger = logging.getLogger('interim')
action_logger = logging.getLogger('interim.actions')
anomaly_logger = logging.getLogger('interim.anomalies')
perf_logger = logging.getLogger('interim.performance')


def log_action(category, action, message, request=None, **kwargs):
    """Log une action utilisateur avec contexte complet"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    ip_addr = "-"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
        ip_addr = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '-'))
        if ',' in ip_addr:
            ip_addr = ip_addr.split(',')[0].strip()
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [{category}] [{action}] [User:{user_info}] [IP:{ip_addr}] {extra_info} {message}"
    
    action_logger.info(log_msg)
    logger.info(log_msg)


def log_anomalie(category, message, severite='WARNING', request=None, **kwargs):
    """Log une anomalie détectée avec niveau de sévérité"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [ANOMALIE] [{category}] [{severite}] [User:{user_info}] {extra_info} {message}"
    
    if severite == 'ERROR':
        anomaly_logger.error(f"❌ {log_msg}")
        logger.error(f"❌ ANOMALIE: {log_msg}")
    elif severite == 'CRITICAL':
        anomaly_logger.critical(f"🔥 {log_msg}")
        logger.critical(f"🔥 ANOMALIE CRITIQUE: {log_msg}")
    else:
        anomaly_logger.warning(f"⚠️ {log_msg}")
        logger.warning(f"⚠️ ANOMALIE: {log_msg}")


def log_resume(operation, stats, duree_ms=None):
    """Log un résumé d'opération avec statistiques visuelles"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    
    lines = [
        "",
        "=" * 60,
        f"📊 RÉSUMÉ: {operation}",
        "=" * 60,
        f"⏰ Date/Heure: {timestamp}",
    ]
    
    if duree_ms is not None:
        if duree_ms >= 60000:
            duree_str = f"{duree_ms/60000:.1f} min"
        elif duree_ms >= 1000:
            duree_str = f"{duree_ms/1000:.1f} sec"
        else:
            duree_str = f"{duree_ms:.0f} ms"
        lines.append(f"⏱️ Durée: {duree_str}")
    
    lines.append("📈 Statistiques:")
    for key, value in stats.items():
        icon = '✅' if 'succes' in key.lower() or 'ok' in key.lower() or 'cree' in key.lower() else \
               '❌' if 'erreur' in key.lower() or 'echec' in key.lower() else \
               '⚠️' if 'warning' in key.lower() or 'anomal' in key.lower() else '•'
        lines.append(f"   {icon} {key}: {value}")
    
    lines.extend(["=" * 60, ""])
    
    resume_text = '\n'.join(lines)
    perf_logger.info(resume_text)
    logger.info(resume_text)


def log_erreur(category, message, exception=None, request=None, **kwargs):
    """Log une erreur avec stack trace complète"""
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_info = "anonymous"
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        user_info = request.user.username
    
    extra_info = ' '.join([f"[{k}:{v}]" for k, v in kwargs.items() if v is not None])
    log_msg = f"[{timestamp}] [ERREUR] [{category}] [User:{user_info}] {extra_info} {message}"
    
    if exception:
        log_msg += f"\n  Exception: {type(exception).__name__}: {str(exception)}"
        log_msg += f"\n  Stack trace:\n{traceback.format_exc()}"
    
    logger.error(log_msg)
    anomaly_logger.error(log_msg)


# ================================================================
# UTILITAIRES
# ================================================================

def is_admin_or_rh(user):
    """Vérifie si l'utilisateur est admin ou RH"""
    if user.is_superuser:
        return True
    if hasattr(user, 'profilutilisateur'):
        return user.profilutilisateur.type_profil in ['ADMIN', 'RH']
    return False


def _format_size(size_bytes):
    """Formate une taille en bytes en format lisible"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _get_logs_directory():
    """Retourne le répertoire des logs"""
    return getattr(settings, 'LOGS_DIR', settings.BASE_DIR / 'logs')


def _count_lines(filepath):
    """Compte le nombre de lignes dans un fichier"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except:
        return 0


# ================================================================
# PARSEUR DE LOGS
# ================================================================

# Pattern pour parser les lignes de log du nouveau système
LOG_PATTERN = re.compile(
    r'\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*'
    r'\[(?P<category>[^\]]+)\]\s*'
    r'\[(?P<action>[^\]]+)\]\s*'
    r'(?:\[User:(?P<user>[^\]]+)\])?\s*'
    r'(?:\[IP:(?P<ip>[^\]]+)\])?\s*'
    r'(?P<extra>(?:\[[^\]]+\]\s*)*)'
    r'(?P<message>.*)'
)

# Pattern pour les anomalies
ANOMALY_PATTERN = re.compile(
    r'\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*'
    r'\[ANOMALIE\]\s*'
    r'\[(?P<category>[^\]]+)\]\s*'
    r'\[(?P<severite>[^\]]+)\]\s*'
    r'(?:\[User:(?P<user>[^\]]+)\])?\s*'
    r'(?P<extra>(?:\[[^\]]+\]\s*)*)'
    r'(?P<message>.*)'
)

# Pattern pour les résumés
RESUME_PATTERN = re.compile(r'📊 RÉSUMÉ: (?P<operation>.+)')


def _make_aware(dt):
    """Convertit un datetime naive en aware (avec timezone)"""
    if dt is None:
        return timezone.now()
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def parse_log_line(line, source_file='unknown'):
    """Parse une ligne de log et retourne un dictionnaire structuré"""
    line = line.strip()
    if not line:
        return None
    
    # Essayer le pattern standard
    match = LOG_PATTERN.match(line)
    if match:
        data = match.groupdict()
        extras = {}
        if data['extra']:
            extra_matches = re.findall(r'\[([^:]+):([^\]]+)\]', data['extra'])
            for key, value in extra_matches:
                extras[key] = value
        
        try:
            dt = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M:%S')
        except:
            dt = timezone.now()
        
        return {
            'type': 'action',
            'timestamp': data['timestamp'],
            'timestamp_dt': _make_aware(dt),
            'category': data['category'],
            'action': data['action'],
            'user': data['user'] or 'anonymous',
            'ip': data['ip'] or '-',
            'message': data['message'].strip(),
            'extras': extras,
            'source_file': source_file,
            'raw': line,
            'severite': 'INFO',
        }
    
    # Essayer le pattern anomalie
    match = ANOMALY_PATTERN.match(line)
    if match:
        data = match.groupdict()
        extras = {}
        if data['extra']:
            extra_matches = re.findall(r'\[([^:]+):([^\]]+)\]', data['extra'])
            for key, value in extra_matches:
                extras[key] = value
        
        try:
            dt = datetime.strptime(data['timestamp'], '%Y-%m-%d %H:%M:%S')
        except:
            dt = timezone.now()
        
        return {
            'type': 'anomalie',
            'timestamp': data['timestamp'],
            'timestamp_dt': _make_aware(dt),
            'category': data['category'],
            'action': 'ANOMALIE',
            'user': data['user'] or 'anonymous',
            'ip': '-',
            'message': data['message'].strip(),
            'extras': extras,
            'source_file': source_file,
            'raw': line,
            'severite': data['severite'],
        }
    
    # Essayer le pattern résumé
    match = RESUME_PATTERN.search(line)
    if match:
        return {
            'type': 'resume',
            'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp_dt': timezone.now(),
            'category': 'PERFORMANCE',
            'action': 'RESUME',
            'user': 'system',
            'ip': '-',
            'message': match.group('operation'),
            'extras': {},
            'source_file': source_file,
            'raw': line,
            'severite': 'INFO',
        }
    
    # Ligne non structurée
    if 'ERROR' in line.upper() or 'ERREUR' in line.upper():
        severite = 'ERROR'
    elif 'WARNING' in line.upper() or 'WARN' in line.upper():
        severite = 'WARNING'
    elif 'CRITICAL' in line.upper():
        severite = 'CRITICAL'
    else:
        severite = 'INFO'
    
    return {
        'type': 'raw',
        'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'timestamp_dt': timezone.now(),
        'category': 'SYSTEM',
        'action': 'LOG',
        'user': '-',
        'ip': '-',
        'message': line[:500],
        'extras': {},
        'source_file': source_file,
        'raw': line,
        'severite': severite,
    }


def read_log_file(filepath, max_lines=10000, filters=None):
    """Lit un fichier de log et retourne les entrées parsées"""
    entries = []
    source_file = os.path.basename(filepath)
    
    if not os.path.exists(filepath):
        return entries
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        lines = list(reversed(lines[-max_lines:]))
        
        for line in lines:
            entry = parse_log_line(line, source_file)
            if entry:
                if filters:
                    if filters.get('category') and entry['category'] != filters['category']:
                        continue
                    if filters.get('severite') and entry['severite'] != filters['severite']:
                        continue
                    if filters.get('user') and filters['user'].lower() not in entry['user'].lower():
                        continue
                    if filters.get('recherche') and filters['recherche'].lower() not in entry['raw'].lower():
                        continue
                    if filters.get('date_debut'):
                        try:
                            dt_debut = datetime.strptime(filters['date_debut'], '%Y-%m-%d')
                            dt_debut = _make_aware(dt_debut)
                            if entry['timestamp_dt'].date() < dt_debut.date():
                                continue
                        except:
                            pass
                    if filters.get('date_fin'):
                        try:
                            dt_fin = datetime.strptime(filters['date_fin'], '%Y-%m-%d')
                            dt_fin = _make_aware(dt_fin)
                            if entry['timestamp_dt'].date() > dt_fin.date():
                                continue
                        except:
                            pass
                
                entries.append(entry)
    
    except Exception as e:
        logger.error(f"Erreur lecture fichier log {filepath}: {e}")
    
    return entries


def get_all_log_entries(filters=None, max_per_file=5000):
    """Récupère toutes les entrées de logs depuis tous les fichiers"""
    logs_dir = _get_logs_directory()
    all_entries = []
    
    log_files = ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']
    source_filter = filters.get('source_file') if filters else None
    
    for log_file in log_files:
        if source_filter and log_file != source_filter:
            continue
        
        filepath = os.path.join(logs_dir, log_file)
        if os.path.exists(filepath):
            entries = read_log_file(filepath, max_lines=max_per_file, filters=filters)
            all_entries.extend(entries)
    
    all_entries.sort(key=lambda x: x['timestamp_dt'], reverse=True)
    return all_entries


# ================================================================
# VUES PRINCIPALES
# ================================================================

@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs(request):
    """
    Vue principale du journal des logs et audits
    Combine les logs de la BDD (HistoriqueAction) et des fichiers de logs
    """
    start_time = time.time()
    log_action('LOGS', 'ACCES_JOURNAL', "Accès journal des logs", request=request)
    
    # Paramètres de filtrage
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')
    heure_debut = request.GET.get('heure_debut', '00:00')
    heure_fin = request.GET.get('heure_fin', '23:59')
    type_action = request.GET.get('type_action', '')
    category_filter = request.GET.get('category', '')
    severite_filter = request.GET.get('severite', '')
    source_filter = request.GET.get('source', '')
    source_file_filter = request.GET.get('source_file', '')
    utilisateur_id = request.GET.get('utilisateur', '')
    recherche = request.GET.get('recherche', '').strip()
    niveau_hierarchique = request.GET.get('niveau', '')
    per_page = request.GET.get('per_page', '50')
    
    file_filters = {
        'category': category_filter,
        'severite': severite_filter,
        'recherche': recherche,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'source_file': source_file_filter,
    }
    
    logs_combined = []
    
    # 1. Logs depuis les fichiers
    if source_filter != 'bdd':
        file_entries = get_all_log_entries(filters=file_filters, max_per_file=3000)
        for entry in file_entries:
            logs_combined.append({
                'id': None,
                'source': 'file',
                'source_file': entry['source_file'],
                'created_at': entry['timestamp_dt'],
                'action': entry['action'],
                'category': entry['category'],
                'description': entry['message'],
                'utilisateur_nom': entry['user'],
                'utilisateur_matricule': '-',
                'demande_numero': entry['extras'].get('demande', '-'),
                'niveau_hierarchique': entry['extras'].get('niveau', '-'),
                'adresse_ip': entry['ip'],
                'severite': entry['severite'],
                'raw': entry['raw'],
                'extras': entry['extras'],
            })
    
    # 2. Logs depuis la BDD
    if source_filter != 'file':
        logs_qs = HistoriqueAction.objects.select_related(
            'utilisateur', 'utilisateur__user', 'demande', 'proposition', 'validation'
        ).all()
        
        if date_debut:
            try:
                dt_debut = datetime.strptime(f"{date_debut} {heure_debut}", '%Y-%m-%d %H:%M')
                dt_debut = timezone.make_aware(dt_debut) if timezone.is_naive(dt_debut) else dt_debut
                logs_qs = logs_qs.filter(created_at__gte=dt_debut)
            except ValueError:
                pass
        
        if date_fin:
            try:
                dt_fin = datetime.strptime(f"{date_fin} {heure_fin}", '%Y-%m-%d %H:%M')
                dt_fin = timezone.make_aware(dt_fin) if timezone.is_naive(dt_fin) else dt_fin
                logs_qs = logs_qs.filter(created_at__lte=dt_fin)
            except ValueError:
                pass
        
        if type_action:
            logs_qs = logs_qs.filter(action=type_action)
        if utilisateur_id:
            logs_qs = logs_qs.filter(utilisateur_id=utilisateur_id)
        if niveau_hierarchique:
            logs_qs = logs_qs.filter(niveau_hierarchique=niveau_hierarchique)
        if recherche:
            logs_qs = logs_qs.filter(
                Q(description__icontains=recherche) |
                Q(demande__numero_demande__icontains=recherche) |
                Q(utilisateur__matricule__icontains=recherche) |
                Q(adresse_ip__icontains=recherche)
            )
        
        logs_qs = logs_qs.order_by('-created_at')[:5000]
        
        for log in logs_qs:
            logs_combined.append({
                'id': log.id,
                'source': 'bdd',
                'source_file': 'database',
                'created_at': log.created_at,
                'action': log.get_action_display() if hasattr(log, 'get_action_display') else log.action,
                'category': 'DATABASE',
                'description': log.description,
                'utilisateur_nom': log.utilisateur.nom_complet if log.utilisateur else 'Système',
                'utilisateur_matricule': log.utilisateur.matricule if log.utilisateur else '-',
                'demande_numero': log.demande.numero_demande if log.demande else '-',
                'niveau_hierarchique': log.niveau_hierarchique or '-',
                'adresse_ip': log.adresse_ip or '-',
                'severite': 'INFO',
                'raw': log.description,
                'extras': {},
            })
    
    logs_combined.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Statistiques
    today = timezone.now().date()
    logs_dir = _get_logs_directory()
    
    file_stats = {}
    log_files = ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']
    for lf in log_files:
        filepath = os.path.join(logs_dir, lf)
        if os.path.exists(filepath):
            stat = os.stat(filepath)
            file_stats[lf] = {
                'taille': _format_size(stat.st_size),
                'modifie': datetime.fromtimestamp(stat.st_mtime),
            }
    
    stats = {
        'total_bdd': HistoriqueAction.objects.count(),
        'aujourd_hui_bdd': HistoriqueAction.objects.filter(created_at__date=today).count(),
        'cette_semaine_bdd': HistoriqueAction.objects.filter(created_at__gte=today - timedelta(days=7)).count(),
        'filtres_actifs': len(logs_combined),
        'fichiers_logs': len(file_stats),
    }
    
    categories_count = defaultdict(int)
    severites_count = defaultdict(int)
    for log in logs_combined[:1000]:
        categories_count[log['category']] += 1
        severites_count[log['severite']] += 1
    
    repartition_categories = [{'category': k, 'count': v} for k, v in sorted(categories_count.items(), key=lambda x: -x[1])[:10]]
    repartition_severites = [{'severite': k, 'count': v} for k, v in sorted(severites_count.items(), key=lambda x: -x[1])]
    
    # Pagination
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100, 200]:
            per_page = 50
    except (ValueError, TypeError):
        per_page = 50
    
    paginator = Paginator(logs_combined, per_page)
    page = request.GET.get('page', 1)
    
    try:
        logs_page = paginator.page(page)
    except PageNotAnInteger:
        logs_page = paginator.page(1)
    except EmptyPage:
        logs_page = paginator.page(paginator.num_pages)
    
    types_action = getattr(HistoriqueAction, 'TYPES_ACTION', [])
    utilisateurs = ProfilUtilisateur.objects.filter(
        actions_historique__isnull=False
    ).distinct().select_related('user').order_by('user__last_name')[:100]
    
    niveaux = [
        ('CHEF_EQUIPE', 'Chef d\'équipe'),
        ('RESPONSABLE', 'Responsable (N+1)'),
        ('DIRECTEUR', 'Directeur (N+2)'),
        ('RH', 'RH'),
        ('ADMIN', 'Administrateur'),
    ]
    
    categories = [
        ('USERS', 'Utilisateurs'), ('KELIO', 'Kelio Sync'), ('FERIES', 'Jours Fériés'),
        ('INTERIM', 'Demandes Intérim'), ('VALIDATION', 'Validations'), ('PROPOSITIONS', 'Propositions'),
        ('NOTIFICATIONS', 'Notifications'), ('WORKFLOW', 'Workflow'), ('SYSTEM', 'Système'),
        ('DATABASE', 'Base de données'), ('PERFORMANCE', 'Performance'), ('LOGS', 'Journal'),
    ]
    
    severites = [('INFO', 'Information'), ('WARNING', 'Avertissement'), ('ERROR', 'Erreur'), ('CRITICAL', 'Critique')]
    sources_fichiers = [
        ('actions.log', 'Actions'), ('anomalies.log', 'Anomalies'), ('performance.log', 'Performance'),
        ('errors.log', 'Erreurs'), ('interim.log', 'Principal'),
    ]
    
    duree_ms = (time.time() - start_time) * 1000
    
    context = {
        'logs': logs_page, 'stats': stats, 'file_stats': file_stats,
        'repartition_categories': repartition_categories, 'repartition_severites': repartition_severites,
        'types_action': types_action, 'utilisateurs': utilisateurs, 'niveaux': niveaux,
        'categories': categories, 'severites': severites, 'sources_fichiers': sources_fichiers,
        'date_debut': date_debut, 'date_fin': date_fin, 'heure_debut': heure_debut, 'heure_fin': heure_fin,
        'type_action': type_action, 'category_filter': category_filter, 'severite_filter': severite_filter,
        'source_filter': source_filter, 'source_file_filter': source_file_filter,
        'utilisateur_id': utilisateur_id, 'recherche': recherche, 'niveau_hierarchique': niveau_hierarchique,
        'per_page': per_page,
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    
    return render(request, 'journal_logs.html', context)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_export(request, format_export):
    """Export des logs en CSV ou JSON"""
    import csv
    import json
    
    log_action('LOGS', 'EXPORT', f"Export logs format {format_export}", request=request)
    
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')
    heure_debut = request.GET.get('heure_debut', '00:00')
    heure_fin = request.GET.get('heure_fin', '23:59')
    type_action = request.GET.get('type_action', '')
    category_filter = request.GET.get('category', '')
    severite_filter = request.GET.get('severite', '')
    source_filter = request.GET.get('source', '')
    source_file_filter = request.GET.get('source_file', '')
    utilisateur_id = request.GET.get('utilisateur', '')
    recherche = request.GET.get('recherche', '').strip()
    
    logs_combined = []
    
    if source_filter != 'bdd':
        file_filters = {
            'category': category_filter, 'severite': severite_filter, 'recherche': recherche,
            'date_debut': date_debut, 'date_fin': date_fin, 'source_file': source_file_filter,
        }
        file_entries = get_all_log_entries(filters=file_filters, max_per_file=5000)
        for entry in file_entries:
            logs_combined.append({
                'date': entry['timestamp'], 'source': entry['source_file'], 'category': entry['category'],
                'action': entry['action'], 'severite': entry['severite'], 'utilisateur': entry['user'],
                'ip': entry['ip'], 'message': entry['message'],
            })
    
    if source_filter != 'file':
        logs_qs = HistoriqueAction.objects.select_related('utilisateur', 'utilisateur__user', 'demande').all()
        
        if date_debut:
            try:
                dt_debut = datetime.strptime(f"{date_debut} {heure_debut}", '%Y-%m-%d %H:%M')
                dt_debut = timezone.make_aware(dt_debut) if timezone.is_naive(dt_debut) else dt_debut
                logs_qs = logs_qs.filter(created_at__gte=dt_debut)
            except ValueError:
                pass
        if date_fin:
            try:
                dt_fin = datetime.strptime(f"{date_fin} {heure_fin}", '%Y-%m-%d %H:%M')
                dt_fin = timezone.make_aware(dt_fin) if timezone.is_naive(dt_fin) else dt_fin
                logs_qs = logs_qs.filter(created_at__lte=dt_fin)
            except ValueError:
                pass
        if type_action:
            logs_qs = logs_qs.filter(action=type_action)
        if utilisateur_id:
            logs_qs = logs_qs.filter(utilisateur_id=utilisateur_id)
        if recherche:
            logs_qs = logs_qs.filter(
                Q(description__icontains=recherche) | Q(demande__numero_demande__icontains=recherche) |
                Q(utilisateur__matricule__icontains=recherche)
            )
        
        logs_qs = logs_qs.order_by('-created_at')[:5000]
        for log in logs_qs:
            logs_combined.append({
                'date': log.created_at.strftime('%Y-%m-%d %H:%M:%S'), 'source': 'database', 'category': 'DATABASE',
                'action': log.get_action_display() if hasattr(log, 'get_action_display') else log.action,
                'severite': 'INFO', 'utilisateur': log.utilisateur.nom_complet if log.utilisateur else 'Système',
                'ip': log.adresse_ip or '-', 'message': log.description[:500],
            })
    
    logs_combined.sort(key=lambda x: x['date'], reverse=True)
    
    if format_export == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="journal_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        response.write('\ufeff')
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['Date/Heure', 'Source', 'Catégorie', 'Action', 'Sévérité', 'Utilisateur', 'IP', 'Message'])
        for log in logs_combined:
            writer.writerow([log['date'], log['source'], log['category'], log['action'], log['severite'],
                            log['utilisateur'], log['ip'], log['message'][:200]])
        return response
    
    elif format_export == 'json':
        response = HttpResponse(json.dumps(logs_combined, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="journal_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
        return response
    
    return HttpResponse("Format non supporté", status=400)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_detail(request, log_id):
    """Détail d'un log en JSON (pour modal AJAX)"""
    log_action('LOGS', 'DETAIL', f"Consultation détail log {log_id}", request=request)
    
    try:
        log = HistoriqueAction.objects.select_related(
            'utilisateur', 'utilisateur__user', 'demande', 'proposition', 'validation'
        ).get(pk=log_id)
        
        data = {
            'success': True,
            'log': {
                'id': log.id, 'source': 'database',
                'date': log.created_at.strftime('%d/%m/%Y %H:%M:%S'),
                'action': log.get_action_display() if hasattr(log, 'get_action_display') else log.action,
                'action_code': log.action, 'category': 'DATABASE', 'severite': 'INFO',
                'utilisateur': log.utilisateur.nom_complet if log.utilisateur else 'Système',
                'matricule': log.utilisateur.matricule if log.utilisateur else '-',
                'email': log.utilisateur.user.email if log.utilisateur and log.utilisateur.user else '-',
                'demande': log.demande.numero_demande if log.demande else '-',
                'demande_id': log.demande.id if log.demande else None,
                'description': log.description,
                'niveau_hierarchique': log.niveau_hierarchique or '-',
                'niveau_validation': getattr(log, 'niveau_validation', None),
                'adresse_ip': log.adresse_ip or '-',
                'user_agent': getattr(log, 'user_agent', '-') or '-',
                'is_superuser': getattr(log, 'is_superuser', False),
                'donnees_avant': getattr(log, 'donnees_avant', None),
                'donnees_apres': getattr(log, 'donnees_apres', None),
                'proposition_id': log.proposition.id if log.proposition else None,
                'validation_id': log.validation.id if log.validation else None,
            }
        }
        return JsonResponse(data)
        
    except HistoriqueAction.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Log non trouvé'}, status=404)
    except Exception as e:
        log_erreur('LOGS', "Erreur détail log", exception=e, request=request)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_fichiers_logs(request):
    """Vue pour afficher les fichiers de logs système"""
    log_action('LOGS', 'FICHIERS_LISTE', "Accès liste fichiers logs", request=request)
    
    logs_dir = _get_logs_directory()
    fichiers_logs = []
    
    try:
        if os.path.exists(logs_dir):
            for filename in os.listdir(logs_dir):
                filepath = os.path.join(logs_dir, filename)
                if os.path.isfile(filepath) and filename.endswith('.log'):
                    stat = os.stat(filepath)
                    
                    if 'actions' in filename:
                        type_log, icone, couleur = 'Actions', 'fa-play-circle', 'success'
                    elif 'anomalies' in filename:
                        type_log, icone, couleur = 'Anomalies', 'fa-exclamation-triangle', 'warning'
                    elif 'errors' in filename:
                        type_log, icone, couleur = 'Erreurs', 'fa-times-circle', 'danger'
                    elif 'performance' in filename:
                        type_log, icone, couleur = 'Performance', 'fa-tachometer-alt', 'info'
                    elif 'interim' in filename:
                        type_log, icone, couleur = 'Principal', 'fa-file-alt', 'primary'
                    else:
                        type_log, icone, couleur = 'Autre', 'fa-file', 'secondary'
                    
                    fichiers_logs.append({
                        'nom': filename, 'type_log': type_log, 'icone': icone, 'couleur': couleur,
                        'taille': stat.st_size, 'taille_human': _format_size(stat.st_size),
                        'modifie': datetime.fromtimestamp(stat.st_mtime), 'lignes': _count_lines(filepath),
                    })
            fichiers_logs.sort(key=lambda x: x['modifie'], reverse=True)
    except Exception as e:
        log_erreur('LOGS', "Erreur lecture répertoire logs", exception=e, request=request)
    
    context = {
        'fichiers_logs': fichiers_logs, 'logs_dir': str(logs_dir),
        'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
    }
    return render(request, 'journal_fichiers_logs.html', context)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_fichier_contenu(request, filename):
    """Affiche le contenu d'un fichier de log (avec pagination et filtres)"""
    log_action('LOGS', 'FICHIER_CONTENU', f"Lecture fichier {filename}", request=request)
    
    logs_dir = _get_logs_directory()
    filepath = os.path.join(logs_dir, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(str(logs_dir))):
        return HttpResponse("Accès non autorisé", status=403)
    if not os.path.exists(filepath):
        return HttpResponse("Fichier non trouvé", status=404)
    
    lignes_par_page = int(request.GET.get('lignes', 100))
    page = int(request.GET.get('page', 1))
    recherche = request.GET.get('recherche', '').strip()
    niveau = request.GET.get('niveau', '')
    category = request.GET.get('category', '')
    
    try:
        entries = read_log_file(filepath, max_lines=50000)
        
        if recherche:
            entries = [e for e in entries if recherche.lower() in e['raw'].lower()]
        if niveau:
            entries = [e for e in entries if e['severite'] == niveau.upper()]
        if category:
            entries = [e for e in entries if e['category'] == category.upper()]
        
        total_entries = len(entries)
        total_pages = (total_entries + lignes_par_page - 1) // lignes_par_page
        debut = (page - 1) * lignes_par_page
        fin = debut + lignes_par_page
        entries_page = entries[debut:fin]
        
        all_categories = list(set(e['category'] for e in entries[:1000]))
        
        context = {
            'filename': filename, 'entries': entries_page, 'page': page, 'total_pages': total_pages,
            'total_entries': total_entries, 'lignes_par_page': lignes_par_page, 'recherche': recherche,
            'niveau': niveau, 'category': category, 'all_categories': sorted(all_categories),
            'profil_utilisateur': request.user.profilutilisateur if hasattr(request.user, 'profilutilisateur') else None,
        }
        return render(request, 'journal_fichier_contenu.html', context)
        
    except Exception as e:
        log_erreur('LOGS', f"Erreur lecture fichier {filename}", exception=e, request=request)
        return HttpResponse(f"Erreur: {str(e)}", status=500)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_stats_api(request):
    """API pour les statistiques de logs en temps réel"""
    try:
        logs_dir = _get_logs_directory()
        today = timezone.now().date()
        
        file_stats = {}
        for lf in ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']:
            filepath = os.path.join(logs_dir, lf)
            if os.path.exists(filepath):
                stat = os.stat(filepath)
                file_stats[lf] = {
                    'taille': stat.st_size, 'taille_human': _format_size(stat.st_size),
                    'modifie': datetime.fromtimestamp(stat.st_mtime).isoformat(), 'lignes': _count_lines(filepath),
                }
        
        bdd_stats = {
            'total': HistoriqueAction.objects.count(),
            'aujourd_hui': HistoriqueAction.objects.filter(created_at__date=today).count(),
            'cette_semaine': HistoriqueAction.objects.filter(created_at__gte=today - timedelta(days=7)).count(),
        }
        
        anomalies_recentes = []
        anomalies_path = os.path.join(logs_dir, 'anomalies.log')
        if os.path.exists(anomalies_path):
            entries = read_log_file(anomalies_path, max_lines=10)
            for e in entries[:5]:
                anomalies_recentes.append({
                    'timestamp': e['timestamp'], 'category': e['category'],
                    'severite': e['severite'], 'message': e['message'][:100],
                })
        
        return JsonResponse({
            'success': True, 'file_stats': file_stats, 'bdd_stats': bdd_stats,
            'anomalies_recentes': anomalies_recentes, 'timestamp': timezone.now().isoformat(),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ================================================================
# TÉLÉCHARGEMENT ZIP DES LOGS
# ================================================================

@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_download_zip(request):
    """
    Télécharge tous les fichiers de logs dans une archive ZIP
    Paramètres GET optionnels:
    - files: liste de fichiers séparés par virgule (ex: actions.log,errors.log)
    - include_rotated: inclure les fichiers de rotation (.log.1, .log.2, etc.)
    """
    import zipfile
    from io import BytesIO
    
    log_action('LOGS', 'DOWNLOAD_ZIP', "Téléchargement archive ZIP des logs", request=request)
    
    try:
        logs_dir = _get_logs_directory()
        
        # Paramètres
        files_filter = request.GET.get('files', '')
        include_rotated = request.GET.get('include_rotated', 'false').lower() == 'true'
        
        # Liste des fichiers à inclure
        files_to_include = []
        
        if files_filter:
            # Fichiers spécifiques demandés
            requested_files = [f.strip() for f in files_filter.split(',')]
        else:
            # Tous les fichiers .log principaux
            requested_files = ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']
        
        if os.path.exists(logs_dir):
            for filename in os.listdir(logs_dir):
                filepath = os.path.join(logs_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                
                # Vérifier si c'est un fichier log demandé
                is_main_log = filename in requested_files
                is_rotated = include_rotated and any(filename.startswith(f.replace('.log', '')) and '.log' in filename for f in requested_files)
                
                if is_main_log or is_rotated:
                    files_to_include.append({
                        'name': filename,
                        'path': filepath,
                        'size': os.path.getsize(filepath)
                    })
        
        if not files_to_include:
            return JsonResponse({
                'success': False,
                'message': 'Aucun fichier de log trouvé'
            }, status=404)
        
        # Créer l'archive ZIP en mémoire
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_info in files_to_include:
                # Ajouter le fichier au ZIP
                zip_file.write(file_info['path'], file_info['name'])
        
        zip_buffer.seek(0)
        
        # Générer le nom du fichier
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"logs_interim365_{timestamp}.zip"
        
        # Créer la réponse HTTP
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
        response['Content-Length'] = len(zip_buffer.getvalue())
        
        # Log du succès
        total_size = sum(f['size'] for f in files_to_include)
        log_action('LOGS', 'DOWNLOAD_ZIP_OK', 
                  f"Archive ZIP créée: {len(files_to_include)} fichiers, {_format_size(total_size)}",
                  request=request, fichiers=len(files_to_include))
        
        return response
        
    except Exception as e:
        log_erreur('LOGS', "Erreur création archive ZIP", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'message': f'Erreur lors de la création de l\'archive: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_download_file(request, filename):
    """
    Télécharge un fichier de log spécifique
    """
    log_action('LOGS', 'DOWNLOAD_FILE', f"Téléchargement fichier {filename}", request=request)
    
    logs_dir = _get_logs_directory()
    filepath = os.path.join(logs_dir, filename)
    
    # Sécurité: vérifier que le fichier est dans le répertoire logs
    if not os.path.abspath(filepath).startswith(os.path.abspath(str(logs_dir))):
        log_anomalie('LOGS', f"Tentative accès non autorisé: {filename}", severite='WARNING', request=request)
        return HttpResponse("Accès non autorisé", status=403)
    
    if not os.path.exists(filepath):
        return HttpResponse("Fichier non trouvé", status=404)
    
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(content)
        
        return response
        
    except Exception as e:
        log_erreur('LOGS', f"Erreur téléchargement fichier {filename}", exception=e, request=request)
        return HttpResponse(f"Erreur: {str(e)}", status=500)


# ================================================================
# PURGE DES LOGS
# ================================================================

@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_purge(request):
    """
    Purge les fichiers de logs
    
    POST avec JSON body:
    - mode: 'truncate' (vider les fichiers) ou 'delete_rotated' (supprimer fichiers rotation)
    - files: liste des fichiers à purger (optionnel, tous par défaut)
    - jours_retention: nombre de jours à conserver pour delete_rotated (défaut: 7)
    - confirm: doit être True pour exécuter
    """
    import json
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Méthode POST requise'}, status=405)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'JSON invalide'}, status=400)
    
    mode = data.get('mode', 'truncate')
    files_to_purge = data.get('files', [])
    jours_retention = int(data.get('jours_retention', 7))
    confirm = data.get('confirm', False)
    
    if not confirm:
        return JsonResponse({
            'success': False,
            'message': 'Confirmation requise (confirm: true)'
        }, status=400)
    
    if jours_retention < 1:
        return JsonResponse({
            'success': False,
            'message': 'jours_retention doit être >= 1'
        }, status=400)
    
    log_action('LOGS', 'PURGE_DEMANDE', f"Demande purge mode={mode}", request=request, 
              mode=mode, jours_retention=jours_retention)
    
    logs_dir = _get_logs_directory()
    results = {
        'fichiers_purges': [],
        'fichiers_supprimes': [],
        'erreurs': [],
        'espace_libere': 0
    }
    
    try:
        if not os.path.exists(logs_dir):
            return JsonResponse({
                'success': False,
                'message': f'Répertoire logs non trouvé: {logs_dir}'
            }, status=404)
        
        # Liste des fichiers log principaux
        main_log_files = ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']
        
        if not files_to_purge:
            files_to_purge = main_log_files
        
        if mode == 'truncate':
            # Mode: Vider les fichiers (les garder mais avec contenu vide)
            for filename in files_to_purge:
                filepath = os.path.join(logs_dir, filename)
                if os.path.exists(filepath) and os.path.isfile(filepath):
                    try:
                        # Récupérer la taille avant
                        size_before = os.path.getsize(filepath)
                        
                        # Vider le fichier
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"# Log purgé le {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} par {request.user.username}\n")
                        
                        results['fichiers_purges'].append({
                            'nom': filename,
                            'taille_avant': _format_size(size_before)
                        })
                        results['espace_libere'] += size_before
                        
                    except Exception as e:
                        results['erreurs'].append({
                            'fichier': filename,
                            'erreur': str(e)
                        })
        
        elif mode == 'delete_rotated':
            # Mode: Supprimer les fichiers de rotation anciens
            date_limite = datetime.now() - timedelta(days=jours_retention)
            
            for filename in os.listdir(logs_dir):
                filepath = os.path.join(logs_dir, filename)
                
                if not os.path.isfile(filepath):
                    continue
                
                # Vérifier si c'est un fichier de rotation (ex: actions.log.1, actions.log.2)
                is_rotated = False
                for main_file in main_log_files:
                    base_name = main_file.replace('.log', '')
                    if filename.startswith(base_name) and filename != main_file and '.log' in filename:
                        is_rotated = True
                        break
                
                if not is_rotated:
                    continue
                
                # Vérifier la date de modification
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    
                    if mtime < date_limite:
                        size = os.path.getsize(filepath)
                        os.remove(filepath)
                        
                        results['fichiers_supprimes'].append({
                            'nom': filename,
                            'taille': _format_size(size),
                            'date_modif': mtime.strftime('%Y-%m-%d %H:%M')
                        })
                        results['espace_libere'] += size
                        
                except Exception as e:
                    results['erreurs'].append({
                        'fichier': filename,
                        'erreur': str(e)
                    })
        
        elif mode == 'delete_all_rotated':
            # Mode: Supprimer TOUS les fichiers de rotation
            for filename in os.listdir(logs_dir):
                filepath = os.path.join(logs_dir, filename)
                
                if not os.path.isfile(filepath):
                    continue
                
                # Vérifier si c'est un fichier de rotation
                is_rotated = False
                for main_file in main_log_files:
                    base_name = main_file.replace('.log', '')
                    if filename.startswith(base_name) and filename != main_file and '.log' in filename:
                        is_rotated = True
                        break
                
                if not is_rotated:
                    continue
                
                try:
                    size = os.path.getsize(filepath)
                    os.remove(filepath)
                    
                    results['fichiers_supprimes'].append({
                        'nom': filename,
                        'taille': _format_size(size)
                    })
                    results['espace_libere'] += size
                    
                except Exception as e:
                    results['erreurs'].append({
                        'fichier': filename,
                        'erreur': str(e)
                    })
        
        else:
            return JsonResponse({
                'success': False,
                'message': f"Mode inconnu: {mode}. Modes valides: truncate, delete_rotated, delete_all_rotated"
            }, status=400)
        
        # Résumé
        results['espace_libere_human'] = _format_size(results['espace_libere'])
        
        log_action('LOGS', 'PURGE_OK', 
                  f"Purge réussie: {len(results['fichiers_purges'])} vidés, {len(results['fichiers_supprimes'])} supprimés, {results['espace_libere_human']} libérés",
                  request=request)
        
        log_resume('PURGE_LOGS', {
            'mode': mode,
            'fichiers_purges': len(results['fichiers_purges']),
            'fichiers_supprimes': len(results['fichiers_supprimes']),
            'erreurs': len(results['erreurs']),
            'espace_libere': results['espace_libere_human'],
        })
        
        return JsonResponse({
            'success': True,
            'message': f"Purge effectuée avec succès",
            'results': results
        })
        
    except Exception as e:
        log_erreur('LOGS', "Erreur purge logs", exception=e, request=request)
        return JsonResponse({
            'success': False,
            'message': f'Erreur lors de la purge: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(is_admin_or_rh)
def journal_logs_purge_info(request):
    """
    Retourne les informations pour la purge (tailles, fichiers de rotation, etc.)
    Utile pour afficher une confirmation avant purge
    """
    logs_dir = _get_logs_directory()
    
    info = {
        'logs_dir': str(logs_dir),
        'fichiers_principaux': [],
        'fichiers_rotation': [],
        'taille_totale': 0,
        'taille_rotation': 0,
    }
    
    main_log_files = ['actions.log', 'anomalies.log', 'performance.log', 'errors.log', 'interim.log']
    
    try:
        if os.path.exists(logs_dir):
            for filename in os.listdir(logs_dir):
                filepath = os.path.join(logs_dir, filename)
                
                if not os.path.isfile(filepath):
                    continue
                
                if not '.log' in filename:
                    continue
                
                stat = os.stat(filepath)
                file_info = {
                    'nom': filename,
                    'taille': stat.st_size,
                    'taille_human': _format_size(stat.st_size),
                    'date_modif': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'lignes': _count_lines(filepath)
                }
                
                if filename in main_log_files:
                    info['fichiers_principaux'].append(file_info)
                    info['taille_totale'] += stat.st_size
                else:
                    # Fichier de rotation
                    info['fichiers_rotation'].append(file_info)
                    info['taille_rotation'] += stat.st_size
                    info['taille_totale'] += stat.st_size
        
        info['taille_totale_human'] = _format_size(info['taille_totale'])
        info['taille_rotation_human'] = _format_size(info['taille_rotation'])
        info['nb_fichiers_rotation'] = len(info['fichiers_rotation'])
        
        # Trier par taille décroissante
        info['fichiers_principaux'].sort(key=lambda x: x['taille'], reverse=True)
        info['fichiers_rotation'].sort(key=lambda x: x['taille'], reverse=True)
        
        return JsonResponse({
            'success': True,
            'info': info
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)