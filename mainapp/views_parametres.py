# views_parametres.py
"""
Vues pour la gestion des paramètres globaux et workflow.
Adapté aux modèles existants (ConfigurationApiKelio, ConfigurationScoring, etc.)
"""

import json
import logging
from datetime import datetime, timedelta
from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError

from .models import (
    ProfilUtilisateur, Departement, Site, Poste, MotifAbsence,
    ConfigurationApiKelio, ConfigurationScoring, CacheApiKelio, WorkflowEtape,
)

logger = logging.getLogger('interim')
logger_actions = logging.getLogger('interim.actions')
logger_security = logging.getLogger('interim.security')


# ================================================================
# DÉCORATEURS ET UTILITAIRES
# ================================================================

def admin_required(view_func):
    """Décorateur pour restreindre l'accès aux administrateurs"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Vous devez être connecté.")
            return redirect('connexion')
        
        try:
            profil = request.user.profilutilisateur
            if profil.type_profil not in ['ADMIN', 'RH', 'SUPERUSER']:
                logger_security.warning(f"Accès refusé - {request.user.username} -> {request.path}")
                messages.error(request, "Accès non autorisé.")
                return redirect('index')
        except ProfilUtilisateur.DoesNotExist:
            messages.error(request, "Profil utilisateur non trouvé.")
            return redirect('index')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def log_action(user, action, details=""):
    """Enregistre une action utilisateur"""
    msg = f"[{user.username}] {action}"
    if details:
        msg += f" - {details}"
    logger_actions.info(msg)


def get_context_base(request):
    """Contexte de base pour les templates"""
    return {
        'profil_utilisateur': request.user.profilutilisateur,
        'today': timezone.now().date(),
        'now': timezone.now(),
    }


# ================================================================
# DASHBOARD PARAMÈTRES
# ================================================================

@login_required
@admin_required
def parametres_dashboard(request):
    """Dashboard principal des paramètres"""
    context = get_context_base(request)
    
    context['stats'] = {
        'departements_count': Departement.objects.filter(actif=True).count(),
        'departements_total': Departement.objects.count(),
        'sites_count': Site.objects.filter(actif=True).count(),
        'sites_total': Site.objects.count(),
        'postes_count': Poste.objects.filter(actif=True).count(),
        'postes_total': Poste.objects.count(),
        'motifs_count': MotifAbsence.objects.filter(actif=True).count(),
        'motifs_total': MotifAbsence.objects.count(),
        'workflow_etapes': WorkflowEtape.objects.filter(actif=True).count(),
        'cache_entries': CacheApiKelio.objects.count(),
    }
    
    context['config_kelio'] = ConfigurationApiKelio.objects.filter(actif=True).first()
    context['config_scoring'] = ConfigurationScoring.objects.filter(configuration_par_defaut=True).first()
    
    log_action(request.user, "Accès dashboard paramètres")
    return render(request, 'parametres/dashboard.html', context)


# ================================================================
# CONFIGURATION API KELIO (SINGLETON - Une seule configuration)
# ================================================================

@login_required
@admin_required
def config_kelio_liste(request):
    """Affichage de la configuration unique API Kelio"""
    context = get_context_base(request)
    
    # Récupérer la configuration unique (singleton)
    config = ConfigurationApiKelio.objects.first()
    context['config'] = config
    
    # Statistiques du cache
    if config:
        context['stats_cache'] = {
            'total': CacheApiKelio.objects.filter(configuration=config).count(),
        }
    
    return render(request, 'parametres/config_kelio/liste.html', context)


@login_required
@admin_required
def config_kelio_modifier(request):
    """Créer ou modifier la configuration unique API Kelio"""
    context = get_context_base(request)
    
    # Récupérer la configuration existante ou None
    config = ConfigurationApiKelio.objects.first()
    is_new = config is None
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    config = ConfigurationApiKelio()
                
                config.nom = request.POST.get('nom', 'Configuration Kelio').strip()
                config.url_base = request.POST.get('url_base', '').strip()
                config.username = request.POST.get('username', '').strip()
                
                # Mot de passe crypté (seulement si fourni)
                new_password = request.POST.get('password', '').strip()
                if new_password:
                    config.set_password(new_password)
                
                config.timeout_seconds = int(request.POST.get('timeout_seconds', 30))
                
                # Services
                config.service_employees = request.POST.get('service_employees') == 'on'
                config.service_absences = request.POST.get('service_absences') == 'on'
                config.service_formations = request.POST.get('service_formations') == 'on'
                config.service_competences = request.POST.get('service_competences') == 'on'
                
                # Cache
                config.cache_duree_defaut_minutes = int(request.POST.get('cache_duree_defaut_minutes', 60))
                config.cache_taille_max_mo = int(request.POST.get('cache_taille_max_mo', 100))
                config.auto_invalidation_cache = request.POST.get('auto_invalidation_cache') == 'on'
                
                config.actif = request.POST.get('actif') == 'on'
                
                config.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} config Kelio", f"Nom: {config.nom}")
                messages.success(request, f"Configuration API Kelio {'créée' if is_new else 'modifiée'} avec succès.")
                return redirect('config_kelio_liste')
                
        except Exception as e:
            logger.error(f"Erreur config Kelio: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['config'] = config
    context['is_new'] = is_new
    return render(request, 'parametres/config_kelio/form.html', context)


@login_required
@admin_required
@require_POST
def config_kelio_toggle_actif(request):
    """Activer/désactiver la configuration Kelio"""
    try:
        config = ConfigurationApiKelio.objects.first()
        if not config:
            return JsonResponse({'success': False, 'message': "Aucune configuration trouvée."})
        
        config.actif = not config.actif
        config.save()
        
        action = "activée" if config.actif else "désactivée"
        log_action(request.user, f"Configuration Kelio {action}")
        
        return JsonResponse({
            'success': True, 
            'actif': config.actif,
            'message': f"Configuration {action} avec succès."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def config_kelio_tester(request):
    """
    Tester la connexion API Kelio en utilisant les fonctions de kelio_sync_v43.py
    Effectue une vérification complète: configuration, SOAP, et connexion
    """
    import time
    start_time = time.time()
    
    try:
        # Import des fonctions de kelio_sync_v43
        try:
            from .services.kelio_sync_v43 import (
                verifier_configuration_kelio_v43,
                diagnostic_kelio_v43,
                KelioSyncServiceV43,
                SOAP_AVAILABLE
            )
            kelio_module_available = True
        except ImportError as e:
            kelio_module_available = False
            logger.warning(f"Module kelio_sync_v43 non disponible: {e}")
        
        # Récupérer la configuration active
        config = ConfigurationApiKelio.objects.filter(actif=True).first()
        if not config:
            return JsonResponse({
                'success': False,
                'message': "Aucune configuration API Kelio active trouvée.",
                'recommandations': [
                    "Créez une configuration dans les paramètres",
                    "Activez la configuration créée"
                ]
            })
        
        resultats_tests = []
        
        # Test 1: Vérification de la configuration de base
        test_config = {
            'nom': 'Configuration de base',
            'success': True,
            'details': []
        }
        
        if not config.url_base:
            test_config['success'] = False
            test_config['details'].append("URL de base manquante")
        else:
            test_config['details'].append(f"URL: {config.url_base}")
            
        if not config.username:
            test_config['success'] = False
            test_config['details'].append("Nom d'utilisateur manquant")
        else:
            test_config['details'].append(f"Utilisateur: {config.username}")
            
        if not config.password_encrypted:
            test_config['success'] = False
            test_config['details'].append("Mot de passe non configuré")
        else:
            test_config['details'].append("Mot de passe: ••••••••")
            
        resultats_tests.append(test_config)
        
        # Test 2: Vérification des dépendances SOAP (si module disponible)
        if kelio_module_available:
            test_soap = {
                'nom': 'Dépendances SOAP',
                'success': SOAP_AVAILABLE,
                'details': ["zeep et requests installés" if SOAP_AVAILABLE else "zeep ou requests manquant"]
            }
            resultats_tests.append(test_soap)
            
            # Test 3: Vérification avancée via kelio_sync_v43
            try:
                config_check = verifier_configuration_kelio_v43()
                test_kelio = {
                    'nom': 'Vérification Kelio V4.3',
                    'success': config_check.get('valide', False),
                    'details': []
                }
                
                if config_check.get('tests'):
                    for t in config_check['tests']:
                        status = "✓" if t.get('resultat') else "✗"
                        test_kelio['details'].append(f"{status} {t.get('test')}")
                        
                if config_check.get('erreur'):
                    test_kelio['details'].append(f"Erreur: {config_check['erreur']}")
                    
                resultats_tests.append(test_kelio)
            except Exception as e:
                resultats_tests.append({
                    'nom': 'Vérification Kelio V4.3',
                    'success': False,
                    'details': [f"Erreur: {str(e)}"]
                })
        
        # Test 4: Test de connexion HTTP basique à l'URL
        test_http = {
            'nom': 'Connexion HTTP',
            'success': False,
            'details': []
        }
        
        try:
            import requests
            from requests.auth import HTTPBasicAuth
            
            # Tenter une connexion basique
            response = requests.get(
                config.url_base,
                auth=HTTPBasicAuth(config.username, config.get_password()),
                timeout=config.timeout_seconds,
                verify=True  # Vérification SSL
            )
            
            test_http['details'].append(f"Code HTTP: {response.status_code}")
            test_http['details'].append(f"Temps réponse: {response.elapsed.total_seconds():.2f}s")
            
            if response.status_code in [200, 401, 403]:
                # 200 = OK, 401/403 = Auth requise (serveur répond)
                test_http['success'] = True
                if response.status_code == 200:
                    test_http['details'].append("Serveur accessible et authentification OK")
                elif response.status_code in [401, 403]:
                    test_http['details'].append("Serveur accessible (vérifier les credentials)")
            else:
                test_http['details'].append(f"Réponse inattendue du serveur")
                
        except requests.exceptions.Timeout:
            test_http['details'].append(f"Timeout après {config.timeout_seconds}s")
        except requests.exceptions.SSLError as e:
            test_http['details'].append(f"Erreur SSL: {str(e)[:100]}")
        except requests.exceptions.ConnectionError:
            test_http['details'].append("Impossible de se connecter au serveur")
        except Exception as e:
            test_http['details'].append(f"Erreur: {str(e)[:100]}")
            
        resultats_tests.append(test_http)
        
        # Test 5: Test SOAP (création client) si module disponible
        if kelio_module_available and SOAP_AVAILABLE:
            test_soap_client = {
                'nom': 'Client SOAP Kelio',
                'success': False,
                'details': []
            }
            
            try:
                service = KelioSyncServiceV43(config)
                # Essayer de créer un client pour un service basique
                client = service._get_soap_client_ultra_robust('EmployeeService')
                
                if client:
                    test_soap_client['success'] = True
                    test_soap_client['details'].append("Client SOAP créé avec succès")
                    test_soap_client['details'].append("Service EmployeeService accessible")
                else:
                    test_soap_client['details'].append("Impossible de créer le client SOAP")
                    
            except Exception as e:
                error_msg = str(e)[:150]
                test_soap_client['details'].append(f"Erreur: {error_msg}")
                
            resultats_tests.append(test_soap_client)
        
        # Calcul du résultat global
        elapsed_time = time.time() - start_time
        tests_reussis = sum(1 for t in resultats_tests if t['success'])
        tests_total = len(resultats_tests)
        success_global = all(t['success'] for t in resultats_tests[:3])  # Les 3 premiers tests sont critiques
        
        log_action(request.user, "Test connexion API Kelio", 
                   f"Résultat: {'OK' if success_global else 'ÉCHEC'} ({tests_reussis}/{tests_total} tests)")
        
        return JsonResponse({
            'success': success_global,
            'message': f"Connexion {'réussie' if success_global else 'échouée'} - {tests_reussis}/{tests_total} tests passés",
            'tests': resultats_tests,
            'configuration': {
                'nom': config.nom,
                'url': config.url_base,
                'timeout': config.timeout_seconds
            },
            'temps_execution': f"{elapsed_time:.2f}s"
        })
        
    except Exception as e:
        logger.error(f"Erreur test API Kelio: {e}")
        return JsonResponse({
            'success': False,
            'message': f"Erreur lors du test: {str(e)}",
            'temps_execution': f"{time.time() - start_time:.2f}s"
        })


@login_required
@admin_required
@require_POST
def config_kelio_vider_cache(request, pk=None):
    """Vider le cache de la configuration Kelio (singleton)"""
    try:
        config = ConfigurationApiKelio.objects.first()
        if not config:
            return JsonResponse({'success': False, 'message': "Aucune configuration trouvée."})
        
        count = config.vider_cache()
        log_action(request.user, "Vidage cache Kelio", f"Entrées supprimées: {count}")
        return JsonResponse({'success': True, 'message': f"{count} entrées de cache supprimées."})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def lancer_sync_kelio(request):
    """Lancer une synchronisation Kelio (appel asynchrone)"""
    try:
        # Import des fonctions de synchronisation
        try:
            from .services.kelio_sync_v43 import synchroniser_tous_employes_kelio_v43_production
            
            # Lancer la synchronisation
            result = synchroniser_tous_employes_kelio_v43_production()
            
            log_action(request.user, "Lancement synchronisation Kelio", 
                       f"Statut: {result.get('statut_global', 'inconnu')}")
            
            return JsonResponse({
                'success': result.get('statut_global') != 'erreur_critique',
                'message': f"Synchronisation terminée. Statut: {result.get('statut_global', 'inconnu')}",
                'details': result
            })
            
        except ImportError:
            return JsonResponse({
                'success': False,
                'message': "Module de synchronisation Kelio non disponible."
            })
            
    except Exception as e:
        logger.error(f"Erreur lancement sync Kelio: {e}")
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# CONFIGURATION SCORING (SINGLETON - Une seule configuration)
# ================================================================

@login_required
@admin_required
def config_scoring_liste(request):
    """Affichage de la configuration unique de scoring"""
    context = get_context_base(request)
    
    # Récupérer la configuration unique (singleton)
    config = ConfigurationScoring.objects.first()
    context['config'] = config
    
    return render(request, 'parametres/config_scoring/liste.html', context)


@login_required
@admin_required
def config_scoring_modifier(request):
    """Créer ou modifier la configuration unique de scoring"""
    context = get_context_base(request)
    
    # Récupérer la configuration existante ou None
    config = ConfigurationScoring.objects.first()
    is_new = config is None
    
    if request.method == 'POST':
        try:
            # DEBUG: Afficher les données POST reçues
            logger.info(f"=== CONFIG SCORING POST DATA ===")
            for key, value in request.POST.items():
                logger.info(f"  {key}: {value}")
            
            # Récupérer les valeurs du formulaire
            nom = request.POST.get('nom', 'Barèmes de scoring').strip() or 'Barèmes de scoring'
            description = request.POST.get('description', '').strip()
            
            # Poids
            poids_similarite_poste = float(request.POST.get('poids_similarite_poste') or 0.25)
            poids_competences = float(request.POST.get('poids_competences') or 0.25)
            poids_experience = float(request.POST.get('poids_experience') or 0.20)
            poids_disponibilite = float(request.POST.get('poids_disponibilite') or 0.15)
            poids_proximite = float(request.POST.get('poids_proximite') or 0.10)
            poids_anciennete = float(request.POST.get('poids_anciennete') or 0.05)
            
            # Vérifier total poids
            total_poids = poids_similarite_poste + poids_competences + poids_experience + poids_disponibilite + poids_proximite + poids_anciennete
            logger.info(f"Total poids: {total_poids}")
            
            if abs(total_poids - 1.0) > 0.01:
                messages.error(request, f"Le total des poids doit être égal à 100% (actuellement {total_poids*100:.0f}%)")
                context['config'] = config
                context['is_new'] = is_new
                context['departements'] = Departement.objects.filter(actif=True)
                return render(request, 'parametres/config_scoring/form.html', context)
            
            # Bonus
            bonus_proposition_humaine = int(request.POST.get('bonus_proposition_humaine') or 5)
            bonus_experience_similaire = int(request.POST.get('bonus_experience_similaire') or 8)
            bonus_recommandation = int(request.POST.get('bonus_recommandation') or 10)
            bonus_manager_direct = int(request.POST.get('bonus_manager_direct') or 12)
            bonus_chef_equipe = int(request.POST.get('bonus_chef_equipe') or 8)
            bonus_responsable = int(request.POST.get('bonus_responsable') or 15)
            bonus_directeur = int(request.POST.get('bonus_directeur') or 18)
            bonus_rh = int(request.POST.get('bonus_rh') or 20)
            bonus_admin = int(request.POST.get('bonus_admin') or 20)
            bonus_superuser = int(request.POST.get('bonus_superuser') or 0)
            
            # Pénalités
            penalite_indisponibilite_partielle = int(request.POST.get('penalite_indisponibilite_partielle') or 15)
            penalite_indisponibilite_totale = int(request.POST.get('penalite_indisponibilite_totale') or 50)
            penalite_distance_excessive = int(request.POST.get('penalite_distance_excessive') or 10)
            
            # Options
            pour_types_urgence = request.POST.get('pour_types_urgence', '')
            actif = request.POST.get('actif') == 'on'
            
            logger.info(f"Valeurs parsées: nom={nom}, actif={actif}, poids_similarite={poids_similarite_poste}")
            
            if is_new:
                # CRÉATION: Utiliser create() qui est plus direct
                logger.info("Création nouvelle config...")
                
                # D'abord désactiver toutes les configs par défaut existantes
                ConfigurationScoring.objects.all().update(configuration_par_defaut=False)
                
                config = ConfigurationScoring.objects.create(
                    nom=nom,
                    description=description,
                    poids_similarite_poste=poids_similarite_poste,
                    poids_competences=poids_competences,
                    poids_experience=poids_experience,
                    poids_disponibilite=poids_disponibilite,
                    poids_proximite=poids_proximite,
                    poids_anciennete=poids_anciennete,
                    bonus_proposition_humaine=bonus_proposition_humaine,
                    bonus_experience_similaire=bonus_experience_similaire,
                    bonus_recommandation=bonus_recommandation,
                    bonus_manager_direct=bonus_manager_direct,
                    bonus_chef_equipe=bonus_chef_equipe,
                    bonus_responsable=bonus_responsable,
                    bonus_directeur=bonus_directeur,
                    bonus_rh=bonus_rh,
                    bonus_admin=bonus_admin,
                    bonus_superuser=bonus_superuser,
                    penalite_indisponibilite_partielle=penalite_indisponibilite_partielle,
                    penalite_indisponibilite_totale=penalite_indisponibilite_totale,
                    penalite_distance_excessive=penalite_distance_excessive,
                    pour_types_urgence=pour_types_urgence,
                    actif=actif,
                    configuration_par_defaut=True,
                )
                logger.info(f"Config créée avec pk={config.pk}")
                
            else:
                # MODIFICATION: Utiliser update() directement sur le QuerySet
                logger.info(f"Modification config pk={config.pk}...")
                
                # D'abord désactiver toutes les configs par défaut
                ConfigurationScoring.objects.all().update(configuration_par_defaut=False)
                
                # Puis mettre à jour la config actuelle
                rows_updated = ConfigurationScoring.objects.filter(pk=config.pk).update(
                    nom=nom,
                    description=description,
                    poids_similarite_poste=poids_similarite_poste,
                    poids_competences=poids_competences,
                    poids_experience=poids_experience,
                    poids_disponibilite=poids_disponibilite,
                    poids_proximite=poids_proximite,
                    poids_anciennete=poids_anciennete,
                    bonus_proposition_humaine=bonus_proposition_humaine,
                    bonus_experience_similaire=bonus_experience_similaire,
                    bonus_recommandation=bonus_recommandation,
                    bonus_manager_direct=bonus_manager_direct,
                    bonus_chef_equipe=bonus_chef_equipe,
                    bonus_responsable=bonus_responsable,
                    bonus_directeur=bonus_directeur,
                    bonus_rh=bonus_rh,
                    bonus_admin=bonus_admin,
                    bonus_superuser=bonus_superuser,
                    penalite_indisponibilite_partielle=penalite_indisponibilite_partielle,
                    penalite_indisponibilite_totale=penalite_indisponibilite_totale,
                    penalite_distance_excessive=penalite_distance_excessive,
                    pour_types_urgence=pour_types_urgence,
                    actif=actif,
                    configuration_par_defaut=True,
                )
                logger.info(f"Rows updated: {rows_updated}")
                
                # Vérifier que la mise à jour a fonctionné
                config_verif = ConfigurationScoring.objects.filter(pk=config.pk).first()
                if config_verif:
                    logger.info(f"Vérification après update: nom={config_verif.nom}, poids_similarite={config_verif.poids_similarite_poste}")
            
            # M2M pour départements
            if hasattr(config, 'pour_departements'):
                dept_ids = request.POST.getlist('pour_departements')
                if dept_ids:
                    config.pour_departements.set(dept_ids)
                else:
                    config.pour_departements.clear()
            
            log_action(request.user, f"{'Création' if is_new else 'Modification'} config scoring", f"Nom: {nom}")
            messages.success(request, f"Configuration de scoring {'créée' if is_new else 'modifiée'} avec succès.")
            return redirect('config_scoring_liste')
            
        except Exception as e:
            logger.error(f"Erreur config scoring: {e}", exc_info=True)
            messages.error(request, f"Erreur: {str(e)}")
    
    context['config'] = config
    context['is_new'] = is_new
    context['departements'] = Departement.objects.filter(actif=True)
    
    return render(request, 'parametres/config_scoring/form.html', context)


@login_required
@admin_required
@require_POST
def config_scoring_toggle_actif(request):
    """Activer/désactiver la configuration de scoring"""
    try:
        config = ConfigurationScoring.objects.first()
        if not config:
            return JsonResponse({'success': False, 'message': "Aucune configuration trouvée."})
        
        config.actif = not config.actif
        config.save()
        
        action = "activée" if config.actif else "désactivée"
        log_action(request.user, f"Configuration scoring {action}")
        
        return JsonResponse({
            'success': True, 
            'actif': config.actif,
            'message': f"Configuration {action} avec succès."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def config_scoring_reinitialiser(request):
    """Réinitialiser la configuration de scoring aux valeurs par défaut"""
    try:
        config = ConfigurationScoring.objects.first()
        if not config:
            config = ConfigurationScoring()
        
        # Valeurs par défaut
        config.nom = "Barèmes de scoring par défaut"
        config.description = "Configuration réinitialisée aux valeurs par défaut"
        
        # Poids par défaut
        config.poids_similarite_poste = 0.25
        config.poids_competences = 0.25
        config.poids_experience = 0.20
        config.poids_disponibilite = 0.15
        config.poids_proximite = 0.10
        config.poids_anciennete = 0.05
        
        # Bonus par défaut
        config.bonus_proposition_humaine = 5
        config.bonus_manager_direct = 12
        config.bonus_chef_equipe = 8
        config.bonus_responsable = 15
        config.bonus_directeur = 18
        config.bonus_rh = 20
        config.bonus_admin = 20
        
        # Pénalités par défaut
        config.penalite_indisponibilite_partielle = 15
        config.penalite_indisponibilite_totale = 50
        config.penalite_distance_excessive = 10
        
        config.actif = True
        config.configuration_par_defaut = True
        config.save()
        
        log_action(request.user, "Réinitialisation config scoring")
        
        return JsonResponse({
            'success': True,
            'message': "Configuration réinitialisée aux valeurs par défaut."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# CACHE API KELIO
# ================================================================

@login_required
@admin_required
def cache_kelio_liste(request):
    """Liste et gestion du cache API Kelio"""
    context = get_context_base(request)
    
    search = request.GET.get('search', '')
    service_filtre = request.GET.get('service', '')
    config_filtre = request.GET.get('config', '')
    
    queryset = CacheApiKelio.objects.select_related('configuration').order_by('-updated_at')
    
    if search:
        queryset = queryset.filter(cle_cache__icontains=search)
    if service_filtre:
        queryset = queryset.filter(service_name=service_filtre)
    if config_filtre:
        queryset = queryset.filter(configuration_id=config_filtre)
    
    paginator = Paginator(queryset, 50)
    page = request.GET.get('page', 1)
    cache_entries = paginator.get_page(page)
    
    now = timezone.now()
    context['cache_entries'] = cache_entries
    context['search'] = search
    context['service_filtre'] = service_filtre
    context['config_filtre'] = config_filtre
    context['services'] = CacheApiKelio.objects.values_list('service_name', flat=True).distinct()
    context['configurations'] = ConfigurationApiKelio.objects.all()
    context['stats_cache'] = {
        'total': CacheApiKelio.objects.count(),
        'expired': CacheApiKelio.objects.filter(date_expiration__lt=now).count(),
        'expires_soon': CacheApiKelio.objects.filter(
            date_expiration__gte=now,
            date_expiration__lte=now + timedelta(hours=1)
        ).count(),
    }
    
    return render(request, 'parametres/cache_kelio/liste.html', context)


@login_required
@admin_required
@require_POST
def cache_kelio_purger(request):
    """Purger le cache"""
    try:
        type_purge = request.POST.get('type', 'expired')
        
        if type_purge == 'all':
            count = CacheApiKelio.objects.count()
            CacheApiKelio.objects.all().delete()
            message = f"Cache entièrement vidé ({count} entrées)"
        else:
            count = CacheApiKelio.objects.filter(date_expiration__lt=timezone.now()).count()
            CacheApiKelio.objects.filter(date_expiration__lt=timezone.now()).delete()
            message = f"{count} entrées expirées supprimées"
        
        log_action(request.user, "Purge cache Kelio", message)
        return JsonResponse({'success': True, 'message': message})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def cache_kelio_supprimer(request, pk):
    """Supprimer une entrée de cache"""
    try:
        entry = get_object_or_404(CacheApiKelio, pk=pk)
        entry.delete()
        return JsonResponse({'success': True, 'message': "Entrée supprimée."})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# WORKFLOW ÉTAPES
# ================================================================

@login_required
@admin_required
def workflow_etapes_liste(request):
    """Liste des étapes de workflow"""
    context = get_context_base(request)
    
    etapes = WorkflowEtape.objects.all().order_by('ordre')
    context['etapes'] = etapes
    context['stats_workflow'] = {
        'total': etapes.count(),
        'actives': etapes.filter(actif=True).count(),
        'obligatoires': etapes.filter(obligatoire=True).count(),
    }
    
    return render(request, 'parametres/workflow/liste.html', context)


@login_required
@admin_required
def workflow_etape_modifier(request, pk=None):
    """Créer ou modifier une étape de workflow"""
    context = get_context_base(request)
    
    if pk:
        etape = get_object_or_404(WorkflowEtape, pk=pk)
        is_new = False
    else:
        etape = None
        is_new = True
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    etape = WorkflowEtape()
                
                etape.nom = request.POST.get('nom', '').strip()
                etape.type_etape = request.POST.get('type_etape', 'DEMANDE')
                etape.ordre = int(request.POST.get('ordre', 1))
                etape.obligatoire = request.POST.get('obligatoire') == 'on'
                
                delai = request.POST.get('delai_max_heures', '')
                etape.delai_max_heures = int(delai) if delai else None
                
                etape.condition_urgence = request.POST.get('condition_urgence', 'TOUTES')
                etape.permet_propositions_humaines = request.POST.get('permet_propositions_humaines') == 'on'
                etape.permet_ajout_nouveaux_candidats = request.POST.get('permet_ajout_nouveaux_candidats') == 'on'
                etape.actif = request.POST.get('actif') == 'on'
                
                etape.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} étape workflow", f"Nom: {etape.nom}")
                messages.success(request, f"Étape {'créée' if is_new else 'modifiée'} avec succès.")
                return redirect('workflow_etapes_liste')
                
        except Exception as e:
            logger.error(f"Erreur étape workflow: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['etape'] = etape
    context['is_new'] = is_new
    context['types_etape'] = WorkflowEtape.TYPES_ETAPE
    context['conditions_urgence'] = [
        ('TOUTES', 'Toutes'),
        ('NORMALE', 'Normale'),
        ('ELEVEE', 'Élevée'),
        ('CRITIQUE', 'Critique'),
    ]
    
    return render(request, 'parametres/workflow/form.html', context)


@login_required
@admin_required
@require_POST
def workflow_etapes_reordonner(request):
    """Réordonner les étapes par drag & drop"""
    try:
        data = json.loads(request.body)
        ordre_ids = data.get('ordre', [])
        
        with transaction.atomic():
            for index, etape_id in enumerate(ordre_ids, start=1):
                WorkflowEtape.objects.filter(pk=etape_id).update(ordre=index)
        
        log_action(request.user, "Réordonnancement workflow")
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def workflow_etape_supprimer(request, pk):
    """Supprimer une étape de workflow"""
    try:
        etape = get_object_or_404(WorkflowEtape, pk=pk)
        nom = etape.nom
        etape.delete()
        log_action(request.user, "Suppression étape workflow", f"Nom: {nom}")
        return JsonResponse({'success': True, 'message': f"Étape '{nom}' supprimée."})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# DÉPARTEMENTS
# ================================================================

@login_required
@admin_required
def departements_liste(request):
    """Liste des départements"""
    context = get_context_base(request)
    
    search = request.GET.get('search', '')
    actif_filtre = request.GET.get('actif', '')
    
    queryset = Departement.objects.annotate(
        nb_employes=Count('employes', distinct=True),
        nb_postes=Count('postes', distinct=True)
    ).order_by('nom')
    
    if search:
        queryset = queryset.filter(Q(nom__icontains=search) | Q(code__icontains=search))
    if actif_filtre:
        queryset = queryset.filter(actif=(actif_filtre == 'true'))
    
    paginator = Paginator(queryset, 25)
    page = request.GET.get('page', 1)
    departements = paginator.get_page(page)
    
    context['departements'] = departements
    context['search'] = search
    context['actif_filtre'] = actif_filtre
    context['stats'] = {
        'total': Departement.objects.count(),
        'actifs': Departement.objects.filter(actif=True).count(),
    }
    
    return render(request, 'parametres/departements/liste.html', context)


@login_required
@admin_required
def departement_modifier(request, pk=None):
    """Créer ou modifier un département"""
    context = get_context_base(request)
    
    if pk:
        departement = get_object_or_404(Departement, pk=pk)
        is_new = False
    else:
        departement = None
        is_new = True
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    departement = Departement()
                
                departement.code = request.POST.get('code', '').strip().upper()
                departement.nom = request.POST.get('nom', '').strip()
                departement.description = request.POST.get('description', '').strip()
                
                manager_id = request.POST.get('manager')
                departement.manager_id = int(manager_id) if manager_id else None
                
                departement.actif = request.POST.get('actif') == 'on'
                departement.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} département", f"Nom: {departement.nom}")
                messages.success(request, f"Département {'créé' if is_new else 'modifié'} avec succès.")
                return redirect('departements_liste')
                
        except Exception as e:
            logger.error(f"Erreur département: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['departement'] = departement
    context['is_new'] = is_new
    context['managers_disponibles'] = ProfilUtilisateur.objects.filter(
        type_profil__in=['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
    ).select_related('user')
    
    return render(request, 'parametres/departements/form.html', context)


@login_required
@admin_required
@require_POST
def departement_toggle_actif(request, pk):
    """Activer/désactiver un département"""
    try:
        dept = get_object_or_404(Departement, pk=pk)
        dept.actif = not dept.actif
        dept.save()
        return JsonResponse({'success': True, 'actif': dept.actif})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# SITES
# ================================================================

@login_required
@admin_required
def sites_liste(request):
    """Liste des sites"""
    context = get_context_base(request)
    
    search = request.GET.get('search', '')
    ville_filtre = request.GET.get('ville', '')
    actif_filtre = request.GET.get('actif', '')
    
    queryset = Site.objects.annotate(
        nb_postes=Count('postes', distinct=True)
    ).order_by('nom')
    
    if search:
        queryset = queryset.filter(Q(nom__icontains=search) | Q(ville__icontains=search))
    if ville_filtre:
        queryset = queryset.filter(ville=ville_filtre)
    if actif_filtre:
        queryset = queryset.filter(actif=(actif_filtre == 'true'))
    
    paginator = Paginator(queryset, 25)
    page = request.GET.get('page', 1)
    sites = paginator.get_page(page)
    
    context['sites'] = sites
    context['search'] = search
    context['ville_filtre'] = ville_filtre
    context['actif_filtre'] = actif_filtre
    context['villes'] = Site.objects.values_list('ville', flat=True).distinct().order_by('ville')
    context['stats'] = {
        'total': Site.objects.count(),
        'actifs': Site.objects.filter(actif=True).count(),
    }
    
    return render(request, 'parametres/sites/liste.html', context)


@login_required
@admin_required
def site_modifier(request, pk=None):
    """Créer ou modifier un site"""
    context = get_context_base(request)
    
    if pk:
        site = get_object_or_404(Site, pk=pk)
        is_new = False
    else:
        site = None
        is_new = True
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    site = Site()
                
                site.nom = request.POST.get('nom', '').strip()
                site.adresse = request.POST.get('adresse', '').strip()
                site.ville = request.POST.get('ville', '').strip()
                site.code_postal = request.POST.get('code_postal', '').strip()
                site.pays = request.POST.get('pays', "Côte d'Ivoire").strip()
                site.telephone = request.POST.get('telephone', '').strip()
                site.email = request.POST.get('email', '').strip()
                
                responsable_id = request.POST.get('responsable')
                site.responsable_id = int(responsable_id) if responsable_id else None
                
                site.actif = request.POST.get('actif') == 'on'
                site.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} site", f"Nom: {site.nom}")
                messages.success(request, f"Site {'créé' if is_new else 'modifié'} avec succès.")
                return redirect('sites_liste')
                
        except Exception as e:
            logger.error(f"Erreur site: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['site'] = site
    context['is_new'] = is_new
    context['responsables_disponibles'] = ProfilUtilisateur.objects.filter(
        type_profil__in=['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
    ).select_related('user')
    
    return render(request, 'parametres/sites/form.html', context)


@login_required
@admin_required
@require_POST
def site_toggle_actif(request, pk):
    """Activer/désactiver un site"""
    try:
        site = get_object_or_404(Site, pk=pk)
        site.actif = not site.actif
        site.save()
        return JsonResponse({'success': True, 'actif': site.actif})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# POSTES
# ================================================================

@login_required
@admin_required
def postes_liste(request):
    """Liste des postes"""
    context = get_context_base(request)
    
    search = request.GET.get('search', '')
    departement_filtre = request.GET.get('departement', '')
    site_filtre = request.GET.get('site', '')
    niveau_filtre = request.GET.get('niveau', '')
    
    queryset = Poste.objects.select_related('departement', 'site').annotate(
        nb_employes=Count('employes', distinct=True)
    ).order_by('titre')
    
    if search:
        queryset = queryset.filter(Q(titre__icontains=search) | Q(description__icontains=search))
    if departement_filtre:
        queryset = queryset.filter(departement_id=departement_filtre)
    if site_filtre:
        queryset = queryset.filter(site_id=site_filtre)
    if niveau_filtre:
        queryset = queryset.filter(niveau_responsabilite=niveau_filtre)
    
    paginator = Paginator(queryset, 25)
    page = request.GET.get('page', 1)
    postes = paginator.get_page(page)
    
    context['postes'] = postes
    context['search'] = search
    context['departement_filtre'] = departement_filtre
    context['site_filtre'] = site_filtre
    context['niveau_filtre'] = niveau_filtre
    context['departements'] = Departement.objects.filter(actif=True)
    context['sites'] = Site.objects.filter(actif=True)
    context['niveaux'] = [(1, 'Exécution'), (2, 'Maîtrise'), (3, 'Cadre')]
    context['stats'] = {
        'total': Poste.objects.count(),
        'actifs': Poste.objects.filter(actif=True).count(),
        'interim_autorises': Poste.objects.filter(interim_autorise=True).count(),
    }
    
    return render(request, 'parametres/postes/liste.html', context)


@login_required
@admin_required
def poste_modifier(request, pk=None):
    """Créer ou modifier un poste"""
    context = get_context_base(request)
    
    if pk:
        poste = get_object_or_404(Poste, pk=pk)
        is_new = False
    else:
        poste = None
        is_new = True
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    poste = Poste()
                
                poste.titre = request.POST.get('titre', '').strip()
                poste.description = request.POST.get('description', '').strip()
                poste.departement_id = int(request.POST.get('departement'))
                poste.site_id = int(request.POST.get('site'))
                poste.niveau_responsabilite = int(request.POST.get('niveau_responsabilite', 1))
                poste.interim_autorise = request.POST.get('interim_autorise') == 'on'
                poste.actif = request.POST.get('actif') == 'on'
                poste.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} poste", f"Titre: {poste.titre}")
                messages.success(request, f"Poste {'créé' if is_new else 'modifié'} avec succès.")
                return redirect('postes_liste')
                
        except Exception as e:
            logger.error(f"Erreur poste: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['poste'] = poste
    context['is_new'] = is_new
    context['departements'] = Departement.objects.filter(actif=True)
    context['sites'] = Site.objects.filter(actif=True)
    context['niveaux'] = [(1, 'Exécution'), (2, 'Maîtrise'), (3, 'Cadre')]
    
    return render(request, 'parametres/postes/form.html', context)


@login_required
@admin_required
@require_POST
def poste_toggle_actif(request, pk):
    """Activer/désactiver un poste"""
    try:
        poste = get_object_or_404(Poste, pk=pk)
        poste.actif = not poste.actif
        poste.save()
        return JsonResponse({'success': True, 'actif': poste.actif})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# MOTIFS D'ABSENCE
# ================================================================

@login_required
@admin_required
def motifs_absence_liste(request):
    """Liste des motifs d'absence"""
    context = get_context_base(request)
    
    search = request.GET.get('search', '')
    categorie_filtre = request.GET.get('categorie', '')
    
    queryset = MotifAbsence.objects.all().order_by('categorie', 'nom')
    
    if search:
        queryset = queryset.filter(Q(nom__icontains=search) | Q(code__icontains=search))
    if categorie_filtre:
        queryset = queryset.filter(categorie=categorie_filtre)
    
    paginator = Paginator(queryset, 25)
    page = request.GET.get('page', 1)
    motifs = paginator.get_page(page)
    
    context['motifs'] = motifs
    context['search'] = search
    context['categorie_filtre'] = categorie_filtre
    context['categories'] = [
        ('MALADIE', 'Maladie'),
        ('CONGE', 'Congé'),
        ('FORMATION', 'Formation'),
        ('PERSONNEL', 'Personnel'),
        ('PROFESSIONNEL', 'Professionnel'),
    ]
    context['stats'] = {
        'total': MotifAbsence.objects.count(),
        'actifs': MotifAbsence.objects.filter(actif=True).count(),
    }
    
    return render(request, 'parametres/motifs_absence/liste.html', context)


