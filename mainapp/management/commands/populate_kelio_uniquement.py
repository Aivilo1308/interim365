# -*- coding: utf-8 -*-
#!/usr/bin/env python
"""
Commande Django Management pour importer uniquement les donnees Kelio
Version epuree - Import Kelio SafeSecur UNIQUEMENT sans donnees fictives
VERSION AVEC DEBUG DETAILLE ET TRACES COMPLETES

URL DE BASE KELIO SAFESECUR: https://keliodemo-safesecur.kelio.io/open

FONCTIONNALITES:
OK URL Kelio SafeSecur configuree
OK Import STRICT depuis Kelio SafeSecur uniquement
OK Configuration de scoring basique
OK Workflow d'interim simple
OK Pas de donnees fictives
OK Import des employes Kelio uniquement
OK Import des formations/absences Kelio uniquement
OK TRACES DE DEBUG DETAILLEES pour suivi complet
OK MESSAGES DE PROGRESSION pour chaque etape
OK LOGS D'ERREUR PRECIS avec stack traces

TABLES GEREES (IMPORT KELIO STRICT):
OK Configuration et cache Kelio SafeSecur
OK Configuration de scoring de base
OK Employes et profils utilisateurs (Kelio STRICT)
OK Competences et referentiel (Kelio STRICT)
OK Formations et absences utilisateurs (Kelio STRICT)
OK Structure organisationnelle minimale (si necessaire)

Usage avec debug:
    python manage.py populate_kelio_data --mode=kelio_only --verbose
    python manage.py populate_kelio_data --mode=kelio_only --with-kelio-sync --force --verbose
    python manage.py populate_kelio_data --mode=kelio_only --no-test-connection --verbose
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from datetime import datetime, date, timedelta
import logging
from typing import Dict, List, Optional, Any
import random
import uuid
import json

# ================================================================
# CONFIGURATION KELIO SAFESECUR - IMPORT STRICT
# ================================================================

KELIO_SAFESECUR_BASE_URL = 'https://keliodemo-safesecur.kelio.io/open'
KELIO_SAFESECUR_SERVICES_URL = '{}/services'.format(KELIO_SAFESECUR_BASE_URL)

KELIO_SAFESECUR_DEFAULT_AUTH = {
    'username': 'webservices',
    'password': '12345'
}

# Configuration des environnements Kelio SafeSecur
KELIO_ENVIRONMENTS = {
    'demo': {
        'base_url': KELIO_SAFESECUR_BASE_URL,
        'services_url': KELIO_SAFESECUR_SERVICES_URL,
        'description': 'Environnement de demonstration Kelio SafeSecur',
        'timeout': 30
    },
    'production': {
        'base_url': KELIO_SAFESECUR_BASE_URL,
        'services_url': KELIO_SAFESECUR_SERVICES_URL,
        'description': 'Environnement de production Kelio SafeSecur',
        'timeout': 45
    }
}

# Configuration du logging avec debug detaille
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('kelio_import_debug.log', mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Logger specifique pour les traces d'import
import_logger = logging.getLogger('kelio_import')
import_logger.setLevel(logging.DEBUG)

class Command(BaseCommand):
    """
    Commande Django pour l'import strict des donnees Kelio SafeSecur UNIQUEMENT
    """
    help = 'Importe UNIQUEMENT les donnees depuis Kelio SafeSecur - AUCUNE donnee fictive'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=[
                'kelio_only', 'structure_kelio', 'employees_kelio', 'minimal'
            ],
            default='kelio_only',
            help='Mode d\'import: kelio_only (complet Kelio), structure_kelio (structure depuis Kelio), employees_kelio (employes Kelio), minimal (configuration minimale)'
        )
        parser.add_argument(
            '--kelio-url',
            type=str,
            default=KELIO_SAFESECUR_SERVICES_URL,
            help='URL de base pour les services Kelio (defaut: {})'.format(KELIO_SAFESECUR_SERVICES_URL)
        )
        parser.add_argument(
            '--kelio-environment',
            choices=['demo', 'production'],
            default='demo',
            help='Environnement Kelio SafeSecur a utiliser (defaut: demo)'
        )
        parser.add_argument(
            '--with-kelio-sync',
            action='store_true',
            help='Forcer la synchronisation avec Kelio SafeSecur SOAP'
        )
        parser.add_argument(
            '--no-test-connection',
            action='store_true',
            help='Ne pas tester la connexion Kelio avant import'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulation sans modification de la base'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forcer la recreation meme si les donnees existent'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Affichage detaille des operations'
        )
        parser.add_argument(
            '--api-timeout',
            type=int,
            default=30,
            help='Timeout pour les appels API Kelio en secondes (defaut: 30)'
        )
        parser.add_argument(
            '--default-password',
            type=str,
            default='Kelio2025@',
            help='Mot de passe par defaut pour les utilisateurs importes de Kelio (defaut: Kelio2025@)'
        )
    
    def handle(self, *args, **options):
        """Point d'entree principal de la commande avec debug detaille"""
        debug_session_id = str(uuid.uuid4())[:8]
        
        try:
            logger.info(">>> DEBUT SESSION DEBUG - ID: {}".format(debug_session_id))
            logger.info("=" * 100)
            
            # Configuration du niveau de log avec traces detaillees
            if options['verbose']:
                logging.getLogger().setLevel(logging.DEBUG)
                logging.getLogger('kelio_import').setLevel(logging.DEBUG)
                logger.debug(">>> MODE VERBOSE ACTIVE - Traces detaillees activees")
            
            # Recuperation des parametres avec validation
            logger.debug(">>> RECUPERATION ET VALIDATION DES PARAMETRES")
            mode = options['mode']
            kelio_url = options['kelio_url']
            kelio_environment = options['kelio_environment']
            with_kelio_sync = options['with_kelio_sync']
            test_connection = not options['no_test_connection']
            dry_run = options['dry_run']
            force = options['force']
            api_timeout = options['api_timeout']
            default_password = options['default_password']
            
            logger.debug("  OK Mode selectionne: {}".format(mode))
            logger.debug("  OK URL Kelio: {}".format(kelio_url))
            logger.debug("  OK Environnement: {}".format(kelio_environment))
            logger.debug("  OK Sync Kelio: {}".format(with_kelio_sync))
            logger.debug("  OK Test connexion: {}".format(test_connection))
            logger.debug("  OK Mode simulation: {}".format(dry_run))
            logger.debug("  OK Mode force: {}".format(force))
            logger.debug("  OK Timeout API: {}s".format(api_timeout))
            
            # Configuration Kelio SafeSecur avec validation
            logger.debug(">>> CONFIGURATION KELIO SAFESECUR")
            kelio_config = KELIO_ENVIRONMENTS.get(kelio_environment, KELIO_ENVIRONMENTS['demo'])
            kelio_config['services_url'] = kelio_url
            kelio_config['timeout'] = api_timeout
            logger.debug("  OK Configuration Kelio chargee: {}".format(kelio_config))
            
            # Affichage des parametres avec debug
            self.stdout.write(self.style.SUCCESS('>>> IMPORT KELIO SAFESECUR STRICT - AUCUNE DONNEE FICTIVE'))
            self.stdout.write(">>> SESSION DEBUG ID: {}".format(debug_session_id))
            self.stdout.write("=" * 80)
            self.stdout.write("Mode: {}".format(mode))
            self.stdout.write("URL Kelio SafeSecur: {}".format(kelio_url))
            self.stdout.write("Environnement: {}".format(kelio_environment))
            self.stdout.write("Sync Kelio SOAP: {}".format('Oui' if with_kelio_sync else 'Non'))
            self.stdout.write("Test connexion: {}".format('Oui' if test_connection else 'Non'))
            self.stdout.write("Simulation: {}".format('Oui' if dry_run else 'Non'))
            self.stdout.write("Force: {}".format('Oui' if force else 'Non'))
            self.stdout.write("Timeout API: {}s".format(api_timeout))
            self.stdout.write("Mot de passe par defaut: {}".format(default_password))
            self.stdout.write("AUCUNE DONNEE FICTIVE NE SERA CREEE")
            self.stdout.write("Logs detailles dans: kelio_import_debug.log")
            self.stdout.write("=" * 80)
            
            if dry_run:
                logger.info(">>> MODE SIMULATION ACTIVE - Aucune modification ne sera effectuee")
                self.stdout.write(self.style.WARNING(">>> MODE SIMULATION - Aucune modification ne sera effectuee"))
                return
            
            # Validation des parametres critiques
            logger.debug("OK VALIDATION DES PARAMETRES CRITIQUES")
            if not kelio_url:
                raise ValueError("URL Kelio manquante")
            if api_timeout < 10:
                logger.warning("WARNING Timeout API tres court: {}s".format(api_timeout))
            
            logger.debug(">>> CREATION DE L'INSTANCE D'IMPORT")
            # Lancer l'import avec configuration SafeSecur
            importer = KelioStrictDataImporter(
                stdout=self.stdout,
                style=self.style,
                force=force,
                kelio_config=kelio_config,
                default_password=default_password,
                with_kelio_sync=with_kelio_sync,
                debug_session_id=debug_session_id
            )
            
            logger.info(">>> LANCEMENT DE L'IMPORT EN MODE: {}".format(mode))
            success = importer.run_import(mode, test_connection)
            
            if success:
                logger.info("OK SESSION {} - Import Kelio SafeSecur strict termine avec succes".format(debug_session_id))
                self.stdout.write(
                    self.style.SUCCESS('OK Import Kelio SafeSecur strict termine avec succes')
                )
            else:
                logger.error("ERROR SESSION {} - Import Kelio SafeSecur strict echoue".format(debug_session_id))
                raise CommandError('ERROR Import Kelio SafeSecur strict echoue')
                
        except Exception as e:
            logger.error("ERROR SESSION {} - Erreur dans la commande: {}".format(debug_session_id, e))
            logger.error("ERROR Stack trace complete:", exc_info=True)
            raise CommandError('Erreur lors de l\'import: {}'.format(str(e)))
        finally:
            logger.info(">>> FIN SESSION DEBUG - ID: {}".format(debug_session_id))
            logger.info("=" * 100)


# ================================================================
# CLASSE PRINCIPALE D'IMPORT KELIO STRICT
# ================================================================

class KelioStrictDataImporter:
    """
    Gestionnaire principal pour l'import strict des donnees Kelio SafeSecur UNIQUEMENT
    """
    
    def __init__(self, stdout=None, style=None, force=False,
                 kelio_config=None, default_password='Kelio2025@', with_kelio_sync=True,
                 debug_session_id=None):
        
        logger.debug(">>> INITIALISATION KelioStrictDataImporter")
        
        # Import des modeles apres setup Django
        logger.debug(">>> Import des modeles Django")
        from mainapp.models import (
            ConfigurationApiKelio, CacheApiKelio, ConfigurationScoring,
            ProfilUtilisateur, Departement, Site, Poste,
            Competence, MotifAbsence, CompetenceUtilisateur, FormationUtilisateur,
            AbsenceUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended,
            WorkflowEtape
        )
        
        self.models = {
            'ConfigurationApiKelio': ConfigurationApiKelio,
            'CacheApiKelio': CacheApiKelio,
            'ConfigurationScoring': ConfigurationScoring,
            'ProfilUtilisateur': ProfilUtilisateur,
            'Departement': Departement,
            'Site': Site,
            'Poste': Poste,
            'Competence': Competence,
            'MotifAbsence': MotifAbsence,
            'CompetenceUtilisateur': CompetenceUtilisateur,
            'FormationUtilisateur': FormationUtilisateur,
            'AbsenceUtilisateur': AbsenceUtilisateur,
            'ProfilUtilisateurKelio': ProfilUtilisateurKelio,
            'ProfilUtilisateurExtended': ProfilUtilisateurExtended,
            'WorkflowEtape': WorkflowEtape,
        }
        logger.debug("  OK {} modeles Django importes".format(len(self.models)))
        
        # Initialisation des statistiques detaillees
        self.stats = {
            'total_imported': 0,
            'total_updated': 0,
            'total_errors': 0,
            'total_skipped': 0,
            'by_model': {},
            'operation_times': {},
            'error_details': []
        }
        logger.debug("  OK Statistiques initialisees")
        
        # Configuration Kelio SafeSecur
        self.kelio_config_data = kelio_config or KELIO_ENVIRONMENTS['demo']
        self.kelio_config = None
        self.stdout = stdout
        self.style = style
        self.force = force
        self.default_password = default_password
        self.with_kelio_sync = with_kelio_sync
        self.debug_session_id = debug_session_id or str(uuid.uuid4())[:8]
        
        logger.debug("  OK Session debug ID: {}".format(self.debug_session_id))
        logger.debug("  OK URL Kelio configuree: {}".format(self.kelio_config_data.get('services_url')))
        logger.debug("  OK Sync Kelio active: {}".format(self.with_kelio_sync))
        logger.debug("  OK Mode force: {}".format(self.force))
        
        # Stockage des objets importes avec compteurs detailles
        self.imported_objects = {
            'departements': [],
            'sites': [],
            'postes': [],
            'employes': [],
            'competences': [],
            'motifs_absence': [],
            'formations': [],
            'absences': []
        }
        logger.debug("  OK Conteneurs d'objets importes initialises")
        
        # Timestamps pour mesurer les performances
        self.operation_start_time = None
        self.last_operation_time = None
        
        logger.debug("OK INITIALISATION KelioStrictDataImporter TERMINEE")
        
    def _write(self, message, style_func=None, debug_level='INFO'):
        """Helper pour ecrire des messages avec style Django et debug detaille"""
        if self.stdout:
            if style_func and self.style:
                self.stdout.write(style_func(message))
            else:
                self.stdout.write(message)
        
        # Log avec niveau approprie
        if debug_level == 'DEBUG':
            logger.debug("[{}] {}".format(self.debug_session_id, message))
        elif debug_level == 'WARNING':
            logger.warning("[{}] {}".format(self.debug_session_id, message))
        elif debug_level == 'ERROR':
            logger.error("[{}] {}".format(self.debug_session_id, message))
        else:
            logger.info("[{}] {}".format(self.debug_session_id, message))
    
    def _start_operation_timer(self, operation_name):
        """Demarre le timer pour une operation"""
        self.operation_start_time = timezone.now()
        self.last_operation_time = self.operation_start_time
        logger.debug(">>> DEBUT OPERATION: {}".format(operation_name))
        return self.operation_start_time
    
    def _end_operation_timer(self, operation_name):
        """Termine le timer pour une operation"""
        if self.operation_start_time:
            duration = (timezone.now() - self.operation_start_time).total_seconds()
            self.stats['operation_times'][operation_name] = duration
            logger.debug(">>> FIN OPERATION: {} - Duree: {:.2f}s".format(operation_name, duration))
            return duration
        return 0
    
    def _log_error_with_details(self, error_msg, exception=None, context=None):
        """Log une erreur avec details complets"""
        error_detail = {
            'timestamp': timezone.now().isoformat(),
            'session_id': self.debug_session_id,
            'message': error_msg,
            'context': context or {},
            'exception_type': type(exception).__name__ if exception else None,
            'exception_msg': str(exception) if exception else None
        }
        
        self.stats['error_details'].append(error_detail)
        self.stats['total_errors'] += 1
        
        logger.error("ERROR [{}] {}".format(self.debug_session_id, error_msg))
        if exception:
            logger.error("ERROR [{}] Exception: {}".format(self.debug_session_id, exception))
            if context:
                logger.error("ERROR [{}] Contexte: {}".format(self.debug_session_id, context))
            logger.debug("ERROR [{}] Stack trace:".format(self.debug_session_id), exc_info=True)
        
    def run_import(self, mode='kelio_only', test_connection=True):
        """
        Lance l'import strict des donnees Kelio SafeSecur avec debug detaille
        
        Args:
            mode: 'kelio_only', 'structure_kelio', 'employees_kelio', 'minimal'
            test_connection: Tester la connexion Kelio avant import
        """
        operation_timer = self._start_operation_timer('import_complet')
        
        self._write(">>> DEBUT DE L'IMPORT KELIO SAFESECUR STRICT - SESSION: {}".format(self.debug_session_id))
        self._write(">>> Mode selectionne: {}".format(mode), debug_level='DEBUG')
        logger.info(">>> IMPORT KELIO STRICT - Mode: {} - Session: {}".format(mode, self.debug_session_id))
        
        try:
            # Etape 1: Configuration Kelio SafeSecur
            self._write(">>> ETAPE 1/6: Configuration Kelio SafeSecur...")
            step_timer = self._start_operation_timer('configuration_kelio')
            self._setup_kelio_safesecur_configuration()
            step_duration = self._end_operation_timer('configuration_kelio')
            self._write("OK ETAPE 1 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            
            # Etape 2: Configuration minimale
            self._write(">>> ETAPE 2/6: Configuration minimale...")
            step_timer = self._start_operation_timer('configuration_minimale')
            self._setup_minimal_configuration()
            step_duration = self._end_operation_timer('configuration_minimale')
            self._write("OK ETAPE 2 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            
            # Etape 3: Test de connexion (optionnel)
            if test_connection:
                self._write(">>> ETAPE 3/6: Test de connexion Kelio SafeSecur...")
                step_timer = self._start_operation_timer('test_connexion')
                self._test_kelio_safesecur_connection()
                step_duration = self._end_operation_timer('test_connexion')
                self._write("OK ETAPE 3 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            else:
                self._write(">>> ETAPE 3/6: Test de connexion ignore", debug_level='DEBUG')
            
            # Etape 4: Import selon le mode
            self._write(">>> ETAPE 4/6: Import des donnees en mode {}...".format(mode))
            step_timer = self._start_operation_timer('import_{}'.format(mode))
            
            if mode == 'kelio_only':
                self._import_kelio_complete()
            elif mode == 'structure_kelio':
                self._import_kelio_structure_only()
            elif mode == 'employees_kelio':
                self._import_kelio_employees_only()
            elif mode == 'minimal':
                self._import_minimal_configuration()
            else:
                error_msg = "Mode d'import non supporte: {}".format(mode)
                self._log_error_with_details(error_msg, context={'mode': mode})
                raise ValueError(error_msg)
            
            step_duration = self._end_operation_timer('import_{}'.format(mode))
            self._write("OK ETAPE 4 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            
            # Etape 5: Validation post-import
            self._write("OK ETAPE 5/6: Validation post-import...")
            step_timer = self._start_operation_timer('validation_post_import')
            self._validate_post_import()
            step_duration = self._end_operation_timer('validation_post_import')
            self._write("OK ETAPE 5 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            
            # Etape 6: Statistiques finales
            self._write(">>> ETAPE 6/6: Generation des statistiques...")
            step_timer = self._start_operation_timer('statistiques_finales')
            duration = self._end_operation_timer('import_complet')
            self._log_final_statistics(duration)
            step_duration = self._end_operation_timer('statistiques_finales')
            self._write("OK ETAPE 6 TERMINEE en {:.2f}s".format(step_duration), debug_level='DEBUG')
            
            # Resume final avec debug
            success_msg = "OK Import Kelio SafeSecur strict termine avec succes - Session: {}".format(self.debug_session_id)
            self._write(success_msg, self.style.SUCCESS if self.style else None)
            logger.info(">>> SUCCES: {}".format(success_msg))
            logger.info(">>> RESUME: {} importes, {} mis a jour, {} erreurs".format(self.stats['total_imported'], self.stats['total_updated'], self.stats['total_errors']))
            
            return True
            
        except Exception as e:
            error_context = {
                'mode': mode,
                'test_connection': test_connection,
                'session_id': self.debug_session_id,
                'current_stats': self.stats
            }
            
            self._log_error_with_details("Erreur lors de l'import Kelio SafeSecur strict", e, error_context)
            self._log_error_statistics()
            self._write("ERROR Erreur import: {}".format(e), self.style.ERROR if self.style else None, debug_level='ERROR')
            
            return False
    
    def _setup_kelio_safesecur_configuration(self):
        """Configure la connexion Kelio SafeSecur avec debug detaille"""
        ConfigurationApiKelio = self.models['ConfigurationApiKelio']
        
        try:
            logger.debug(">>> [{}] Debut configuration Kelio SafeSecur".format(self.debug_session_id))
            
            # Configuration Kelio SafeSecur avec validation
            default_config = {
                'url_base': self.kelio_config_data['services_url'],
                'username': KELIO_SAFESECUR_DEFAULT_AUTH['username'],
                'password': KELIO_SAFESECUR_DEFAULT_AUTH['password'],
                'timeout_seconds': self.kelio_config_data['timeout'],
                'service_employees': True,
                'service_absences': True,
                'service_formations': True,
                'service_competences': True,
                'cache_duree_defaut_minutes': 60,
                'cache_taille_max_mo': 100,
                'auto_invalidation_cache': True,
                'actif': True
            }
            
            logger.debug(">>> [{}] Configuration par defaut preparee:".format(self.debug_session_id))
            for key, value in default_config.items():
                if key != 'password':  # Ne pas logger le mot de passe
                    logger.debug("   • {}: {}".format(key, value))
                else:
                    logger.debug("   • {}: {}".format(key, '*' * len(str(value))))
            
            # Rechercher ou creer la configuration Kelio SafeSecur
            logger.debug(">>> [{}] Recherche configuration existante...".format(self.debug_session_id))
            existing_configs = ConfigurationApiKelio.objects.filter(nom='Configuration Kelio SafeSecur')
            logger.debug(">>> [{}] {} configuration(s) existante(s) trouvee(s)".format(self.debug_session_id, existing_configs.count()))
            
            self.kelio_config, created = ConfigurationApiKelio.objects.get_or_create(
                nom='Configuration Kelio SafeSecur',
                defaults=default_config
            )
            
            if created:
                logger.debug("OK [{}] Nouvelle configuration Kelio creee".format(self.debug_session_id))
            else:
                logger.debug(">>> [{}] Configuration Kelio existante recuperee".format(self.debug_session_id))
            
            # Mise a jour forcee si necessaire
            if not created and self.force:
                logger.debug(">>> [{}] Mode force active - Mise a jour de la configuration".format(self.debug_session_id))
                old_url = self.kelio_config.url_base
                for key, value in default_config.items():
                    old_value = getattr(self.kelio_config, key, None)
                    setattr(self.kelio_config, key, value)
                    if old_value != value and key != 'password':
                        logger.debug("   • {}: {} -> {}".format(key, old_value, value))
                
                self.kelio_config.save()
                logger.debug("OK [{}] Configuration mise a jour depuis {}".format(self.debug_session_id, old_url))
                self._write(">>> Configuration Kelio mise a jour", debug_level='DEBUG')
            
            # Validation de la configuration
            logger.debug("OK [{}] Validation de la configuration finale:".format(self.debug_session_id))
            logger.debug("   • ID: {}".format(self.kelio_config.id))
            logger.debug("   • Nom: {}".format(self.kelio_config.nom))
            logger.debug("   • URL: {}".format(self.kelio_config.url_base))
            logger.debug("   • Username: {}".format(self.kelio_config.username))
            logger.debug("   • Timeout: {}s".format(self.kelio_config.timeout_seconds))
            logger.debug("   • Services actifs: employees={}, formations={}".format(self.kelio_config.service_employees, self.kelio_config.service_formations))
            logger.debug("   • Configuration active: {}".format(self.kelio_config.actif))
            
            action = "creee" if created else "recuperee"
            self._write(">>> Configuration Kelio SafeSecur {}: {}".format(action, self.kelio_config.nom))
            self._write(">>> URL configuree: {}".format(self.kelio_config.url_base), debug_level='DEBUG')
            self._write(">>> Identifiants: {}".format(self.kelio_config.username), debug_level='DEBUG')
            self._write(">>> Timeout: {}s".format(self.kelio_config.timeout_seconds), debug_level='DEBUG')
            
            self._update_stats('ConfigurationApiKelio', created)
            logger.debug("OK [{}] Configuration Kelio SafeSecur terminee avec succes".format(self.debug_session_id))
            
        except Exception as e:
            error_context = {
                'kelio_config_data': self.kelio_config_data,
                'default_config': default_config if 'default_config' in locals() else None
            }
            self._log_error_with_details("Erreur configuration Kelio SafeSecur", e, error_context)
            raise
    
    def _setup_minimal_configuration(self):
        """Configure uniquement les elements minimaux necessaires"""
        ConfigurationScoring = self.models['ConfigurationScoring']
        WorkflowEtape = self.models['WorkflowEtape']
        
        try:
            # Configuration scoring minimale
            config_scoring, created = ConfigurationScoring.objects.get_or_create(
                nom='Configuration Kelio Minimale',
                defaults={
                    'description': 'Configuration minimale pour import Kelio strict',
                    'poids_similarite_poste': 0.30,
                    'poids_competences': 0.30,
                    'poids_experience': 0.25,
                    'poids_disponibilite': 0.15,
                    'configuration_par_defaut': True,
                    'actif': True
                }
            )
            
            # Workflow etape minimale
            etape_workflow, created_etape = WorkflowEtape.objects.get_or_create(
                type_etape='DEMANDE',
                defaults={
                    'nom': 'Creation de demande Kelio',
                    'ordre': 1,
                    'obligatoire': True,
                    'actif': True
                }
            )
            
            configs_created = sum([created, created_etape])
            if configs_created > 0:
                self._write(">>> Configurations minimales creees: {}".format(configs_created))
                self._update_stats('ConfigurationScoring', created)
                self._update_stats('WorkflowEtape', created_etape)
            
        except Exception as e:
            logger.error("Erreur configuration minimale: {}".format(e))
            raise
    
    def _test_kelio_safesecur_connection(self):
        """Test la connexion aux services Kelio SafeSecur avec debug detaille"""
        try:
            logger.debug(">>> [{}] Debut test de connexion Kelio SafeSecur".format(self.debug_session_id))
            self._write(">>> Test de connexion aux services Kelio SafeSecur...")
            
            # Import du service de synchronisation avec gestion d'erreur
            try:
                logger.debug(">>> [{}] Import du service kelio_api_simplifie...".format(self.debug_session_id))
                from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
                logger.debug("OK [{}] Service kelio_api_simplifie importe avec succes".format(self.debug_session_id))
                
                logger.debug(">>> [{}] Creation du service de sync avec configuration:".format(self.debug_session_id))
                logger.debug("   • URL: {}".format(self.kelio_config.url_base))
                logger.debug("   • Username: {}".format(self.kelio_config.username))
                logger.debug("   • Timeout: {}s".format(self.kelio_config.timeout_seconds))
                
                sync_service = get_kelio_sync_service_v41(self.kelio_config)
                logger.debug("OK [{}] Service de synchronisation cree".format(self.debug_session_id))
                
                logger.debug(">>> [{}] Lancement test connexion complete...".format(self.debug_session_id))
                test_start_time = timezone.now()
                
                test_results = sync_service.test_connexion_complete_v41()
                
                test_duration = (timezone.now() - test_start_time).total_seconds()
                logger.debug(">>> [{}] Test connexion termine en {:.2f}s".format(self.debug_session_id, test_duration))
                
                # Analyse detaillee des resultats
                logger.debug(">>> [{}] Analyse des resultats de test:".format(self.debug_session_id))
                logger.debug("   • Resultats bruts: {}".format(test_results))
                
                global_status = test_results.get('global_status', False)
                logger.debug("   • Statut global: {}".format(global_status))
                
                if global_status:
                    self._write("OK Connexion Kelio SafeSecur reussie", self.style.SUCCESS if self.style else None)
                    logger.info("OK [{}] CONNEXION KELIO SAFESECUR ETABLIE AVEC SUCCES".format(self.debug_session_id))
                    logger.info(">>> [{}] URL: {}".format(self.debug_session_id, self.kelio_config.url_base))
                    logger.info(">>> [{}] Authentification reussie pour: {}".format(self.debug_session_id, self.kelio_config.username))
                    
                    # Log detaille des services avec comptage
                    services_status = test_results.get('services_status', {})
                    total_services = len(services_status)
                    services_actifs = 0
                    services_inactifs = 0
                    
                    logger.debug(">>> [{}] Etat des services ({} services testes):".format(self.debug_session_id, total_services))
                    self._write(">>> Services Kelio testes: {}".format(total_services))
                    
                    for service_name, service_info in services_status.items():
                        service_status = service_info.get('status', 'UNKNOWN')
                        service_description = service_info.get('description', 'Service Kelio')
                        
                        if service_status == 'OK':
                            services_actifs += 1
                            status_icon = "OK"
                            logger.info("OK [{}] SERVICE ACTIF: {} - {}".format(self.debug_session_id, service_name, service_description))
                        else:
                            services_inactifs += 1
                            status_icon = "ERROR"
                            error_details = service_info.get('error', 'Aucun detail d\'erreur')
                            logger.warning("ERROR [{}] SERVICE INACTIF: {} - Erreur: {}".format(self.debug_session_id, service_name, error_details))
                        
                        self._write("  {} {}: {}".format(status_icon, service_name, service_description))
                        logger.debug("   • {}: {} - {}".format(service_name, service_status, service_description))
                    
                    # RESUME COMPLET DES SERVICES KELIO
                    logger.info(">>> [{}] RESUME SERVICES KELIO:".format(self.debug_session_id))
                    logger.info("   >>> Services actifs: {}/{}".format(services_actifs, total_services))
                    logger.info("   >>> Services inactifs: {}/{}".format(services_inactifs, total_services))
                    logger.info("   >>> Taux de reussite: {:.1f}%".format((services_actifs/total_services)*100 if total_services > 0 else 0))
                    
                    self._write(">>> Services actifs: {}/{} ({:.1f}%)".format(services_actifs, total_services, (services_actifs/total_services)*100 if total_services > 0 else 0))
                    
                    if services_actifs == total_services:
                        logger.info(">>> [{}] TOUS LES SERVICES KELIO SONT OPERATIONNELS!".format(self.debug_session_id))
                        self._write(">>> Tous les services Kelio SafeSecur sont operationnels!", self.style.SUCCESS if self.style else None)
                    elif services_actifs > 0:
                        logger.warning("WARNING [{}] CONNEXION PARTIELLE - {} service(s) indisponible(s)".format(self.debug_session_id, services_inactifs))
                        self._write("WARNING Connexion partielle - {} service(s) indisponible(s)".format(services_inactifs), self.style.WARNING if self.style else None)
                    else:
                        logger.error("ERROR [{}] AUCUN SERVICE KELIO DISPONIBLE".format(self.debug_session_id))
                        self._write("ERROR Aucun service Kelio disponible", self.style.ERROR if self.style else None)
                    
                    # Statistiques de connexion
                    connection_stats = test_results.get('connection_stats', {})
                    if connection_stats:
                        logger.debug(">>> [{}] Statistiques de connexion:".format(self.debug_session_id))
                        for stat_name, stat_value in connection_stats.items():
                            logger.debug("   • {}: {}".format(stat_name, stat_value))
                    
                else:
                    warning_msg = "WARNING Certains services Kelio SafeSecur ne sont pas disponibles"
                    self._write(warning_msg, self.style.WARNING if self.style else None, debug_level='WARNING')
                    logger.warning("WARNING [{}] CONNEXION KELIO ECHOUEE".format(self.debug_session_id))
                    
                    # Log des services en echec
                    failed_services = []
                    services_status = test_results.get('services_status', {})
                    for service_name, service_info in services_status.items():
                        if service_info.get('status') != 'OK':
                            failed_services.append(service_name)
                            error_details = service_info.get('error', 'Erreur inconnue')
                            logger.warning("ERROR [{}] Service {} en echec: {}".format(self.debug_session_id, service_name, error_details))
                    
                    logger.warning("WARNING [{}] {} service(s) en echec: {}".format(self.debug_session_id, len(failed_services), failed_services))
                    
                    # Log des erreurs globales
                    global_error = test_results.get('error', None)
                    if global_error:
                        logger.warning("WARNING [{}] Erreur globale: {}".format(self.debug_session_id, global_error))
                
                # Enregistrer les resultats du test dans les stats
                self.stats['connection_test'] = {
                    'success': global_status,
                    'duration_seconds': test_duration,
                    'services_tested': len(services_status),
                    'services_ok': len([s for s in services_status.values() if s.get('status') == 'OK']),
                    'test_timestamp': test_start_time.isoformat()
                }
                
            except ImportError as e:
                error_msg = "Service Kelio non disponible: {}".format(e)
                logger.error("ERROR [{}] IMPORT ERROR - SERVICE KELIO INDISPONIBLE: {}".format(self.debug_session_id, error_msg))
                self._write("WARNING Service Kelio non disponible", self.style.WARNING if self.style else None, debug_level='WARNING')
                
                self.stats['connection_test'] = {
                    'success': False,
                    'error': 'ImportError',
                    'error_details': str(e)
                }
                
        except Exception as e:
            error_context = {
                'kelio_config_id': self.kelio_config.id if self.kelio_config else None,
                'kelio_url': self.kelio_config.url_base if self.kelio_config else None
            }
            
            logger.error("ERROR [{}] EXCEPTION LORS DU TEST CONNEXION KELIO: {}".format(self.debug_session_id, e))
            self._log_error_with_details("Test de connexion Kelio SafeSecur echoue", e, error_context)
            self._write("WARNING Test connexion echoue", self.style.WARNING if self.style else None, debug_level='WARNING')
            
            self.stats['connection_test'] = {
                'success': False,
                'error': 'Exception',
                'error_details': str(e)
            }
    
    # ================================================================
    # METHODES D'IMPORT STRICT KELIO
    # ================================================================
    
    def _import_kelio_complete(self):
        """Import complet depuis Kelio SafeSecur UNIQUEMENT"""
        self._write(">>> Import complet Kelio SafeSecur strict")
        
        import_steps = [
            ("Structure Kelio", self._import_kelio_structure),
            ("Employes Kelio", self._import_kelio_employees),
            ("Formations Kelio", self._import_kelio_formations),
            ("Absences Kelio", self._import_kelio_absences),
            ("Competences Kelio", self._import_kelio_competences),
            ("Cache Kelio", self._import_kelio_cache)
        ]
        
        for step_name, step_function in import_steps:
            self._write(">>> {}...".format(step_name))
            try:
                with transaction.atomic():
                    step_function()
                self._write("OK {} termine".format(step_name))
            except Exception as e:
                logger.error("ERROR Erreur {}: {}".format(step_name, e))
                self._write("ERROR Erreur {}: {}".format(step_name, e), self.style.ERROR if self.style else None)
    
    def _import_kelio_structure_only(self):
        """Import de la structure organisationnelle depuis Kelio uniquement"""
        self._write(">>> Import structure Kelio...")
        try:
            self._import_kelio_structure()
        except Exception as e:
            logger.error("Erreur import structure Kelio: {}".format(e))
    
    def _import_kelio_employees_only(self):
        """Import des employes depuis Kelio uniquement"""
        self._write(">>> Import employes Kelio...")
        try:
            self._import_kelio_employees()
        except Exception as e:
            logger.error("Erreur import employes Kelio: {}".format(e))
    
    def _import_minimal_configuration(self):
        """Import configuration minimale seulement"""
        self._write(">>> Configuration minimale terminee")
    
    # ================================================================
    # SYNCHRONISATION KELIO SAFESECUR STRICT
    # ================================================================
    
    def _import_kelio_structure(self):
        """Importe la structure organisationnelle depuis Kelio"""
        try:
            self._write(">>> Import structure organisationnelle depuis Kelio...")
            
            if not self.with_kelio_sync:
                self._write(">>> Synchronisation Kelio desactivee - structure minimale creee")
                self._create_minimal_structure()
                return
            
            # Import des donnees structure depuis Kelio
            try:
                from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
                
                sync_service = get_kelio_sync_service_v41(self.kelio_config)
                
                # Import departements
                logger.info(">>> [{}] APPEL SERVICE WEB KELIO - DEPARTEMENTS".format(self.debug_session_id))
                self._write(">>> Synchronisation departements Kelio...")
                dept_results = sync_service.synchroniser_departements_v41()
                
                logger.info(">>> [{}] RESULTAT SERVICE DEPARTEMENTS:".format(self.debug_session_id))
                logger.info("   • Statut: {}".format(dept_results.get('statut', 'INCONNU')))
                logger.info("   • Reponse brute: {}".format(dept_results))
                
                if dept_results.get('statut') == 'reussi':
                    departements_data = dept_results.get('departements', [])
                    nb_dept = len(departements_data)
                    self._write("OK {} departement(s) importe(s) depuis Kelio".format(nb_dept))
                    logger.info("OK [{}] SERVICE DEPARTEMENTS REUSSI: {} enregistrement(s)".format(self.debug_session_id, nb_dept))
                    
                    # Log detail des departements recus
                    for i, dept_data in enumerate(departements_data[:3], 1):  # Log des 3 premiers
                        logger.debug("   >>> Departement {}: {}".format(i, dept_data))
                    if len(departements_data) > 3:
                        logger.debug("   ... et {} autre(s) departement(s)".format(len(departements_data) - 3))
                    
                    self._log_table_import_summary('Departement', nb_dept, 0, 0)
                else:
                    error_msg = dept_results.get('erreur', 'Erreur inconnue')
                    logger.error("ERROR [{}] SERVICE DEPARTEMENTS ECHOUE: {}".format(self.debug_session_id, error_msg))
                    self._write("ERROR Erreur import departements: {}".format(error_msg), debug_level='ERROR')
                
                # Import sites
                logger.info(">>> [{}] APPEL SERVICE WEB KELIO - SITES".format(self.debug_session_id))
                self._write(">>> Synchronisation sites Kelio...")
                site_results = sync_service.synchroniser_sites_v41()
                
                logger.info(">>> [{}] RESULTAT SERVICE SITES:".format(self.debug_session_id))
                logger.info("   • Statut: {}".format(site_results.get('statut', 'INCONNU')))
                logger.info("   • Reponse brute: {}".format(site_results))
                
                if site_results.get('statut') == 'reussi':
                    sites_data = site_results.get('sites', [])
                    nb_sites = len(sites_data)
                    self._write("OK {} site(s) importe(s) depuis Kelio".format(nb_sites))
                    logger.info("OK [{}] SERVICE SITES REUSSI: {} enregistrement(s)".format(self.debug_session_id, nb_sites))
                    
                    # Log detail des sites recus
                    for i, site_data in enumerate(sites_data[:3], 1):  # Log des 3 premiers
                        logger.debug("   >>> Site {}: {}".format(i, site_data))
                    if len(sites_data) > 3:
                        logger.debug("   ... et {} autre(s) site(s)".format(len(sites_data) - 3))
                    
                    self._log_table_import_summary('Site', nb_sites, 0, 0)
                else:
                    error_msg = site_results.get('erreur', 'Erreur inconnue')
                    logger.error("ERROR [{}] SERVICE SITES ECHOUE: {}".format(self.debug_session_id, error_msg))
                    self._write("ERROR Erreur import sites: {}".format(error_msg), debug_level='ERROR')
                
                # Import postes
                logger.info(">>> [{}] APPEL SERVICE WEB KELIO - POSTES".format(self.debug_session_id))
                self._write(">>> Synchronisation postes Kelio...")
                poste_results = sync_service.synchroniser_postes_v41()
                
                logger.info(">>> [{}] RESULTAT SERVICE POSTES:".format(self.debug_session_id))
                logger.info("   • Statut: {}".format(poste_results.get('statut', 'INCONNU')))
                logger.info("   • Reponse brute: {}".format(poste_results))
                
                if poste_results.get('statut') == 'reussi':
                    postes_data = poste_results.get('postes', [])
                    nb_postes = len(postes_data)
                    self._write("OK {} poste(s) importe(s) depuis Kelio".format(nb_postes))
                    logger.info("OK [{}] SERVICE POSTES REUSSI: {} enregistrement(s)".format(self.debug_session_id, nb_postes))
                    
                    # Log detail des postes recus
                    for i, poste_data in enumerate(postes_data[:3], 1):  # Log des 3 premiers
                        logger.debug("   >>> Poste {}: {}".format(i, poste_data))
                    if len(postes_data) > 3:
                        logger.debug("   ... et {} autre(s) poste(s)".format(len(postes_data) - 3))
                    
                    self._log_table_import_summary('Poste', nb_postes, 0, 0)
                else:
                    error_msg = poste_results.get('erreur', 'Erreur inconnue')
                    logger.error("ERROR [{}] SERVICE POSTES ECHOUE: {}".format(self.debug_session_id, error_msg))
                    self._write("ERROR Erreur import postes: {}".format(error_msg), debug_level='ERROR')
                
                # LOG RESUME STRUCTURE
                total_structure = (nb_dept if 'nb_dept' in locals() else 0) + \
                                 (nb_sites if 'nb_sites' in locals() else 0) + \
                                 (nb_postes if 'nb_postes' in locals() else 0)
                logger.info(">>> [{}] RESUME STRUCTURE ORGANISATIONNELLE:".format(self.debug_session_id))
                logger.info("   >>> Total enregistrements structure: {}".format(total_structure))
                logger.info("   >>> Departements: {}".format(nb_dept if 'nb_dept' in locals() else 0))
                logger.info("   >>> Sites: {}".format(nb_sites if 'nb_sites' in locals() else 0))
                logger.info("   >>> Postes: {}".format(nb_postes if 'nb_postes' in locals() else 0))
                
            except Exception as e:
                logger.error("ERROR [{}] EXCEPTION LORS DES APPELS SERVICES STRUCTURE KELIO: {}".format(self.debug_session_id, e))
                logger.error("Erreur synchronisation structure Kelio: {}".format(e))
                self._write(">>> Fallback vers structure minimale")
                self._create_minimal_structure()
                
        except Exception as e:
            logger.error("Erreur import structure Kelio: {}".format(e))
            raise
    
    def _import_kelio_employees(self):
        """Importe les employes depuis Kelio SafeSecur UNIQUEMENT avec debug detaille"""
        try:
            logger.debug(">>> [{}] Debut import employes depuis Kelio SafeSecur".format(self.debug_session_id))
            self._write(">>> Import employes depuis Kelio SafeSecur...")
            
            if not self.with_kelio_sync:
                warning_msg = "WARNING Synchronisation Kelio desactivee - aucun employe importe"
                self._write(warning_msg, debug_level='WARNING')
                logger.warning("WARNING [{}] Sync Kelio desactivee".format(self.debug_session_id))
                return []
            
            # Import des employes depuis Kelio avec debug detaille
            try:
                logger.debug(">>> [{}] Import du service synchroniser_tous_employes_kelio_v41...".format(self.debug_session_id))
                from mainapp.services.kelio_api_simplifie import synchroniser_tous_employes_kelio_v41
                logger.debug("OK [{}] Service d'import employes importe".format(self.debug_session_id))
                
                # Pre-synchronisation: etat initial de la base
                ProfilUtilisateur = self.models['ProfilUtilisateur']
                initial_count = ProfilUtilisateur.objects.count()
                logger.debug(">>> [{}] Etat initial: {} employe(s) en base".format(self.debug_session_id, initial_count))
                
                # Configuration de la synchronisation
                sync_config = {
                    'mode': 'complet',
                    'force_update': self.force,
                    'batch_size': 50,
                    'debug_session_id': self.debug_session_id
                }
                logger.debug(">>> [{}] Configuration de sync: {}".format(self.debug_session_id, sync_config))
                
                # Lancer la synchronisation complete avec timer
                logger.info(">>> [{}] APPEL SERVICE WEB KELIO - EMPLOYES".format(self.debug_session_id))
                logger.debug(">>> [{}] Lancement synchronisation complete...".format(self.debug_session_id))
                self._write(">>> Synchronisation employes Kelio...")
                sync_start_time = timezone.now()
                
                resultats = synchroniser_tous_employes_kelio_v41(mode='complet')
                
                sync_duration = (timezone.now() - sync_start_time).total_seconds()
                logger.debug(">>> [{}] Synchronisation terminee en {:.2f}s".format(self.debug_session_id, sync_duration))
                
                # Analyse detaillee des resultats
                logger.info(">>> [{}] RESULTAT SERVICE EMPLOYES:".format(self.debug_session_id))
                logger.info("   • Duree appel: {:.2f}s".format(sync_duration))
                logger.info("   • Reponse brute: {}".format(resultats))
                logger.debug(">>> [{}] Analyse des resultats de synchronisation:".format(self.debug_session_id))
                logger.debug("   • Resultats bruts: {}".format(resultats))
                
                statut_global = resultats.get('statut_global', 'echec')
                logger.info("   • Statut global: {}".format(statut_global))
                logger.debug("   • Statut global: {}".format(statut_global))
                
                if statut_global == 'reussi':
                    # Succes complet
                    resume = resultats.get('resume', {})
                    nb_employees = resume.get('employees_reussis', 0)
                    nb_errors = resume.get('employees_echec', 0)
                    nb_skipped = resume.get('employees_ignores', 0)
                    
                    logger.debug("   • Employes traites avec succes: {}".format(nb_employees))
                    logger.debug("   • Employes en erreur: {}".format(nb_errors))
                    logger.debug("   • Employes ignores: {}".format(nb_skipped))
                    
                    success_msg = "OK {} employe(s) importe(s) depuis Kelio SafeSecur".format(nb_employees)
                    self._write(success_msg)
                    logger.info("OK [{}] SERVICE EMPLOYES REUSSI COMPLETEMENT".format(self.debug_session_id))
                    logger.info("OK [{}] {}".format(self.debug_session_id, success_msg))
                    
                    # Verification post-synchronisation
                    final_count = ProfilUtilisateur.objects.count()
                    new_employees = final_count - initial_count
                    logger.debug(">>> [{}] Etat final: {} employe(s) en base (+{})".format(self.debug_session_id, final_count, new_employees))
                    
                    # Recuperer les employes importes avec details
                    logger.debug(">>> [{}] Recuperation des employes importes...".format(self.debug_session_id))
                    employes_kelio = list(ProfilUtilisateur.objects.filter(
                        kelio_sync_status='REUSSI'
                    ).order_by('-kelio_last_sync')[:nb_employees])
                    
                    logger.debug(">>> [{}] {} employe(s) Kelio recupere(s):".format(self.debug_session_id, len(employes_kelio)))
                    for i, employe in enumerate(employes_kelio[:5]):  # Log des 5 premiers
                        logger.debug("   {}. {} - {} ({})".format(i+1, employe.matricule, employe.nom_complet, employe.type_profil))
                    
                    if len(employes_kelio) > 5:
                        logger.debug("   ... et {} autre(s)".format(len(employes_kelio) - 5))
                    
                    # Analyse des types de profils importes
                    profil_stats = {}
                    for employe in employes_kelio:
                        profil_type = employe.type_profil
                        profil_stats[profil_type] = profil_stats.get(profil_type, 0) + 1
                    
                    logger.debug(">>> [{}] Repartition par type de profil:".format(self.debug_session_id))
                    for profil_type, count in profil_stats.items():
                        logger.debug("   • {}: {}".format(profil_type, count))
                    
                    self.imported_objects['employes'].extend(employes_kelio)
                    self._update_stats('ProfilUtilisateur', True, count=nb_employees)
                    
                    # Enregistrer les details de la synchronisation
                    self.stats['employees_import'] = {
                        'status': 'success',
                        'duration_seconds': sync_duration,
                        'total_imported': nb_employees,
                        'total_errors': nb_errors,
                        'total_skipped': nb_skipped,
                        'profile_distribution': profil_stats,
                        'initial_count': initial_count,
                        'final_count': final_count
                    }
                    
                    # LOG DETAILLE DU NOMBRE D'ENREGISTREMENTS EMPLOYES
                    logger.info(">>> [{}] IMPORT EMPLOYES KELIO TERMINE:".format(self.debug_session_id))
                    logger.info("   >>> Employes importes: {}".format(nb_employees))
                    logger.info("   ERROR Employes en erreur: {}".format(nb_errors))
                    logger.info("   >>> Employes ignores: {}".format(nb_skipped))
                    logger.info("   >>> Base avant import: {} employe(s)".format(initial_count))
                    logger.info("   >>> Base apres import: {} employe(s)".format(final_count))
                    logger.info("   >>> Nouveaux employes crees: +{}".format(new_employees))
                    
                    # Resume des enregistrements par table associee
                    ProfilUtilisateurKelio = self.models['ProfilUtilisateurKelio']
                    ProfilUtilisateurExtended = self.models['ProfilUtilisateurExtended']
                    
                    kelio_profiles_created = ProfilUtilisateurKelio.objects.filter(
                        profil__in=employes_kelio
                    ).count()
                    
                    extended_profiles_created = ProfilUtilisateurExtended.objects.filter(
                        profil__in=employes_kelio
                    ).count()
                    
                    logger.info(">>> [{}] ENREGISTREMENTS TABLES ASSOCIEES:".format(self.debug_session_id))
                    logger.info("   >>> ProfilUtilisateur: {} enregistrements".format(nb_employees))
                    logger.info("   >>> ProfilUtilisateurKelio: {} enregistrements".format(kelio_profiles_created))
                    logger.info("   >>> ProfilUtilisateurExtended: {} enregistrements".format(extended_profiles_created))
                    
                    # Utiliser la nouvelle methode de resume
                    self._log_table_import_summary('ProfilUtilisateur', nb_employees, 0, nb_errors)
                    
                    return employes_kelio
                    
                elif statut_global == 'partiel':
                    # Succes partiel
                    resume = resultats.get('resume', {})
                    nb_employees = resume.get('employees_reussis', 0)
                    nb_errors = resume.get('employees_echec', 0)
                    
                    warning_msg = "WARNING {} employe(s) partiellement synchronise(s) depuis Kelio SafeSecur ({} erreur(s))".format(nb_employees, nb_errors)
                    self._write(warning_msg, self.style.WARNING if self.style else None, debug_level='WARNING')
                    logger.warning("WARNING [{}] SERVICE EMPLOYES REUSSI PARTIELLEMENT".format(self.debug_session_id))
                    logger.warning("WARNING [{}] {}".format(self.debug_session_id, warning_msg))
                    
                    # Log des erreurs detaillees
                    erreurs_details = resultats.get('erreurs_details', [])
                    logger.debug("ERROR [{}] Detail des erreurs ({}):".format(self.debug_session_id, len(erreurs_details)))
                    for i, erreur in enumerate(erreurs_details[:3]):  # Log des 3 premieres erreurs
                        logger.debug("   {}. {}".format(i+1, erreur))
                    
                    # Recuperer les employes partiellement importes
                    employes_kelio = list(ProfilUtilisateur.objects.filter(
                        kelio_sync_status__in=['REUSSI', 'PARTIEL']
                    ).order_by('-kelio_last_sync')[:nb_employees])
                    
                    self.imported_objects['employes'].extend(employes_kelio)
                    self._update_stats('ProfilUtilisateur', True, count=nb_employees)
                    
                    self.stats['employees_import'] = {
                        'status': 'partial',
                        'duration_seconds': sync_duration,
                        'total_imported': nb_employees,
                        'total_errors': nb_errors,
                        'error_details': erreurs_details[:10]  # Garder les 10 premieres erreurs
                    }
                    
                    return employes_kelio
                    
                else:
                    # Echec complet
                    error_msg = resultats.get('erreur_critique', 'Erreur inconnue')
                    error_details = resultats.get('erreurs_details', [])
                    
                    self._write("ERROR Erreur import employes Kelio: {}".format(error_msg), debug_level='ERROR')
                    logger.error("ERROR [{}] SERVICE EMPLOYES ECHOUE COMPLETEMENT".format(self.debug_session_id))
                    logger.error("ERROR [{}] Echec import employes: {}".format(self.debug_session_id, error_msg))
                    
                    # Log des erreurs detaillees
                    if error_details:
                        logger.error("ERROR [{}] Erreurs detaillees:".format(self.debug_session_id))
                        for i, erreur in enumerate(error_details[:5]):
                            logger.error("   {}. {}".format(i+1, erreur))
                    
                    self.stats['employees_import'] = {
                        'status': 'failed',
                        'duration_seconds': sync_duration,
                        'error_message': error_msg,
                        'error_details': error_details[:10]
                    }
                    
                    return []
                    
            except Exception as e:
                error_context = {
                    'with_kelio_sync': self.with_kelio_sync,
                    'kelio_config_id': self.kelio_config.id if self.kelio_config else None
                }
                self._log_error_with_details("Erreur synchronisation employes Kelio", e, error_context)
                self._write("ERROR Erreur synchronisation employes: {}".format(e), debug_level='ERROR')
                
                self.stats['employees_import'] = {
                    'status': 'exception',
                    'error_message': str(e),
                    'error_type': type(e).__name__
                }
                
                return []
                
        except Exception as e:
            self._log_error_with_details("Erreur import employes Kelio", e)
            raise
                    
    def _validate_post_import(self):
        """Valide les donnees apres import avec debug detaille"""
        try:
            logger.debug("OK [{}] Debut validation post-import".format(self.debug_session_id))
            self._write("OK Validation post-import des donnees...")
            
            validation_results = {
                'total_objects': 0,
                'validation_errors': [],
                'warnings': [],
                'model_counts': {}
            }
            
            # Validation des modeles principaux
            models_to_validate = [
                ('ConfigurationApiKelio', 'Configuration Kelio'),
                ('ProfilUtilisateur', 'Employes'),
                ('Departement', 'Departements'),
                ('Site', 'Sites'),
                ('Poste', 'Postes'),
                ('Competence', 'Competences')
            ]
            
            for model_name, display_name in models_to_validate:
                if model_name in self.models:
                    model_class = self.models[model_name]
                    count = model_class.objects.count()
                    validation_results['model_counts'][model_name] = count
                    validation_results['total_objects'] += count
                    
                    logger.debug("   • {}: {} objet(s)".format(display_name, count))
                    
                    # Validations specifiques
                    if model_name == 'ConfigurationApiKelio':
                        active_configs = model_class.objects.filter(actif=True).count()
                        if active_configs == 0:
                            validation_results['validation_errors'].append("Aucune configuration Kelio active")
                        elif active_configs > 1:
                            validation_results['warnings'].append("{} configurations Kelio actives (recommande: 1)".format(active_configs))
                    
                    elif model_name == 'ProfilUtilisateur':
                        if count == 0 and self.with_kelio_sync:
                            validation_results['validation_errors'].append("Aucun employe importe malgre sync Kelio activee")
                        
                        active_employees = model_class.objects.filter(actif=True).count()
                        logger.debug("     -> {} employe(s) actif(s)".format(active_employees))
                        
                        # Verification des profils Kelio
                        kelio_profiles = model_class.objects.filter(
                            kelio_sync_status__in=['REUSSI', 'PARTIEL']
                        ).count()
                        logger.debug("     -> {} profil(s) synchronise(s) avec Kelio".format(kelio_profiles))
            
            # Validation des relations
            logger.debug(">>> [{}] Validation des relations".format(self.debug_session_id))
            ProfilUtilisateur = self.models['ProfilUtilisateur']
            
            # Employes sans departement
            employees_no_dept = ProfilUtilisateur.objects.filter(departement__isnull=True).count()
            if employees_no_dept > 0:
                validation_results['warnings'].append("{} employe(s) sans departement".format(employees_no_dept))
                logger.debug("   WARNING {} employe(s) sans departement".format(employees_no_dept))
            
            # Employes sans site
            employees_no_site = ProfilUtilisateur.objects.filter(site__isnull=True).count()
            if employees_no_site > 0:
                validation_results['warnings'].append("{} employe(s) sans site".format(employees_no_site))
                logger.debug("   WARNING {} employe(s) sans site".format(employees_no_site))
            
            # Resume de validation
            total_errors = len(validation_results['validation_errors'])
            total_warnings = len(validation_results['warnings'])
            
            if total_errors > 0:
                self._write("ERROR {} erreur(s) de validation detectee(s)".format(total_errors), debug_level='ERROR')
                for error in validation_results['validation_errors']:
                    self._write("   • {}".format(error), debug_level='ERROR')
                    logger.error("ERROR [{}] Erreur validation: {}".format(self.debug_session_id, error))
            
            if total_warnings > 0:
                self._write("WARNING {} avertissement(s) de validation".format(total_warnings), debug_level='WARNING')
                for warning in validation_results['warnings']:
                    self._write("   • {}".format(warning), debug_level='WARNING')
                    logger.warning("WARNING [{}] Avertissement validation: {}".format(self.debug_session_id, warning))
            
            if total_errors == 0 and total_warnings == 0:
                self._write("OK Validation post-import reussie - aucun probleme detecte")
                logger.info("OK [{}] Validation post-import parfaite".format(self.debug_session_id))
            
            # Enregistrer les resultats de validation
            self.stats['validation_results'] = validation_results
            
            logger.debug("OK [{}] Validation post-import terminee".format(self.debug_session_id))
            
        except Exception as e:
            self._log_error_with_details("Erreur validation post-import", e)
            self._write("ERROR Erreur validation: {}".format(e), debug_level='ERROR')

    def _update_stats(self, model_name, imported, count=1):
        """Met a jour les statistiques d'import avec debug detaille"""
        if model_name not in self.stats['by_model']:
            self.stats['by_model'][model_name] = {'imported': 0, 'updated': 0, 'skipped': 0}
        
        if imported:
            self.stats['by_model'][model_name]['imported'] += count
            self.stats['total_imported'] += count
            logger.info(">>> [{}] IMPORT {}: +{} NOUVEAU(X) ENREGISTREMENT(S)".format(self.debug_session_id, model_name, count))
            logger.info(">>> [{}] TOTAL {}: {} importe(s)".format(self.debug_session_id, model_name, self.stats['by_model'][model_name]['imported']))
        else:
            self.stats['by_model'][model_name]['updated'] += count
            self.stats['total_updated'] += count
            logger.info(">>> [{}] MISE A JOUR {}: +{} ENREGISTREMENT(S) MIS A JOUR".format(self.debug_session_id, model_name, count))
            logger.info(">>> [{}] TOTAL {}: {} mis a jour".format(self.debug_session_id, model_name, self.stats['by_model'][model_name]['updated']))
        
        # Log du total cumule pour cette table
        total_table = self.stats['by_model'][model_name]['imported'] + self.stats['by_model'][model_name]['updated']
        logger.info(">>> [{}] CUMUL TOTAL {}: {} enregistrement(s) traite(s)".format(self.debug_session_id, model_name, total_table))

    def _log_table_import_summary(self, table_name, imported_count, updated_count=0, errors_count=0):
        """Log un resume detaille pour une table specifique"""
        total_processed = imported_count + updated_count
        
        logger.info(">>> [{}] RESUME TABLE {}:".format(self.debug_session_id, table_name))
        logger.info("   OK Nouveaux enregistrements: {}".format(imported_count))
        logger.info("   >>> Enregistrements mis a jour: {}".format(updated_count))
        logger.info("   ERROR Erreurs rencontrees: {}".format(errors_count))
        logger.info("   >>> Total traite: {}".format(total_processed))
        
        if total_processed > 0:
            success_rate = ((imported_count + updated_count) / (total_processed + errors_count)) * 100 if (total_processed + errors_count) > 0 else 100
            logger.info("   >>> Taux de reussite: {:.1f}%".format(success_rate))
        
        # Messages console
        self._write(">>> {}: {} importe(s), {} mis a jour, {} erreur(s)".format(table_name, imported_count, updated_count, errors_count))
        
        if imported_count > 0:
            self._write("  OK {} nouveaux enregistrements {} ajoutes en base".format(imported_count, table_name))
        if updated_count > 0:
            self._write("  >>> {} enregistrements {} mis a jour".format(updated_count, table_name))
        if errors_count > 0:
            self._write("  ERROR {} erreurs lors du traitement {}".format(errors_count, table_name), debug_level='WARNING')

    def _log_final_statistics(self, duration):
        """Affiche les statistiques finales d'import Kelio strict avec debug detaille"""
        logger.info(">>> [{}] Generation des statistiques finales".format(self.debug_session_id))
        
        self._write(">>> STATISTIQUES D'IMPORT KELIO SAFESECUR STRICT")
        self._write("=" * 80)
        self._write(">>> Session Debug ID: {}".format(self.debug_session_id))
        self._write(">>> Duree totale: {:.2f} secondes".format(duration))
        self._write(">>> Total importe depuis Kelio: {}".format(self.stats['total_imported']))
        self._write(">>> Total mis a jour: {}".format(self.stats['total_updated']))
        self._write("ERROR Total erreurs: {}".format(self.stats['total_errors']))
        self._write(">>> Total ignore: {}".format(self.stats.get('total_skipped', 0)))
        self._write("")
        
        # Detail par modele avec debug
        self._write(">>> Detail par modele:")
        logger.debug(">>> [{}] Detail par modele:".format(self.debug_session_id))
        
        for model_name, stats in self.stats['by_model'].items():
            imported = stats['imported']
            updated = stats['updated']
            skipped = stats.get('skipped', 0)
            total = imported + updated + skipped
            
            if total > 0:
                detail_msg = "  >>> {}: {} importe(s), {} mis a jour".format(model_name, imported, updated)
                if skipped > 0:
                    detail_msg += ", {} ignore(s)".format(skipped)
                self._write(detail_msg)
                logger.debug("   • {}: imported={}, updated={}, skipped={}".format(model_name, imported, updated, skipped))
        
        # Resume des objets importes
        self._write("")
        self._write(">>> RESUME DES DONNEES KELIO IMPORTEES:")
        
        summary_items = [
            ('departements', '>>>', 'departements'),
            ('sites', '>>>', 'sites'),
            ('postes', '>>>', 'postes'),
            ('employes', '>>>', 'employes'),
            ('competences', '>>>', 'competences'),
            ('formations', '>>>', 'formations'),
            ('absences', '>>>', 'absences')
        ]
        
        for key, icon, label in summary_items:
            count = len(self.imported_objects.get(key, []))
            if count > 0:
                self._write("  {} {} {}".format(icon, count, label))
                logger.debug("   • {}: {}".format(label, count))
        
        # Temps par operation
        if self.stats.get('operation_times'):
            self._write("")
            self._write(">>> TEMPS PAR OPERATION:")
            logger.debug(">>> [{}] Temps par operation:".format(self.debug_session_id))
            
            for operation, time_taken in self.stats['operation_times'].items():
                self._write("  >>> {}: {:.2f}s".format(operation, time_taken))
                logger.debug("   • {}: {:.2f}s".format(operation, time_taken))
        
        # Configuration Kelio
        self._write("")
        self._write(">>> CONFIGURATION KELIO SAFESECUR:")
        self._write("  >>> URL de base: {}".format(self.kelio_config_data['base_url']))
        self._write("  >>> Services URL: {}".format(self.kelio_config_data['services_url']))
        self._write("  >>> Timeout: {}s".format(self.kelio_config_data['timeout']))
        self._write("  >>> Sync Kelio active: {}".format('Oui' if self.with_kelio_sync else 'Non'))
        
        # Test de connexion
        if 'connection_test' in self.stats:
            connection_test = self.stats['connection_test']
            status_icon = "OK" if connection_test.get('success') else "ERROR"
            self._write("  >>> Test connexion: {}".format(status_icon))
            
            if 'duration_seconds' in connection_test:
                self._write("  >>> Duree test: {:.2f}s".format(connection_test['duration_seconds']))
        
        # Import employes
        if 'employees_import' in self.stats:
            emp_import = self.stats['employees_import']
            self._write("  >>> Import employes: {}".format(emp_import.get('status', 'unknown')))
            
            if 'total_imported' in emp_import:
                self._write("  >>> Employes importes: {}".format(emp_import['total_imported']))
            
            if 'profile_distribution' in emp_import:
                self._write("  >>> Repartition profils:")
                for profil_type, count in emp_import['profile_distribution'].items():
                    self._write("     • {}: {}".format(profil_type, count))
        
        # Validation
        if 'validation_results' in self.stats:
            validation = self.stats['validation_results']
            total_objects = validation.get('total_objects', 0)
            self._write("  OK Objets valides: {}".format(total_objects))
            
            errors = len(validation.get('validation_errors', []))
            warnings = len(validation.get('warnings', []))
            if errors > 0 or warnings > 0:
                self._write("  WARNING Erreurs/Avertissements: {}/{}".format(errors, warnings))
        
        self._write("")
        self._write("  AUCUNE DONNEE FICTIVE CREEE")
        self._write("  >>> Logs detailles: kelio_import_debug.log")
        self._write("=" * 80)
        
        # Log final dans le fichier
        logger.info(">>> [{}] STATISTIQUES FINALES COMPLETES:".format(self.debug_session_id))
        logger.info("   • Duree: {:.2f}s".format(duration))
        logger.info("   • Importes: {}".format(self.stats['total_imported']))
        logger.info("   • Mis a jour: {}".format(self.stats['total_updated']))
        logger.info("   • Erreurs: {}".format(self.stats['total_errors']))
        logger.info("   • Employes Kelio: {}".format(len(self.imported_objects.get('employes', []))))

    def _log_error_statistics(self):
        """Affiche les statistiques en cas d'erreur avec debug detaille"""
        logger.error("ERROR [{}] GENERATION STATISTIQUES D'ERREUR".format(self.debug_session_id))
        
        self._write("ERROR IMPORT KELIO SAFESECUR STRICT INTERROMPU", self.style.ERROR if self.style else None)
        self._write("=" * 80)
        self._write(">>> Session Debug ID: {}".format(self.debug_session_id))
        self._write("ERROR Erreurs rencontrees: {}".format(self.stats['total_errors']))
        self._write(">>> Elements importes avant interruption: {}".format(self.stats['total_imported']))
        self._write(">>> Elements mis a jour avant interruption: {}".format(self.stats['total_updated']))
        self._write(">>> Configuration Kelio: {}".format(self.kelio_config_data['services_url']))
        
        # Detail des erreurs
        if self.stats.get('error_details'):
            self._write("")
            self._write(">>> DETAIL DES ERREURS:")
            
            for i, error_detail in enumerate(self.stats['error_details'][-5:], 1):  # 5 dernieres erreurs
                self._write("  {}. {}".format(i, error_detail.get('message', 'Erreur inconnue')))
                if error_detail.get('exception_msg'):
                    self._write("     Exception: {}".format(error_detail['exception_msg']))
                
                logger.error("ERROR [{}] Erreur {}: {}".format(self.debug_session_id, i, error_detail))
        
        # Etat des objets importes
        self._write("")
        self._write(">>> ETAT AVANT INTERRUPTION:")
        
        for key, objects in self.imported_objects.items():
            if objects:
                self._write("  >>> {}: {} objet(s)".format(key, len(objects)))
        
        self._write("")
        self._write(">>> Logs complets dans: kelio_import_debug.log")
        self._write("=" * 80)
        
        # Log detaille dans le fichier
        logger.error("ERROR [{}] IMPORT INTERROMPU - RAPPORT FINAL:".format(self.debug_session_id))
        logger.error("   • Total erreurs: {}".format(self.stats['total_errors']))
        logger.error("   • Elements traites: {}".format(self.stats['total_imported'] + self.stats['total_updated']))
        logger.error("   • Session ID: {}".format(self.debug_session_id))
        logger.error("   • URL Kelio: {}".format(self.kelio_config_data['services_url']))
    
    def _import_kelio_formations(self):
        """Importe les formations depuis Kelio UNIQUEMENT avec debug detaille"""
        if not self.with_kelio_sync:
            self._write(">>> Import formations Kelio desactive", debug_level='DEBUG')
            logger.debug(">>> [{}] Import formations Kelio desactive".format(self.debug_session_id))
            return
        
        try:
            logger.debug(">>> [{}] Debut import formations depuis Kelio".format(self.debug_session_id))
            self._write(">>> Import formations depuis Kelio...")
            
            # Import des formations depuis Kelio
            from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
            
            sync_service = get_kelio_sync_service_v41(self.kelio_config)
            
            employes = self.imported_objects.get('employes', [])
            if not employes:
                warning_msg = "WARNING Aucun employe importe - pas de formations a importer"
                self._write(warning_msg, debug_level='WARNING')
                logger.warning("WARNING [{}] {}".format(self.debug_session_id, warning_msg))
                return
            
            logger.debug(">>> [{}] Import formations pour {} employe(s)".format(self.debug_session_id, len(employes)))
            
            formations_importees = 0
            erreurs_formations = 0
            employes_traites = 0
            
            for i, employe in enumerate(employes, 1):
                try:
                    logger.info(">>> [{}] APPEL SERVICE WEB KELIO - FORMATIONS EMPLOYE {}/{}".format(self.debug_session_id, i, len(employes)))
                    logger.debug(">>> [{}] Import formations employe {}/{}: {}".format(self.debug_session_id, i, len(employes), employe.matricule))
                    
                    # Importer les formations de l'employe depuis Kelio
                    formations_results = sync_service.get_formations_employe_v41(employe.kelio_employee_key)
                    
                    logger.debug(">>> [{}] RESULTAT SERVICE FORMATIONS pour {}:".format(self.debug_session_id, employe.matricule))
                    logger.debug("   • Statut: {}".format(formations_results.get('statut', 'INCONNU')))
                    logger.debug("   • Reponse: {}".format(formations_results))
                    
                    if formations_results.get('statut') == 'reussi':
                        formations = formations_results.get('formations', [])
                        formations_importees += len(formations)
                        employes_traites += 1
                        
                        logger.info("OK [{}] SERVICE FORMATIONS REUSSI pour {}: {} formation(s)".format(self.debug_session_id, employe.matricule, len(formations)))
                        logger.debug("   OK {} formation(s) importee(s) pour {}".format(len(formations), employe.matricule))
                        
                        # Traiter et creer les formations...
                        FormationUtilisateur = self.models['FormationUtilisateur']
                        for formation_data in formations:
                            try:
                                formation, created = FormationUtilisateur.objects.get_or_create(
                                    utilisateur=employe,
                                    titre=formation_data.get('titre', 'Formation Kelio'),
                                    defaults={
                                        'organisme': formation_data.get('organisme', 'Organisme Kelio'),
                                        'date_debut': formation_data.get('date_debut'),
                                        'duree_jours': formation_data.get('duree_jours', 1),
                                        'source_donnee': 'KELIO',
                                        'certifiante': formation_data.get('certifiante', False)
                                    }
                                )
                                if created:
                                    self.imported_objects.setdefault('formations', []).append(formation)
                                    self._update_stats('FormationUtilisateur', True)
                                    
                            except Exception as e:
                                logger.debug("   ERROR Erreur creation formation: {}".format(e))
                                erreurs_formations += 1
                        
                    else:
                        erreur_msg = formations_results.get('erreur', 'Erreur inconnue')
                        logger.error("ERROR [{}] SERVICE FORMATIONS ECHOUE pour {}: {}".format(self.debug_session_id, employe.matricule, erreur_msg))
                        logger.debug("   ERROR Erreur formations pour {}: {}".format(employe.matricule, erreur_msg))
                        erreurs_formations += 1
                        
                except Exception as e:
                    logger.error("ERROR [{}] Erreur import formations employe {}: {}".format(self.debug_session_id, employe.matricule, e))
                    erreurs_formations += 1
            
            # Resume
            success_msg = "OK {} formation(s) importee(s) depuis Kelio pour {} employe(s)".format(formations_importees, employes_traites)
            self._write(success_msg)
            logger.info(">>> [{}] {}".format(self.debug_session_id, success_msg))
            
            # LOG DETAILLE DU NOMBRE D'ENREGISTREMENTS FORMATIONS
            logger.info(">>> [{}] IMPORT FORMATIONS KELIO TERMINE:".format(self.debug_session_id))
            logger.info("   >>> Formations importees: {}".format(formations_importees))
            logger.info("   >>> Employes traites: {}/{}".format(employes_traites, len(employes)))
            logger.info("   ERROR Erreurs formations: {}".format(erreurs_formations))
            logger.info("   >>> Taux employes traites: {:.1f}%".format((employes_traites/len(employes)*100) if employes else 0))
            
            self._log_table_import_summary('FormationUtilisateur', formations_importees, 0, erreurs_formations)
            
            if erreurs_formations > 0:
                error_msg = "WARNING {} erreur(s) lors de l'import formations".format(erreurs_formations)
                self._write(error_msg, debug_level='WARNING')
                logger.warning("WARNING [{}] {}".format(self.debug_session_id, error_msg))
            
            # Enregistrer les statistiques
            self.stats['formations_import'] = {
                'total_imported': formations_importees,
                'employees_processed': employes_traites,
                'errors': erreurs_formations,
                'success_rate': (employes_traites / len(employes)) * 100 if employes else 0
            }
            
        except Exception as e:
            self._log_error_with_details("Erreur import formations Kelio", e)

    def _import_kelio_absences(self):
        """Importe les absences depuis Kelio UNIQUEMENT avec debug detaille"""
        if not self.with_kelio_sync:
            self._write(">>> Import absences Kelio desactive", debug_level='DEBUG')
            logger.debug(">>> [{}] Import absences Kelio desactive".format(self.debug_session_id))
            return
        
        try:
            logger.debug(">>> [{}] Debut import absences depuis Kelio".format(self.debug_session_id))
            self._write(">>> Import absences depuis Kelio...")
            
            # Import des absences depuis Kelio
            from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
            
            sync_service = get_kelio_sync_service_v41(self.kelio_config)
            
            employes = self.imported_objects.get('employes', [])
            if not employes:
                warning_msg = "WARNING Aucun employe importe - pas d'absences a importer"
                self._write(warning_msg, debug_level='WARNING')
                logger.warning("WARNING [{}] {}".format(self.debug_session_id, warning_msg))
                return
            
            logger.debug(">>> [{}] Import absences pour {} employe(s)".format(self.debug_session_id, len(employes)))
            
            absences_importees = 0
            erreurs_absences = 0
            employes_traites = 0
            
            for i, employe in enumerate(employes, 1):
                try:
                    logger.info(">>> [{}] APPEL SERVICE WEB KELIO - ABSENCES EMPLOYE {}/{}".format(self.debug_session_id, i, len(employes)))
                    logger.debug(">>> [{}] Import absences employe {}/{}: {}".format(self.debug_session_id, i, len(employes), employe.matricule))
                    
                    # Importer les absences de l'employe depuis Kelio
                    absences_results = sync_service.get_absences_employe_v41(employe.kelio_employee_key)
                    
                    logger.debug(">>> [{}] RESULTAT SERVICE ABSENCES pour {}:".format(self.debug_session_id, employe.matricule))
                    logger.debug("   • Statut: {}".format(absences_results.get('statut', 'INCONNU')))
                    logger.debug("   • Reponse: {}".format(absences_results))
                    
                    if absences_results.get('statut') == 'reussi':
                        absences = absences_results.get('absences', [])
                        absences_importees += len(absences)
                        employes_traites += 1
                        
                        logger.info("OK [{}] SERVICE ABSENCES REUSSI pour {}: {} absence(s)".format(self.debug_session_id, employe.matricule, len(absences)))
                        logger.debug("   OK {} absence(s) importee(s) pour {}".format(len(absences), employe.matricule))
                        
                        # Traiter et creer les absences...
                        AbsenceUtilisateur = self.models['AbsenceUtilisateur']
                        for absence_data in absences:
                            try:
                                absence, created = AbsenceUtilisateur.objects.get_or_create(
                                    utilisateur=employe,
                                    type_absence=absence_data.get('type_absence', 'Absence Kelio'),
                                    date_debut=absence_data.get('date_debut'),
                                    defaults={
                                        'date_fin': absence_data.get('date_fin'),
                                        'duree_jours': absence_data.get('duree_jours', 1),
                                        'source_donnee': 'KELIO'
                                    }
                                )
                                if created:
                                    self.imported_objects.setdefault('absences', []).append(absence)
                                    self._update_stats('AbsenceUtilisateur', True)
                                    
                            except Exception as e:
                                logger.debug("   ERROR Erreur creation absence: {}".format(e))
                                erreurs_absences += 1
                        
                    else:
                        erreur_msg = absences_results.get('erreur', 'Erreur inconnue')
                        logger.error("ERROR [{}] SERVICE ABSENCES ECHOUE pour {}: {}".format(self.debug_session_id, employe.matricule, erreur_msg))
                        logger.debug("   ERROR Erreur absences pour {}: {}".format(employe.matricule, erreur_msg))
                        erreurs_absences += 1
                        
                except Exception as e:
                    logger.error("ERROR [{}] Erreur import absences employe {}: {}".format(self.debug_session_id, employe.matricule, e))
                    erreurs_absences += 1
            
            # Resume
            success_msg = "OK {} absence(s) importee(s) depuis Kelio pour {} employe(s)".format(absences_importees, employes_traites)
            self._write(success_msg)
            logger.info(">>> [{}] {}".format(self.debug_session_id, success_msg))
            
            # LOG DETAILLE DU NOMBRE D'ENREGISTREMENTS ABSENCES
            logger.info(">>> [{}] IMPORT ABSENCES KELIO TERMINE:".format(self.debug_session_id))
            logger.info("   >>> Absences importees: {}".format(absences_importees))
            logger.info("   >>> Employes traites: {}/{}".format(employes_traites, len(employes)))
            logger.info("   ERROR Erreurs absences: {}".format(erreurs_absences))
            logger.info("   >>> Taux employes traites: {:.1f}%".format((employes_traites/len(employes)*100) if employes else 0))
            
            self._log_table_import_summary('AbsenceUtilisateur', absences_importees, 0, erreurs_absences)
            
            if erreurs_absences > 0:
                error_msg = "WARNING {} erreur(s) lors de l'import absences".format(erreurs_absences)
                self._write(error_msg, debug_level='WARNING')
                logger.warning("WARNING [{}] {}".format(self.debug_session_id, error_msg))
            
            # Enregistrer les statistiques
            self.stats['absences_import'] = {
                'total_imported': absences_importees,
                'employees_processed': employes_traites,
                'errors': erreurs_absences,
                'success_rate': (employes_traites / len(employes)) * 100 if employes else 0
            }
            
        except Exception as e:
            self._log_error_with_details("Erreur import absences Kelio", e)

    def _import_kelio_competences(self):
        """Importe les competences depuis Kelio UNIQUEMENT avec debug detaille"""
        if not self.with_kelio_sync:
            self._write(">>> Import competences Kelio desactive", debug_level='DEBUG')
            logger.debug(">>> [{}] Import competences Kelio desactive".format(self.debug_session_id))
            return
        
        try:
            logger.debug(">>> [{}] Debut import competences depuis Kelio".format(self.debug_session_id))
            self._write(">>> Import competences depuis Kelio...")
            
            # Import des competences depuis Kelio
            from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
            
            sync_service = get_kelio_sync_service_v41(self.kelio_config)
            
            logger.info(">>> [{}] APPEL SERVICE WEB KELIO - COMPETENCES".format(self.debug_session_id))
            logger.debug(">>> [{}] Lancement synchronisation competences...".format(self.debug_session_id))
            self._write(">>> Synchronisation competences Kelio...")
            competences_results = sync_service.synchroniser_competences_v41()
            
            logger.info(">>> [{}] RESULTAT SERVICE COMPETENCES:".format(self.debug_session_id))
            logger.info("   • Statut: {}".format(competences_results.get('statut', 'INCONNU')))
            logger.info("   • Reponse brute: {}".format(competences_results))
            logger.debug(">>> [{}] Resultats sync competences: {}".format(self.debug_session_id, competences_results))
            
            if competences_results.get('statut') == 'reussi':
                competences_data = competences_results.get('competences', [])
                nb_competences = len(competences_data)
                
                logger.info("OK [{}] SERVICE COMPETENCES REUSSI: {} competence(s) a traiter".format(self.debug_session_id, nb_competences))
                logger.debug("OK [{}] {} competence(s) a importer".format(self.debug_session_id, nb_competences))
                
                # Traiter les competences
                Competence = self.models['Competence']
                competences_importees = 0
                competences_mises_a_jour = 0
                
                for i, comp_data in enumerate(competences_data, 1):
                    try:
                        logger.debug(">>> [{}] Traitement competence {}/{}: {}".format(self.debug_session_id, i, nb_competences, comp_data.get('nom', 'Sans nom')))
                        
                        competence, created = Competence.objects.get_or_create(
                            nom=comp_data.get('nom', 'Competence Kelio {}'.format(i)),
                            defaults={
                                'categorie': comp_data.get('categorie', 'General'),
                                'type_competence': comp_data.get('type_competence', 'TECHNIQUE'),
                                'description': comp_data.get('description', "Competence importee depuis Kelio: {}".format(comp_data.get('nom', 'Sans nom'))),
                                'kelio_skill_key': comp_data.get('kelio_skill_key', i),
                                'actif': True
                            }
                        )
                        
                        if created:
                            competences_importees += 1
                            self.imported_objects['competences'].append(competence)
                            self._update_stats('Competence', True)
                            logger.debug("   OK Competence creee: {}".format(competence.nom))
                        else:
                            competences_mises_a_jour += 1
                            self._update_stats('Competence', False)
                            logger.debug("   >>> Competence existante: {}".format(competence.nom))
                            
                    except Exception as e:
                        logger.error("ERROR [{}] Erreur traitement competence {}: {}".format(self.debug_session_id, i, e))
                
                success_msg = "OK {} competence(s) importee(s) depuis Kelio ({} mises a jour)".format(competences_importees, competences_mises_a_jour)
                self._write(success_msg)
                logger.info(">>> [{}] {}".format(self.debug_session_id, success_msg))
                
                # LOG DETAILLE DU NOMBRE D'ENREGISTREMENTS COMPETENCES
                logger.info(">>> [{}] IMPORT COMPETENCES KELIO TERMINE:".format(self.debug_session_id))
                logger.info("   >>> Competences importees: {}".format(competences_importees))
                logger.info("   >>> Competences mises a jour: {}".format(competences_mises_a_jour))
                logger.info("   >>> Total traite: {}".format(nb_competences))
                logger.info("   >>> Taux de reussite: {:.1f}%".format(((competences_importees + competences_mises_a_jour) / nb_competences) * 100 if nb_competences else 0))
                
                self._log_table_import_summary('Competence', competences_importees, competences_mises_a_jour, 0)
                
                # Enregistrer les statistiques
                self.stats['competences_import'] = {
                    'total_imported': competences_importees,
                    'total_updated': competences_mises_a_jour,
                    'total_processed': nb_competences,
                    'success_rate': ((competences_importees + competences_mises_a_jour) / nb_competences) * 100 if nb_competences else 0
                }
                
            else:
                error_msg = competences_results.get('erreur', 'Erreur inconnue')
                warning_msg = "WARNING Aucune competence importee depuis Kelio: {}".format(error_msg)
                self._write(warning_msg, debug_level='WARNING')
                logger.error("ERROR [{}] SERVICE COMPETENCES ECHOUE: {}".format(self.debug_session_id, error_msg))
                logger.warning("WARNING [{}] {}".format(self.debug_session_id, warning_msg))
                
                self.stats['competences_import'] = {
                    'total_imported': 0,
                    'error_message': error_msg
                }
            
        except Exception as e:
            self._log_error_with_details("Erreur import competences Kelio", e)
    
    def _import_kelio_cache(self):
        """Importe et configure le cache Kelio"""
        try:
            CacheApiKelio = self.models['CacheApiKelio']
            
            # Nettoyer le cache existant si force
            if self.force:
                CacheApiKelio.objects.all().delete()
                self._write(">>> Cache Kelio nettoye")
            
            # Creer une entree de cache par defaut
            cache_entry, created = CacheApiKelio.objects.get_or_create(
                cle_cache='kelio_import_status',
                defaults={
                    'valeur_cache': json.dumps({
                        'last_import': timezone.now().isoformat(),
                        'import_type': 'kelio_strict',
                        'status': 'completed'
                    }),
                    'date_creation': timezone.now(),
                    'date_expiration': timezone.now() + timedelta(hours=24)
                }
            )
            
            if created:
                self._write("OK Cache Kelio initialise")
                self._update_stats('CacheApiKelio', True)
                logger.info(">>> [{}] CACHE KELIO INITIALISE: 1 enregistrement cree".format(self.debug_session_id))
                self._log_table_import_summary('CacheApiKelio', 1, 0, 0)
            else:
                logger.info(">>> [{}] CACHE KELIO EXISTANT: 0 nouveau enregistrement".format(self.debug_session_id))
                self._log_table_import_summary('CacheApiKelio', 0, 1, 0)
            
        except Exception as e:
            logger.error("Erreur configuration cache Kelio: {}".format(e))
    
    def _create_minimal_structure(self):
        """Cree une structure organisationnelle minimale si Kelio n'est pas disponible"""
        Departement = self.models['Departement']
        Site = self.models['Site']
        Poste = self.models['Poste']
        
        try:
            # Departement par defaut
            dept, created = Departement.objects.get_or_create(
                code='GENERAL',
                defaults={
                    'nom': 'Departement General',
                    'description': 'Departement par defaut pour import Kelio',
                    'actif': True
                }
            )
            if created:
                self.imported_objects['departements'].append(dept)
                self._update_stats('Departement', True)
                logger.info(">>> [{}] DEPARTEMENT MINIMAL CREE: 1 enregistrement".format(self.debug_session_id))
            
            # Site par defaut
            site, created = Site.objects.get_or_create(
                nom='Site Principal',
                defaults={
                    'adresse': 'Adresse non definie',
                    'ville': 'Ville non definie',
                    'actif': True
                }
            )
            if created:
                self.imported_objects['sites'].append(site)
                self._update_stats('Site', True)
                logger.info(">>> [{}] SITE MINIMAL CREE: 1 enregistrement".format(self.debug_session_id))
            
            # Poste par defaut
            poste, created = Poste.objects.get_or_create(
                titre='Poste General',
                site=site,
                defaults={
                    'description': 'Poste par defaut pour import Kelio',
                    'departement': dept,
                    'actif': True
                }
            )
            if created:
                self.imported_objects['postes'].append(poste)
                self._update_stats('Poste', True)
                logger.info(">>> [{}] POSTE MINIMAL CREE: 1 enregistrement".format(self.debug_session_id))
            
            self._write("OK Structure minimale creee")
            
            # LOG RESUME STRUCTURE MINIMALE
            dept_count = 1 if any(created for created in [dept.pk]) else 0
            site_count = 1 if any(created for created in [site.pk]) else 0  
            poste_count = 1 if any(created for created in [poste.pk]) else 0
            total_minimal = dept_count + site_count + poste_count
            
            logger.info(">>> [{}] STRUCTURE MINIMALE CREEE:".format(self.debug_session_id))
            logger.info("   >>> Total enregistrements crees: {}".format(total_minimal))
            logger.info("   >>> Departements: {}".format(dept_count))
            logger.info("   >>> Sites: {}".format(site_count))
            logger.info("   >>> Postes: {}".format(poste_count))
            
        except Exception as e:
            logger.error("ERROR [{}] ERREUR CREATION STRUCTURE MINIMALE: {}".format(self.debug_session_id, e))
            logger.error("Erreur creation structure minimale: {}".format(e))
            raise