@login_required
@admin_required
def motif_absence_modifier(request, pk=None):
    """Créer ou modifier un motif d'absence"""
    context = get_context_base(request)
    
    if pk:
        motif = get_object_or_404(MotifAbsence, pk=pk)
        is_new = False
    else:
        motif = None
        is_new = True
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                if is_new:
                    motif = MotifAbsence()
                
                motif.code = request.POST.get('code', '').strip().upper()
                motif.nom = request.POST.get('nom', '').strip()
                motif.description = request.POST.get('description', '').strip()
                motif.categorie = request.POST.get('categorie', 'PERSONNEL')
                motif.couleur = request.POST.get('couleur', '#007bff').strip()
                motif.necessite_justificatif = request.POST.get('necessite_justificatif') == 'on'
                motif.delai_prevenance_jours = int(request.POST.get('delai_prevenance_jours', 7))
                
                duree_max = request.POST.get('duree_max_jours', '')
                motif.duree_max_jours = int(duree_max) if duree_max else None
                
                motif.kelio_abbreviation = request.POST.get('kelio_abbreviation', '').strip()
                motif.actif = request.POST.get('actif') == 'on'
                motif.save()
                
                log_action(request.user, f"{'Création' if is_new else 'Modification'} motif absence", f"Nom: {motif.nom}")
                messages.success(request, f"Motif {'créé' if is_new else 'modifié'} avec succès.")
                return redirect('motifs_absence_liste')
                
        except Exception as e:
            logger.error(f"Erreur motif absence: {e}")
            messages.error(request, f"Erreur: {str(e)}")
    
    context['motif'] = motif
    context['is_new'] = is_new
    context['categories'] = [
        ('MALADIE', 'Maladie'),
        ('CONGE', 'Congé'),
        ('FORMATION', 'Formation'),
        ('PERSONNEL', 'Personnel'),
        ('PROFESSIONNEL', 'Professionnel'),
    ]
    
    return render(request, 'parametres/motifs_absence/form.html', context)


@login_required
@admin_required
@require_POST
def motif_absence_toggle_actif(request, pk):
    """Activer/désactiver un motif"""
    try:
        motif = get_object_or_404(MotifAbsence, pk=pk)
        motif.actif = not motif.actif
        motif.save()
        return JsonResponse({'success': True, 'actif': motif.actif})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
@admin_required
@require_POST
def motif_absence_supprimer(request, pk):
    """Supprimer un motif d'absence"""
    try:
        motif = get_object_or_404(MotifAbsence, pk=pk)
        nom = motif.nom
        motif.delete()
        log_action(request.user, "Suppression motif absence", f"Nom: {nom}")
        return JsonResponse({'success': True, 'message': f"Motif '{nom}' supprimé."})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ================================================================
# EXPORT / IMPORT
# ================================================================

@login_required
@admin_required
def parametres_export(request):
    """Exporter les paramètres en JSON"""
    data = {
        'departements': list(Departement.objects.values()),
        'sites': list(Site.objects.values()),
        'postes': list(Poste.objects.values()),
        'motifs_absence': list(MotifAbsence.objects.values()),
        'workflow_etapes': list(WorkflowEtape.objects.values()),
    }
    
    response = HttpResponse(
        json.dumps(data, indent=2, default=str, ensure_ascii=False),
        content_type='application/json'
    )
    response['Content-Disposition'] = f'attachment; filename="parametres_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
    
    log_action(request.user, "Export paramètres")
    return response


@login_required
@admin_required
@require_POST
def parametres_import(request):
    """Importer des paramètres depuis JSON"""
    try:
        fichier = request.FILES.get('fichier')
        if not fichier:
            return JsonResponse({'success': False, 'message': "Aucun fichier."})
        
        data = json.load(fichier)
        resultats = {'crees': 0, 'modifies': 0}
        
        with transaction.atomic():
            for dept_data in data.get('departements', []):
                dept, created = Departement.objects.update_or_create(
                    code=dept_data['code'],
                    defaults={'nom': dept_data['nom'], 'description': dept_data.get('description', ''), 'actif': dept_data.get('actif', True)}
                )
                resultats['crees' if created else 'modifies'] += 1
        
        log_action(request.user, "Import paramètres", f"Créés: {resultats['crees']}, Modifiés: {resultats['modifies']}")
        return JsonResponse({'success': True, 'message': f"Import terminé: {resultats['crees']} créés, {resultats['modifies']} modifiés."})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
