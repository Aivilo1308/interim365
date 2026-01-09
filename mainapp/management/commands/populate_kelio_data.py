#!/usr/bin/env python
"""
Commande Django Management pour remplir les tables avec les données Kelio
Version hiérarchique avec structure managériale complète et debug détaillé

URL DE BASE KELIO SAFESECUR: https://keliodemo-safesecur.kelio.io/open

NOUVELLES FONCTIONNALITÉS:
  ✓ Structure hiérarchique complète avec managers assignés
  ✓ Employés à chaque niveau (CHEF_EQUIPE/RESPONSABLE/DIRECTEUR/RH/ADMIN)
  ✓ Messages de debug détaillés pour connexion Kelio et services web
  ✓ Comptage précis des enregistrements créés par table
  ✓ Import Kelio + complémentation pour atteindre 100 employés
  ✓ Workflow d'intérim avec propositions humaines complètes
  ✓ Configuration scoring et notifications intelligentes

HIÉRARCHIE IMPLEMENTÉE:
  ADMIN (1) → DIRECTEUR (3-4) → RESPONSABLE (8-10) → CHEF_EQUIPE (12-15) → UTILISATEUR (20-25)
  Total: 50 employés avec relations managériales complètes

Usage:
    python manage.py populate_kelio_data --mode=full --verbose
    python manage.py populate_kelio_data --mode=test --debug
    python manage.py populate_kelio_data --with-kelio-sync --force --verbose
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from datetime import datetime, date, timedelta
import logging
from typing import Dict, List, Optional, Any, Tuple
import random
import uuid
import json
import sys
from django.core.cache import cache
from mainapp.models import ConfigurationApiKelio
import logging

logger = logging.getLogger(__name__)

# ================================================================
# CONFIGURATION KELIO SAFESECUR
# ================================================================

class KelioConfigService:
    """Service pour gérer la configuration Kelio de façon sécurisée"""
    
    CACHE_KEY = 'kelio_active_config'
    CACHE_TIMEOUT = 3600  # 1 heure
    
    @classmethod
    def get_active_config(cls):
        """Récupère la configuration active avec cache"""
        # Vérifier d'abord le cache
        cached_config = cache.get(cls.CACHE_KEY)
        if cached_config:
            return cached_config
        
        # Récupérer depuis la base de données
        config = ConfigurationApiKelio.objects.filter(actif=True).first()
        
        if config:
            # Mettre en cache
            cache.set(cls.CACHE_KEY, config, cls.CACHE_TIMEOUT)
        
        return config
    
    @classmethod
    def get_credentials(cls):
        """Récupère les identifiants de façon sécurisée"""
        config = cls.get_active_config()
        
        if not config:
            logger.warning("Aucune configuration Kelio active trouvée, utilisation des valeurs par défaut")
            return {
                'base_url': '',
                'username': '',
                'password': ''
            }
        
        # Récupérer le mot de passe décrypté de façon sécurisée
        password = config.get_password()
        
        if not password:
            logger.error("Impossible de récupérer le mot de passe décrypté")
            raise ValueError("Mot de passe Kelio non disponible")
        
        return {
            'base_url': config.url_base,
            'username': config.username,
            'password': password,
            'config': config  # Optionnel : l'objet complet
        }
    
    @classmethod
    def clear_cache(cls):
        """Vide le cache de configuration"""
        cache.delete(cls.CACHE_KEY)
        logger.info("Cache de configuration Kelio vidé")


credentials = KelioConfigService.get_credentials()

KELIO_SAFESECUR_BASE_URL = credentials['base_url']
KELIO_SAFESECUR_SERVICES_URL = f'{KELIO_SAFESECUR_BASE_URL}/services'

KELIO_SAFESECUR_DEFAULT_AUTH = {
    'username': credentials['username'],
    'password': credentials['password']
}

# Configuration debug avancé
DEBUG_LEVELS = {
    'MINIMAL': 1,
    'STANDARD': 2,
    'VERBOSE': 3,
    'ULTRA_VERBOSE': 4
}

# ================================================================
# CONFIGURATION HIÉRARCHIQUE - 100 EMPLOYÉS
# ================================================================

HIERARCHY_CONFIG = {
    'ADMIN': {
        'count': 3,
        'level': 0,
        'reports_to': None,
        'description': 'Administrateur système'
    },
    'RH': {
        'count': 3,
        'level': 0,
        'reports_to': None,
        'description': 'Ressources Humaines'
    },
    'DIRECTEUR': {
        'count': 8,
        'level': 1,
        'reports_to': ['RH', 'ADMIN'],  # Les directeurs rapportent aux RH ou ADMIN (même niveau)
        'description': 'Directeur métier'
    },
    'RESPONSABLE': {
        'count': 18,
        'level': 2,
        'reports_to': 'DIRECTEUR',
        'description': 'Responsable d\'équipe'
    },
    'CHEF_EQUIPE': {
        'count': 26,
        'level': 3,
        'reports_to': 'RESPONSABLE',
        'description': 'Chef d\'équipe opérationnel'
    },
    'UTILISATEUR': {
        'count': 42,
        'level': 4,
        'reports_to': 'CHEF_EQUIPE',
        'description': 'Utilisateur standard'
    }
}

# Vérification: total = 3 + 3 + 8 + 18 + 26 + 42 = 100 employés

# ================================================================
# SETUP LOGGING AVANCÉ
# ================================================================

class DebugLogger:
    """Logger avancé avec niveaux de debug et compteurs"""
    
    def __init__(self, debug_level=2, stdout=None, style=None):
        self.debug_level = debug_level
        self.stdout = stdout
        self.style = style
        self.counters = {}
        self.start_time = timezone.now()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG if debug_level >= 3 else logging.INFO)
        
    def debug(self, message, level=2):
        """Log debug avec niveau"""
        if self.debug_level >= level:
            self._write(f"[DEBUG L{level}] {message}", level)
            
    def info(self, message):
        """Log info standard"""
        self._write(f"[INFO] {message}", 1)
        
    def success(self, message):
        """Log succès"""
        self._write(f"  {message}", 1, self.style.SUCCESS if self.style else None)
        
    def warning(self, message):
        """Log warning"""
        self._write(f"  {message}", 1, self.style.WARNING if self.style else None)
        
    def error(self, message):
        """Log error"""
        self._write(f"  {message}", 1, self.style.ERROR if self.style else None)
        
    def kelio_debug(self, service_name, message, level=3):
        """Debug spécifique Kelio"""
        if self.debug_level >= level:
            self._write(f"[KELIO-{service_name}] {message}", level)
            
    def count(self, category, increment=1):
        """Incrémente un compteur"""
        if category not in self.counters:
            self.counters[category] = 0
        self.counters[category] += increment
        
    def get_count(self, category):
        """Récupère un compteur"""
        return self.counters.get(category, 0)
        
    def reset_count(self, category):
        """Remet un compteur à zéro"""
        self.counters[category] = 0
        
    def log_counters(self):
        """Affiche tous les compteurs"""
        if not self.counters:
            return
            
        self.info("  COMPTEURS DE MIGRATION:")
        total_created = 0
        for category, count in sorted(self.counters.items()):
            if 'created' in category.lower():
                total_created += count
            self.info(f"   {category}: {count}")
        self.info(f"   TOTAL CRÉÉ: {total_created}")
        
    def log_timing(self):
        """Affiche le timing"""
        duration = (timezone.now() - self.start_time).total_seconds()
        self.info(f"⏱️ Durée totale: {duration:.2f} secondes")
        
    def _write(self, message, level=1, style_func=None):
        """Helper pour écrire des messages"""
        if self.stdout and level <= 2:  # Messages importants sur stdout
            if style_func:
                self.stdout.write(style_func(message))
            else:
                self.stdout.write(message)
        
        # Toujours logger
        if level == 1:
            self.logger.info(message)
        else:
            self.logger.debug(message)


class Command(BaseCommand):
    """
    Commande Django pour la migration hiérarchique des données Kelio SafeSecur
    """
    help = 'Remplit les tables Django avec structure hiérarchique complète depuis Kelio SafeSecur'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=['full', 'structure_only', 'employees_only', 'interim_data', 'test'],
            default='full',
            help='Mode de migration'
        )
        parser.add_argument(
            '--debug',
            action='store_true',
            help='Mode debug ultra-verbose (niveau 4)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Mode verbose (niveau 3)'
        )
        parser.add_argument(
            '--with-kelio-sync',
            action='store_true',
            help='Forcer la synchronisation avec Kelio SafeSecur'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forcer la recréation même si les données existent'
        )
        parser.add_argument(
            '--target-employees',
            type=int,
            default=100,
            help='Nombre total d\'employés souhaités (défaut: 100)'
        )
        parser.add_argument(
            '--default-password',
            type=str,
            default='Test2025@',
            help='Mot de passe par défaut'
        )
        parser.add_argument(
            '--no-test-connection',
            action='store_true',
            help='Ne pas tester la connexion Kelio'
        )
    
    def handle(self, *args, **options):
        """Point d'entrée principal"""
        try:
            # Configuration debug
            debug_level = 4 if options['debug'] else (3 if options['verbose'] else 2)
            
            # Initialisation du logger
            logger = DebugLogger(
                debug_level=debug_level,
                stdout=self.stdout,
                style=self.style
            )
            
            logger.info("  MIGRATION KELIO SAFESECUR AVEC HIÉRARCHIE COMPLÈTE")
            logger.info("=" * 80)
            logger.info(f"Mode: {options['mode']}")
            logger.info(f"Debug niveau: {debug_level}")
            logger.info(f"Sync Kelio: {'Oui' if options['with_kelio_sync'] else 'Non'}")
            logger.info(f"Force: {'Oui' if options['force'] else 'Non'}")
            logger.info(f"Employés cible: {options['target_employees']}")
            logger.info(f"URL Kelio: {KELIO_SAFESECUR_SERVICES_URL}")
            logger.info("=" * 80)
            
            # Lancement de la migration
            migration = KelioHierarchicalMigration(
                logger=logger,
                force=options['force'],
                target_employees=options['target_employees'],
                default_password=options['default_password'],
                with_kelio_sync=options['with_kelio_sync']
            )
            
            success = migration.run_migration(
                mode=options['mode'],
                test_connection=not options['no_test_connection']
            )
            
            if success:
                logger.success('Migration terminée avec succès')
            else:
                raise CommandError('Migration échouée')
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erreur: {str(e)}'))
            raise CommandError(f'Erreur lors de la migration: {str(e)}')


# ================================================================
# CLASSE PRINCIPALE DE MIGRATION HIÉRARCHIQUE
# ================================================================

class KelioHierarchicalMigration:
    """
    Gestionnaire principal pour la migration hiérarchique des données Kelio SafeSecur
    """
    
    def __init__(self, logger, force=False, target_employees=100, 
                 default_password='Test2025@', with_kelio_sync=False):
        
        # Import des modèles
        from mainapp.models import (
            ConfigurationApiKelio, CacheApiKelio, ConfigurationScoring,
            ProfilUtilisateur, Departement, Site, Poste,
            Competence, MotifAbsence, CompetenceUtilisateur, FormationUtilisateur,
            AbsenceUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended,
            DemandeInterim, DisponibiliteUtilisateur, PropositionCandidat,
            ScoreDetailCandidat, ValidationDemande, NotificationInterim,
            HistoriqueAction, ReponseCandidatInterim, WorkflowEtape, WorkflowDemande
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
            'DemandeInterim': DemandeInterim,
            'DisponibiliteUtilisateur': DisponibiliteUtilisateur,
            'PropositionCandidat': PropositionCandidat,
            'ScoreDetailCandidat': ScoreDetailCandidat,
            'ValidationDemande': ValidationDemande,
            'NotificationInterim': NotificationInterim,
            'HistoriqueAction': HistoriqueAction,
            'ReponseCandidatInterim': ReponseCandidatInterim,
            'WorkflowEtape': WorkflowEtape,
            'WorkflowDemande': WorkflowDemande,
        }
        
        self.logger = logger
        self.force = force
        self.target_employees = target_employees
        self.default_password = default_password
        self.with_kelio_sync = with_kelio_sync
        
        # Configuration Kelio
        self.kelio_config = None
        
        # Stockage hiérarchique des objets créés
        self.hierarchy_data = {
            'employees_by_level': {},
            'managers_assigned': {},
            'organizational_structure': {},
            'departments': [],
            'sites': [],
            'postes': [],
            'competences': [],
            'motifs_absence': []
        }
        
    def run_migration(self, mode='full', test_connection=True):
        """Lance la migration complète avec structure hiérarchique"""
        self.logger.info(f"  Début migration mode: {mode}")
        
        try:
            # Étape 1: Configuration système
            self._setup_system_configuration()
            
            # Étape 2: Test connexion Kelio (optionnel)
            if test_connection and mode != 'test':
                self._test_kelio_connection()
            
            # Étape 3: Structure organisationnelle
            self._create_organizational_structure()
            
            # Étape 4: Migration selon le mode
            if mode == 'full':
                self._migrate_full_hierarchical()
            elif mode == 'structure_only':
                self._migrate_structure_only()
            elif mode == 'employees_only':
                self._migrate_employees_hierarchical()
            elif mode == 'interim_data':
                self._migrate_interim_data()
            elif mode == 'test':
                self._migrate_test_data_hierarchical()
            else:
                raise ValueError(f"Mode non supporté: {mode}")
            
            # Étape 5: Statistiques finales
            self._log_final_statistics()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Erreur migration: {e}")
            raise
    
    def _setup_system_configuration(self):
        """Configure le système Kelio et scoring"""
        self.logger.info("  Configuration système...")
        
        # Configuration Kelio SafeSecur
        self._setup_kelio_configuration()
        
        # Configuration scoring
        self._setup_scoring_configuration()
        
        # Configuration workflow
        self._setup_workflow_configuration()
        
        self.logger.success("Configuration système terminée")
    
    def _setup_kelio_configuration(self):
        """Configure la connexion Kelio SafeSecur"""
        ConfigurationApiKelio = self.models['ConfigurationApiKelio']
        
        self.logger.debug("Configuration Kelio SafeSecur...", 3)
        
        config_data = {
            'url_base': KELIO_SAFESECUR_SERVICES_URL,
            'username': KELIO_SAFESECUR_DEFAULT_AUTH['username'],
            'password': KELIO_SAFESECUR_DEFAULT_AUTH['password'],
            'timeout_seconds': 30,
            'service_employees': True,
            'service_absences': True,
            'service_formations': True,
            'service_competences': True,
            'cache_duree_defaut_minutes': 60,
            'cache_taille_max_mo': 100,
            'auto_invalidation_cache': True,
            'actif': True
        }
        
        self.kelio_config, created = ConfigurationApiKelio.objects.get_or_create(
            nom='Configuration Kelio SafeSecur Hiérarchique',
            defaults=config_data
        )
        
        if created:
            self.logger.count('configurations_kelio_created')
            self.logger.success(f"Configuration Kelio créée: {self.kelio_config.nom}")
        else:
            # Mise à jour si nécessaire
            if self.force:
                for key, value in config_data.items():
                    setattr(self.kelio_config, key, value)
                self.kelio_config.save()
                self.logger.count('configurations_kelio_updated')
                self.logger.info("Configuration Kelio mise à jour")
        
        self.logger.debug(f"URL configurée: {self.kelio_config.url_base}", 4)
        self.logger.debug(f"Timeout: {self.kelio_config.timeout_seconds}s", 4)
    
    def _setup_scoring_configuration(self):
        """Configure le scoring avec bonus hiérarchiques"""
        ConfigurationScoring = self.models['ConfigurationScoring']
        
        self.logger.debug("Configuration scoring hiérarchique...", 3)
        
        config_hierarchique = {
            'nom': 'Scoring Hiérarchique SafeSecur',
            'description': 'Configuration avec bonus hiérarchiques adaptés',
            'poids_similarite_poste': 0.25,
            'poids_competences': 0.25,
            'poids_experience': 0.20,
            'poids_disponibilite': 0.15,
            'poids_proximite': 0.10,
            'poids_anciennete': 0.05,
            # Bonus hiérarchiques différenciés
            'bonus_proposition_humaine': 5,
            'bonus_experience_similaire': 8,
            'bonus_recommandation': 10,
            'bonus_manager_direct': 12,
            'bonus_chef_equipe': 8,
            'bonus_responsable': 15,
            'bonus_directeur': 18,
            'bonus_rh': 20,
            'bonus_admin': 22,
            'bonus_superuser': 0,
            'penalite_indisponibilite_partielle': 15,
            'penalite_indisponibilite_totale': 50,
            'penalite_distance_excessive': 10,
            'configuration_par_defaut': True,
            'actif': True
        }
        
        config, created = ConfigurationScoring.objects.get_or_create(
            nom=config_hierarchique['nom'],
            defaults=config_hierarchique
        )
        
        if created:
            self.logger.count('configurations_scoring_created')
            self.logger.success("Configuration scoring hiérarchique créée")
        
        self.logger.debug("Bonus hiérarchiques configurés:", 4)
        self.logger.debug(f"  CHEF_EQUIPE: +{config_hierarchique['bonus_chef_equipe']}", 4)
        self.logger.debug(f"  RESPONSABLE: +{config_hierarchique['bonus_responsable']}", 4)
        self.logger.debug(f"  DIRECTEUR: +{config_hierarchique['bonus_directeur']}", 4)
        self.logger.debug(f"  RH: +{config_hierarchique['bonus_rh']}", 4)
        self.logger.debug(f"  ADMIN: +{config_hierarchique['bonus_admin']}", 4)
    
    def _setup_workflow_configuration(self):
        """Configure les étapes du workflow"""
        WorkflowEtape = self.models['WorkflowEtape']
        
        self.logger.debug("Configuration workflow hiérarchique...", 3)
        
        etapes_workflow = [
            {
                'nom': 'Création demande',
                'type_etape': 'DEMANDE',
                'ordre': 1,
                'obligatoire': True,
                'permet_propositions_humaines': False,
                'actif': True
            },
            {
                'nom': 'Propositions candidats',
                'type_etape': 'PROPOSITION_CANDIDATS',
                'ordre': 2,
                'obligatoire': True,
                'delai_max_heures': 48,
                'permet_propositions_humaines': True,
                'actif': True
            },
            {
                'nom': 'Validation Responsable',
                'type_etape': 'VALIDATION_RESPONSABLE',
                'ordre': 3,
                'obligatoire': True,
                'delai_max_heures': 24,
                'permet_propositions_humaines': True,
                'actif': True
            },
            {
                'nom': 'Validation Directeur',
                'type_etape': 'VALIDATION_DIRECTEUR',
                'ordre': 4,
                'obligatoire': True,
                'delai_max_heures': 24,
                'permet_propositions_humaines': True,
                'actif': True
            },
            {
                'nom': 'Validation RH/Admin',
                'type_etape': 'VALIDATION_RH_ADMIN',
                'ordre': 5,
                'obligatoire': True,
                'delai_max_heures': 12,
                'permet_propositions_humaines': False,
                'actif': True
            }
        ]
        
        created_count = 0
        for etape_data in etapes_workflow:
            etape, created = WorkflowEtape.objects.get_or_create(
                type_etape=etape_data['type_etape'],
                defaults=etape_data
            )
            if created:
                created_count += 1
        
        if created_count > 0:
            self.logger.count('workflow_etapes_created', created_count)
            self.logger.success(f"{created_count} étapes workflow créées")
    
    def _test_kelio_connection(self):
        """Test la connexion Kelio avec debug détaillé"""
        self.logger.info("  Test connexion Kelio SafeSecur...")
        
        try:
            # Test de base de l'URL
            self.logger.kelio_debug("CONNECTION", f"Test URL: {KELIO_SAFESECUR_SERVICES_URL}")
            
            # Tentative d'import du service
            try:
                from mainapp.services.kelio_api_simplifie import get_kelio_sync_service_v41
                self.logger.kelio_debug("IMPORT", "Service Kelio importé avec succès")
                
                # Test de connexion
                sync_service = get_kelio_sync_service_v41(self.kelio_config)
                self.logger.kelio_debug("SERVICE", "Service Kelio instancié")
                
                # Test complet
                results = sync_service.test_connexion_complete_v41()
                self.logger.kelio_debug("TEST", f"Résultats test: {results}")
                
                if results.get('global_status', False):
                    self.logger.success("Connexion Kelio SafeSecur réussie")
                    
                    # Test des services individuels
                    services_status = results.get('services_status', {})
                    for service_name, service_info in services_status.items():
                        status = service_info.get('status', 'UNKNOWN')
                        if status == 'OK':
                            self.logger.kelio_debug("SERVICE", f"  {service_name}: OK")
                        else:
                            self.logger.kelio_debug("SERVICE", f"  {service_name}: {status}")
                
                else:
                    self.logger.warning("Certains services Kelio ne sont pas disponibles")
                    self.logger.warning("Migration en mode dégradé avec données de test")
                    
            except ImportError as e:
                self.logger.kelio_debug("IMPORT", f"Import service échoué: {e}")
                self.logger.warning("Service Kelio non disponible - mode test")
                
        except Exception as e:
            self.logger.kelio_debug("ERROR", f"Erreur test connexion: {e}")
            self.logger.warning("Test connexion échoué - mode dégradé")
    
    def _create_organizational_structure(self):
        """Crée la structure organisationnelle de base"""
        self.logger.info("  Création structure organisationnelle...")
        
        # Départements
        self._create_departments()
        
        # Sites
        self._create_sites()
        
        # Postes
        self._create_postes()
        
        # Motifs d'absence
        self._create_motifs_absence()
        
        # Compétences
        self._create_competences()
        
        self.logger.success("Structure organisationnelle créée")
    
    def _create_departments(self):
        """Crée les départements avec debug"""
        Departement = self.models['Departement']
        
        self.logger.debug("Création départements...", 3)
        
        departements_data = [
            {'nom': 'Direction Générale', 'code': 'DG', 'description': 'Direction générale'},
            {'nom': 'Ressources Humaines', 'code': 'RH', 'description': 'Gestion RH'},
            {'nom': 'Sécurité Opérationnelle', 'code': 'SEC', 'description': 'Sécurité terrain'},
            {'nom': 'Surveillance', 'code': 'SURV', 'description': 'Surveillance vidéo'},
            {'nom': 'Administration', 'code': 'ADMIN', 'description': 'Administration'},
            {'nom': 'Formation', 'code': 'FORM', 'description': 'Formation et développement'}
        ]
        
        created_count = 0
        for data in departements_data:
            dept, created = Departement.objects.get_or_create(
                code=data['code'],
                defaults={**data, 'actif': True}
            )
            if created:
                created_count += 1
                self.hierarchy_data['departments'].append(dept)
                self.logger.debug(f"Département créé: {dept.nom}", 4)
        
        self.logger.count('departements_created', created_count)
        self.logger.success(f"{created_count} départements créés")
    
    def _create_sites(self):
        """Crée les sites avec debug"""
        Site = self.models['Site']
        
        self.logger.debug("Création sites...", 3)
        
        sites_data = [
            {
                'nom': 'Site Central Abidjan',
                'adresse': 'Boulevard de la République',
                'ville': 'Abidjan',
                'code_postal': '01000'
            },
            {
                'nom': 'Antenne Bouaké',
                'adresse': 'Avenue de la Paix',
                'ville': 'Bouaké',
                'code_postal': '01000'
            },
            {
                'nom': 'Bureau Yamoussoukro',
                'adresse': 'Boulevard Félix Houphouët-Boigny',
                'ville': 'Yamoussoukro',
                'code_postal': '01000'
            }
        ]
        
        created_count = 0
        for data in sites_data:
            site, created = Site.objects.get_or_create(
                nom=data['nom'],
                defaults={**data, 'actif': True}
            )
            if created:
                created_count += 1
                self.hierarchy_data['sites'].append(site)
                self.logger.debug(f"Site créé: {site.nom}", 4)
        
        self.logger.count('sites_created', created_count)
        self.logger.success(f"{created_count} sites créés")
    
    def _create_postes(self):
        """Crée les postes avec debug"""
        Poste = self.models['Poste']
        
        if not self.hierarchy_data['departments'] or not self.hierarchy_data['sites']:
            self.logger.warning("Départements ou sites manquants pour créer les postes")
            return
        
        self.logger.debug("Création postes...", 3)
        
        # Postes hiérarchiques pour 100 employés
        postes_hierarchiques = [
            # Direction (niveau 3)
            {'titre': 'Directeur Général', 'niveau': 3, 'dept_idx': 0},
            {'titre': 'Directeur Général Adjoint', 'niveau': 3, 'dept_idx': 0},
            {'titre': 'Directeur Sécurité', 'niveau': 3, 'dept_idx': 2},
            {'titre': 'Directeur Sécurité Adjoint', 'niveau': 3, 'dept_idx': 2},
            {'titre': 'Directeur RH', 'niveau': 3, 'dept_idx': 1},
            {'titre': 'Directeur Opérations', 'niveau': 3, 'dept_idx': 2},
            {'titre': 'Directeur Formation', 'niveau': 3, 'dept_idx': 5},
            {'titre': 'Directeur Administratif', 'niveau': 3, 'dept_idx': 4},
            {'titre': 'Directeur Surveillance', 'niveau': 3, 'dept_idx': 3},
            {'titre': 'Directeur Développement', 'niveau': 3, 'dept_idx': 0},
            
            # Responsables (niveau 2)
            {'titre': 'Responsable Sécurité Abidjan', 'niveau': 2, 'dept_idx': 2},
            {'titre': 'Responsable Sécurité Bouaké', 'niveau': 2, 'dept_idx': 2},
            {'titre': 'Responsable Sécurité Yamoussoukro', 'niveau': 2, 'dept_idx': 2},
            {'titre': 'Responsable Surveillance Centrale', 'niveau': 2, 'dept_idx': 3},
            {'titre': 'Responsable Surveillance Mobile', 'niveau': 2, 'dept_idx': 3},
            {'titre': 'Responsable Formation Technique', 'niveau': 2, 'dept_idx': 5},
            {'titre': 'Responsable Formation Continue', 'niveau': 2, 'dept_idx': 5},
            {'titre': 'Responsable Administration Générale', 'niveau': 2, 'dept_idx': 4},
            {'titre': 'Responsable Administration Terrain', 'niveau': 2, 'dept_idx': 4},
            {'titre': 'Responsable RH Recrutement', 'niveau': 2, 'dept_idx': 1},
            {'titre': 'Responsable RH Formation', 'niveau': 2, 'dept_idx': 1},
            {'titre': 'Responsable RH Paie', 'niveau': 2, 'dept_idx': 1},
            {'titre': 'Responsable Qualité Sécurité', 'niveau': 2, 'dept_idx': 2},
            {'titre': 'Responsable Maintenance', 'niveau': 2, 'dept_idx': 4},
            {'titre': 'Responsable Logistique', 'niveau': 2, 'dept_idx': 4},
            {'titre': 'Responsable Communication', 'niveau': 2, 'dept_idx': 0},
            
            # Chefs d'équipe (niveau 1)
            {'titre': 'Chef Équipe Sécurité Jour', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Chef Équipe Sécurité Nuit', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Chef Équipe Sécurité Weekend', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Chef Équipe Surveillance PC', 'niveau': 1, 'dept_idx': 3},
            {'titre': 'Chef Équipe Surveillance Mobile', 'niveau': 1, 'dept_idx': 3},
            {'titre': 'Chef Équipe Intervention', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Superviseur Formation Pratique', 'niveau': 1, 'dept_idx': 5},
            {'titre': 'Superviseur Formation Théorique', 'niveau': 1, 'dept_idx': 5},
            {'titre': 'Chef Équipe Administrative', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Chef Équipe Maintenance', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Chef Équipe Contrôle Qualité', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Chef Équipe Patrouille', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Chef Équipe Accueil', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Superviseur RH Terrain', 'niveau': 1, 'dept_idx': 1},
            {'titre': 'Chef Équipe Logistique', 'niveau': 1, 'dept_idx': 4},
            
            # Postes opérationnels (niveau 1)
            {'titre': 'Agent de Sécurité Senior', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Agent de Sécurité', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Agent de Sécurité Mobile', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Opérateur Surveillance Principal', 'niveau': 1, 'dept_idx': 3},
            {'titre': 'Opérateur Surveillance', 'niveau': 1, 'dept_idx': 3},
            {'titre': 'Agent Contrôle Accès', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Agent Patrouille', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Agent Intervention', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Formateur Sécurité Senior', 'niveau': 1, 'dept_idx': 5},
            {'titre': 'Formateur Sécurité', 'niveau': 1, 'dept_idx': 5},
            {'titre': 'Formateur Surveillance', 'niveau': 1, 'dept_idx': 5},
            {'titre': 'Assistant Administratif Senior', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Assistant Administratif', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Gestionnaire RH Senior', 'niveau': 1, 'dept_idx': 1},
            {'titre': 'Gestionnaire RH', 'niveau': 1, 'dept_idx': 1},
            {'titre': 'Technicien Maintenance', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Agent Accueil Sécurisé', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Contrôleur Qualité', 'niveau': 1, 'dept_idx': 2},
            {'titre': 'Agent Logistique', 'niveau': 1, 'dept_idx': 4},
            {'titre': 'Coordinateur Terrain', 'niveau': 1, 'dept_idx': 2}
        ]
        
        created_count = 0
        for poste_data in postes_hierarchiques:
            try:
                dept = self.hierarchy_data['departments'][poste_data['dept_idx']]
                site = random.choice(self.hierarchy_data['sites'])
                
                poste, created = Poste.objects.get_or_create(
                    titre=poste_data['titre'],
                    site=site,
                    defaults={
                        'description': f"Poste: {poste_data['titre']}",
                        'departement': dept,
                        'niveau_responsabilite': poste_data['niveau'],
                        'interim_autorise': True,
                        'actif': True
                    }
                )
                
                if created:
                    created_count += 1
                    self.hierarchy_data['postes'].append(poste)
                    self.logger.debug(f"Poste créé: {poste.titre} (Niveau {poste_data['niveau']})", 4)
                    
            except Exception as e:
                self.logger.error(f"Erreur création poste: {e}")
        
        self.logger.count('postes_created', created_count)
        self.logger.success(f"{created_count} postes créés")
    
    def _create_motifs_absence(self):
        """Crée les motifs d'absence"""
        MotifAbsence = self.models['MotifAbsence']
        
        self.logger.debug("Création motifs d'absence...", 3)
        
        motifs_data = [
            {'nom': 'Congé Payé', 'code': 'CP', 'categorie': 'CONGE', 'couleur': '#28a745'},
            {'nom': 'Formation', 'code': 'FORM', 'categorie': 'FORMATION', 'couleur': '#17a2b8'},
            {'nom': 'Mission Externe', 'code': 'MISS', 'categorie': 'PROFESSIONNEL', 'couleur': '#ffc107'},
            {'nom': 'Arrêt Maladie', 'code': 'AM', 'categorie': 'MALADIE', 'couleur': '#dc3545'},
            {'nom': 'RTT', 'code': 'RTT', 'categorie': 'CONGE', 'couleur': '#6c757d'}
        ]
        
        created_count = 0
        for data in motifs_data:
            motif, created = MotifAbsence.objects.get_or_create(
                code=data['code'],
                defaults={**data, 'actif': True}
            )
            if created:
                created_count += 1
                self.hierarchy_data['motifs_absence'].append(motif)
        
        self.logger.count('motifs_absence_created', created_count)
        self.logger.success(f"{created_count} motifs d'absence créés")
    
    def _create_competences(self):
        """Crée les compétences"""
        Competence = self.models['Competence']
        
        self.logger.debug("Création compétences...", 3)
        
        competences_data = [
            {'nom': 'Surveillance Vidéo', 'categorie': 'Technique', 'type_competence': 'TECHNIQUE'},
            {'nom': 'Contrôle Accès', 'categorie': 'Sécurité', 'type_competence': 'TECHNIQUE'},
            {'nom': 'Intervention Sécurité', 'categorie': 'Opérationnelle', 'type_competence': 'TECHNIQUE'},
            {'nom': 'Management Équipe', 'categorie': 'Management', 'type_competence': 'TRANSVERSE'},
            {'nom': 'Formation Sécurité', 'categorie': 'Pédagogie', 'type_competence': 'TRANSVERSE'},
            {'nom': 'Communication', 'categorie': 'Relationnel', 'type_competence': 'COMPORTEMENTALE'},
            {'nom': 'Gestion Administrative', 'categorie': 'Administration', 'type_competence': 'TRANSVERSE'}
        ]
        
        created_count = 0
        for data in competences_data:
            competence, created = Competence.objects.get_or_create(
                nom=data['nom'],
                defaults={**data, 'actif': True}
            )
            if created:
                created_count += 1
                self.hierarchy_data['competences'].append(competence)
        
        self.logger.count('competences_created', created_count)
        self.logger.success(f"{created_count} compétences créées")
    
    # ================================================================
    # MIGRATION HIÉRARCHIQUE DES EMPLOYÉS
    # ================================================================
    
    def _migrate_full_hierarchical(self):
        """Migration complète avec hiérarchie"""
        self.logger.info("  Migration complète hiérarchique...")
        
        steps = [
            ("Employés hiérarchiques", self._migrate_employees_hierarchical),
            ("Données connexes", self._create_employee_related_data),
            ("Demandes intérim", self._create_test_interim_requests),
            ("Workflow complet", self._create_workflow_test_data)
        ]
        
        for step_name, step_function in steps:
            self.logger.info(f"  {step_name}...")
            try:
                step_function()
                self.logger.success(f"  {step_name} terminé")
            except Exception as e:
                self.logger.error(f"  Erreur {step_name}: {e}")
    
    def _migrate_employees_hierarchical(self):
        """Migration des employés avec structure hiérarchique complète"""
        self.logger.info("  Migration employés hiérarchiques...")
        
        # Étape 1: Synchronisation Kelio (si activée)
        kelio_employees = []
        if self.with_kelio_sync:
            kelio_employees = self._sync_kelio_employees()
        
        # Étape 2: Analyse et planification hiérarchique
        needed_by_level = self._plan_hierarchical_structure(len(kelio_employees))
        
        # Étape 3: Création des employés hiérarchiques
        self._create_hierarchical_employees(needed_by_level, kelio_employees)
        
        # Étape 4: Attribution des managers
        self._assign_managers()
        
        # Étape 5: Validation de la hiérarchie
        self._validate_hierarchy()
        
        self.logger.success("Migration employés hiérarchiques terminée")
    
    def _sync_kelio_employees(self):
        """Synchronise les employés depuis Kelio avec debug détaillé"""
        self.logger.info("  Synchronisation employés Kelio...")
        
        try:
            from mainapp.services.kelio_api_simplifie import synchroniser_tous_employes_kelio_v41
            
            self.logger.kelio_debug("SYNC", "Lancement synchronisation employés")
            
            # Synchronisation complète
            results = synchroniser_tous_employes_kelio_v41(mode='complet')
            
            self.logger.kelio_debug("SYNC", f"Résultats: {results}")
            
            if results.get('statut_global') == 'reussi':
                nb_employees = results.get('resume', {}).get('employees_reussis', 0)
                self.logger.kelio_debug("SYNC", f"Employés synchronisés: {nb_employees}")
                self.logger.success(f"Synchronisation Kelio réussie: {nb_employees} employés")
                
                # Récupération des employés Kelio
                ProfilUtilisateur = self.models['ProfilUtilisateur']
                kelio_employees = list(ProfilUtilisateur.objects.filter(
                    kelio_sync_status='REUSSI'
                ).order_by('-kelio_last_sync')[:nb_employees])
                
                self.logger.count('employees_kelio_synced', len(kelio_employees))
                return kelio_employees
                
            else:
                error_msg = results.get('erreur_critique', 'Erreur inconnue')
                self.logger.kelio_debug("SYNC", f"Échec synchronisation: {error_msg}")
                self.logger.warning(f"Synchronisation Kelio échouée: {error_msg}")
                return []
                
        except Exception as e:
            self.logger.kelio_debug("SYNC", f"Exception: {e}")
            self.logger.error(f"Erreur synchronisation Kelio: {e}")
            return []
    
    def _plan_hierarchical_structure(self, kelio_count):
        """Planifie la structure hiérarchique en fonction des employés Kelio"""
        self.logger.debug(f"Planification hiérarchique (Kelio: {kelio_count})", 3)
        
        # Calcul des besoins par niveau
        needed_by_level = {}
        total_planned = 0
        
        for level_name, config in HIERARCHY_CONFIG.items():
            count = config['count']
            needed_by_level[level_name] = count
            total_planned += count
            
            self.logger.debug(f"  {level_name}: {count} employés", 4)
        
        self.logger.debug(f"Total planifié: {total_planned}", 3)
        self.logger.debug(f"Employés Kelio disponibles: {kelio_count}", 3)
        
        # Si on a plus d'employés Kelio que prévu, on ajuste
        if kelio_count > total_planned:
            # Répartir l'excédent dans UTILISATEUR
            excess = kelio_count - total_planned
            needed_by_level['UTILISATEUR'] += excess
            self.logger.debug(f"Excédent Kelio réparti dans UTILISATEUR: +{excess}", 3)
        
        # Si on a moins d'employés Kelio, on complétera avec des fictifs
        elif kelio_count < total_planned:
            deficit = total_planned - kelio_count
            self.logger.debug(f"Déficit à combler avec employés fictifs: {deficit}", 3)
        
        return needed_by_level
    
    def _create_hierarchical_employees(self, needed_by_level, kelio_employees):
        """Crée les employés selon la structure hiérarchique"""
        self.logger.info("  Création employés hiérarchiques...")
        
        # Répartir les employés Kelio par niveau (aléatoirement pour commencer)
        remaining_kelio = kelio_employees.copy()
        created_by_level = {}
        
        # Création/attribution par niveau hiérarchique
        for level_name in ['ADMIN', 'DIRECTEUR', 'RH', 'RESPONSABLE', 'CHEF_EQUIPE', 'UTILISATEUR']:
            config = HIERARCHY_CONFIG[level_name]
            needed_count = needed_by_level[level_name]
            
            self.logger.debug(f"Traitement niveau {level_name}: {needed_count} employés", 3)
            
            level_employees = []
            
            # Utiliser d'abord les employés Kelio disponibles
            kelio_for_level = min(len(remaining_kelio), needed_count)
            for i in range(kelio_for_level):
                employee = remaining_kelio.pop(0)
                # Mise à jour du type_profil
                employee.type_profil = level_name
                employee.save()
                level_employees.append(employee)
                self.logger.debug(f"  Employé Kelio assigné: {employee.nom_complet} -> {level_name}", 4)
            
            # Compléter avec des employés fictifs si nécessaire
            fictifs_needed = needed_count - kelio_for_level
            if fictifs_needed > 0:
                fictifs = self._create_fictitious_employees(level_name, fictifs_needed)
                level_employees.extend(fictifs)
                self.logger.debug(f"  {len(fictifs)} employés fictifs créés pour {level_name}", 4)
            
            created_by_level[level_name] = level_employees
            self.hierarchy_data['employees_by_level'][level_name] = level_employees
            
            self.logger.count(f'employees_{level_name.lower()}_created', len(level_employees))
            self.logger.success(f"Niveau {level_name}: {len(level_employees)} employés")
        
        # Log du résumé
        total_created = sum(len(employees) for employees in created_by_level.values())
        self.logger.success(f"Total employés créés/assignés: {total_created}")
    
    def _create_fictitious_employees(self, level_name, count):
        """Crée des employés fictifs pour un niveau hiérarchique"""
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        ProfilUtilisateurExtended = self.models['ProfilUtilisateurExtended']
        
        self.logger.debug(f"Création de {count} employés fictifs {level_name}", 3)
        
        # Noms africains étendus pour 100 employés
        prenoms = [
            # Noms ivoiriens
            'Kofi', 'Kwame', 'Yaw', 'Akwasi', 'Kwaku', 'Fiifi', 'Kwabena', 'Kojo',
            'Ama', 'Akosua', 'Yaa', 'Adwoa', 'Afia', 'Efua', 'Aba', 'Akua',
            # Noms ouest-africains
            'Mamadou', 'Ibrahim', 'Ousmane', 'Abdoulaye', 'Amadou', 'Sekou', 'Moussa', 'Omar',
            'Fatou', 'Aminata', 'Mariama', 'Fatoumata', 'Awa', 'Kadiatou', 'Aissatou', 'Binta',
            # Noms français/chrétiens
            'Jean', 'Marie', 'Pierre', 'Paul', 'François', 'Emmanuel', 'Michel', 'André',
            'Adjoua', 'Akissi', 'Amenan', 'Bintou', 'Clarisse', 'Daniella', 'Eugénie', 'Fabienne',
            # Noms traditionnels supplémentaires
            'Konan', 'Koffi', 'Kouadio', 'Kouakou', 'Yves', 'Serge', 'Marcel', 'Roger',
            'Mariam', 'Hawa', 'Salimata', 'Oumou', 'Nana', 'Assetou', 'Ramata', 'Djénéba'
        ]
        
        noms = [
            # Noms ivoiriens courants
            'Kouassi', 'Kouame', 'Kone', 'Yao', 'N\'Guessan', 'Ouattara', 'Koffi', 'Konan',
            'Diabate', 'Toure', 'Bamba', 'Diarrassouba', 'Coulibaly', 'Silue', 'Dao', 'Fofana',
            'Traore', 'Sanogo', 'Doumbia', 'Kante', 'Camara', 'Diallo', 'Keita', 'Dembele',
            'Barry', 'Sow', 'Bah', 'Conde', 'Sylla', 'Diakite', 'Koita', 'Bagayoko',
            # Noms du sud et centre
            'Assouan', 'Beugre', 'Gbagbo', 'Gnamien', 'Lake', 'Ahoua', 'Ahizi', 'Akaffou',
            'Anoh', 'Adjoumani', 'Bakayoko', 'Boli', 'Dago', 'Gnabeli', 'Guehi', 'Kacou'
        ]
        
        employees = []
        
        for i in range(count):
            try:
                with transaction.atomic():
                    prenom = random.choice(prenoms)
                    nom = random.choice(noms)
                    matricule = f'{level_name[:3]}{2025}{i+1:03d}'
                    username = f'{level_name.lower()}_{matricule.lower()}'
                    email = f'{prenom.lower()}.{nom.lower()}@safesecur.ci'
                    
                    # Vérifier unicité
                    if User.objects.filter(username=username).exists():
                        if not self.force:
                            continue
                        else:
                            User.objects.filter(username=username).delete()
                    
                    # Créer utilisateur Django
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        first_name=prenom,
                        last_name=nom,
                        password=self.default_password
                    )
                    
                    # Assigner département et site intelligemment
                    if level_name in ['ADMIN', 'DIRECTEUR']:
                        dept = self.hierarchy_data['departments'][0]  # Direction
                    elif level_name == 'RH':
                        dept = next((d for d in self.hierarchy_data['departments'] if d.code == 'RH'), 
                                  self.hierarchy_data['departments'][1])
                    else:
                        dept = random.choice(self.hierarchy_data['departments'][2:])  # Opérationnels
                    
                    site = random.choice(self.hierarchy_data['sites'])
                    poste = None
                    if self.hierarchy_data['postes']:
                        # Sélectionner un poste adapté au niveau
                        niveau_mapping = {'ADMIN': 3, 'DIRECTEUR': 3, 'RH': 2, 
                                        'RESPONSABLE': 2, 'CHEF_EQUIPE': 1, 'UTILISATEUR': 1}
                        niveau_souhaite = niveau_mapping.get(level_name, 1)
                        postes_adaptes = [p for p in self.hierarchy_data['postes'] 
                                        if p.niveau_responsabilite == niveau_souhaite]
                        if postes_adaptes:
                            poste = random.choice(postes_adaptes)
                    
                    # Créer profil utilisateur
                    profil = ProfilUtilisateur.objects.create(
                        user=user,
                        matricule=matricule,
                        type_profil=level_name,
                        statut_employe='ACTIF',
                        departement=dept,
                        site=site,
                        poste=poste,
                        date_embauche=date.today() - timedelta(days=random.randint(30, 1095)),
                        actif=True
                    )
                    
                    # Données étendues
                    ProfilUtilisateurExtended.objects.create(
                        profil=profil,
                        telephone=f'+225 {random.randint(10000000, 99999999)}',
                        date_embauche=profil.date_embauche,
                        type_contrat='CDI',
                        temps_travail=1.0,
                        disponible_interim=level_name not in ['ADMIN', 'DIRECTEUR'],
                        rayon_deplacement_km=random.randint(20, 100)
                    )
                    
                    employees.append(profil)
                    self.logger.debug(f"    Employé fictif créé: {profil.nom_complet} ({level_name})", 4)
                    
            except Exception as e:
                self.logger.error(f"Erreur création employé fictif {level_name}: {e}")
        
        self.logger.count('employees_fictitious_created', len(employees))
        return employees
    
    def _assign_managers(self):
        """Assigne les managers selon la hiérarchie corrigée"""
        self.logger.info("  Attribution des managers...")
        
        assignments_count = 0
        
        # Attribution par niveau (de haut en bas)
        # ADMIN et RH sont au niveau 0 (pas de manager)
        # DIRECTEUR au niveau 1 rapporte à ADMIN ou RH
        for level_name in ['DIRECTEUR', 'RESPONSABLE', 'CHEF_EQUIPE', 'UTILISATEUR']:
            config = HIERARCHY_CONFIG[level_name]
            reports_to = config.get('reports_to')
            
            if not reports_to:
                continue
            
            employees = self.hierarchy_data['employees_by_level'].get(level_name, [])
            
            # Gestion spéciale pour DIRECTEUR qui peut rapporter à RH ou ADMIN (même niveau)
            if level_name == 'DIRECTEUR' and isinstance(reports_to, list):
                # Combiner ADMIN et RH comme managers potentiels des directeurs
                potential_managers = []
                for manager_type in reports_to:
                    potential_managers.extend(self.hierarchy_data['employees_by_level'].get(manager_type, []))
                
                if not potential_managers:
                    self.logger.warning(f"Aucun manager ADMIN/RH disponible pour DIRECTEUR")
                    continue
                
                self.logger.debug(f"Attribution managers ADMIN/RH pour {len(employees)} DIRECTEUR", 3)
                self.logger.debug(f"Managers disponibles: {len(potential_managers)} (ADMIN + RH)", 4)
                
                # Répartir les directeurs entre ADMIN et RH
                for i, employee in enumerate(employees):
                    manager = potential_managers[i % len(potential_managers)]
                    employee.manager = manager
                    employee.save()
                    
                    self.hierarchy_data['managers_assigned'][employee.id] = manager.id
                    assignments_count += 1
                    
                    self.logger.debug(f"  DIRECTEUR {employee.nom_complet} -> Manager: {manager.nom_complet} ({manager.type_profil})", 4)
            
            else:
                # Attribution normale pour les autres niveaux
                potential_managers = self.hierarchy_data['employees_by_level'].get(reports_to, [])
                
                if not potential_managers:
                    self.logger.warning(f"Aucun manager {reports_to} disponible pour {level_name}")
                    continue
                
                self.logger.debug(f"Attribution managers {reports_to} pour {len(employees)} {level_name}", 3)
                
                # Répartir équitablement
                for i, employee in enumerate(employees):
                    manager = potential_managers[i % len(potential_managers)]
                    employee.manager = manager
                    employee.save()
                    
                    self.hierarchy_data['managers_assigned'][employee.id] = manager.id
                    assignments_count += 1
                    
                    self.logger.debug(f"  {employee.nom_complet} -> Manager: {manager.nom_complet}", 4)
        
        self.logger.count('manager_assignments', assignments_count)
        self.logger.success(f"{assignments_count} relations managériales créées")
    
    def _validate_hierarchy(self):
        """Valide la structure hiérarchique créée"""
        self.logger.info("  Validation hiérarchie...")
        
        validation_results = {
            'total_employees': 0,
            'employees_with_manager': 0,
            'managers_count': 0,
            'levels_populated': {},
            'hierarchy_depth': 0
        }
        
        # Compter par niveau
        for level_name, employees in self.hierarchy_data['employees_by_level'].items():
            count = len(employees)
            validation_results['levels_populated'][level_name] = count
            validation_results['total_employees'] += count
            
            # Compter ceux qui ont un manager
            with_manager = sum(1 for emp in employees if emp.manager)
            validation_results['employees_with_manager'] += with_manager
            
            self.logger.debug(f"Niveau {level_name}: {count} employés, {with_manager} avec manager", 3)
        
        # Compter les managers uniques
        managers = set()
        for level_employees in self.hierarchy_data['employees_by_level'].values():
            for emp in level_employees:
                if emp.manager:
                    managers.add(emp.manager.id)
        validation_results['managers_count'] = len(managers)
        
        # Calculer la profondeur hiérarchique
        max_depth = 0
        for emp in self.hierarchy_data['employees_by_level'].get('UTILISATEUR', []):
            depth = self._calculate_hierarchy_depth(emp)
            max_depth = max(max_depth, depth)
        validation_results['hierarchy_depth'] = max_depth
        
        # Log des résultats de validation
        self.logger.success("Validation hiérarchie terminée:")
        self.logger.info(f"  Total employés: {validation_results['total_employees']}")
        self.logger.info(f"  Avec manager: {validation_results['employees_with_manager']}")
        self.logger.info(f"  Managers uniques: {validation_results['managers_count']}")
        self.logger.info(f"  Profondeur max: {validation_results['hierarchy_depth']}")
        
        # Détail par niveau
        for level, count in validation_results['levels_populated'].items():
            expected = HIERARCHY_CONFIG[level]['count']
            status = " " if count >= expected else " "
            self.logger.info(f"  {level}: {count}/{expected} {status}")
    
    def _calculate_hierarchy_depth(self, employee, visited=None):
        """Calcule la profondeur hiérarchique d'un employé"""
        if visited is None:
            visited = set()
        
        if employee.id in visited:  # Éviter les boucles
            return 0
        
        visited.add(employee.id)
        
        if not employee.manager:
            return 0
        
        return 1 + self._calculate_hierarchy_depth(employee.manager, visited)
    
    # ================================================================
    # DONNÉES CONNEXES
    # ================================================================
    
    def _create_employee_related_data(self):
        """Crée les données connexes des employés"""
        self.logger.info("  Création données connexes employés...")
        
        all_employees = []
        for level_employees in self.hierarchy_data['employees_by_level'].values():
            all_employees.extend(level_employees)
        
        # Compétences
        self._assign_competences(all_employees)
        
        # Formations
        self._create_formations(all_employees)
        
        # Absences
        self._create_absences(all_employees)
        
        # Disponibilités
        self._create_disponibilites(all_employees)
        
        self.logger.success("Données connexes créées")
    
    def _assign_competences(self, employees):
        """Assigne des compétences aux employés"""
        CompetenceUtilisateur = self.models['CompetenceUtilisateur']
        
        self.logger.debug("Attribution compétences...", 3)
        
        if not self.hierarchy_data['competences']:
            return
        
        created_count = 0
        for employee in employees[:50]:  # Limiter à 50 pour éviter trop de données
            try:
                # Nombre de compétences selon le niveau
                if employee.type_profil in ['ADMIN', 'DIRECTEUR']:
                    nb_competences = random.randint(4, 6)
                elif employee.type_profil in ['RESPONSABLE', 'RH']:
                    nb_competences = random.randint(3, 5)
                else:
                    nb_competences = random.randint(2, 4)
                
                competences_choisies = random.sample(
                    self.hierarchy_data['competences'],
                    min(nb_competences, len(self.hierarchy_data['competences']))
                )
                
                for competence in competences_choisies:
                    CompetenceUtilisateur.objects.create(
                        utilisateur=employee,
                        competence=competence,
                        niveau_maitrise=random.randint(2, 4),
                        source_donnee='LOCAL',
                        date_evaluation=date.today() - timedelta(days=random.randint(0, 365))
                    )
                    created_count += 1
                    
            except Exception as e:
                self.logger.error(f"Erreur attribution compétences: {e}")
        
        self.logger.count('competences_utilisateur_created', created_count)
        self.logger.success(f"{created_count} compétences utilisateur créées")
    
    def _create_formations(self, employees):
        """Crée des formations pour les employés"""
        FormationUtilisateur = self.models['FormationUtilisateur']
        
        self.logger.debug("Création formations...", 3)
        
        formations_types = [
            'Formation Sécurité de Base',
            'Formation Surveillance Avancée',
            'Formation Management d\'Équipe',
            'Formation Premiers Secours',
            'Formation Réglementation Sécurité',
            'Formation Contrôle d\'Accès',
            'Formation Intervention d\'Urgence',
            'Formation Communication',
            'Formation Technologie Sécurité',
            'Formation Leadership'
        ]
        
        created_count = 0
        for employee in employees[:40]:  # 40 employés avec formations
            try:
                # Plus de formations pour les niveaux élevés
                if employee.type_profil in ['ADMIN', 'DIRECTEUR']:
                    nb_formations = random.randint(2, 4)
                elif employee.type_profil in ['RESPONSABLE', 'RH']:
                    nb_formations = random.randint(1, 3)
                else:
                    nb_formations = random.randint(1, 2)
                
                for _ in range(nb_formations):
                    FormationUtilisateur.objects.create(
                        utilisateur=employee,
                        titre=random.choice(formations_types),
                        organisme="Centre de Formation SafeSecur",
                        date_debut=date.today() - timedelta(days=random.randint(30, 365)),
                        duree_jours=random.randint(1, 5),
                        source_donnee='LOCAL',
                        certifiante=True,
                        diplome_obtenu=True
                    )
                    created_count += 1
                    
            except Exception as e:
                self.logger.error(f"Erreur création formation: {e}")
        
        self.logger.count('formations_created', created_count)
        self.logger.success(f"{created_count} formations créées")
    
    def _create_absences(self, employees):
        """Crée des absences pour les employés"""
        AbsenceUtilisateur = self.models['AbsenceUtilisateur']
        
        self.logger.debug("Création absences...", 3)
        
        types_absence = ['Congé Payé', 'Formation', 'RTT', 'Mission Externe', 'Congé Maladie']
        
        created_count = 0
        for employee in employees[:60]:  # 60 employés avec absences
            try:
                # Nombre d'absences selon l'ancienneté simulée
                nb_absences = random.randint(1, 3)
                
                for _ in range(nb_absences):
                    date_debut = date.today() - timedelta(days=random.randint(0, 180))
                    duree = random.randint(1, 10)
                    
                    AbsenceUtilisateur.objects.create(
                        utilisateur=employee,
                        type_absence=random.choice(types_absence),
                        date_debut=date_debut,
                        date_fin=date_debut + timedelta(days=duree),
                        duree_jours=duree,
                        source_donnee='LOCAL',
                        commentaire=f"Absence {random.choice(types_absence).lower()}"
                    )
                    created_count += 1
                    
            except Exception as e:
                self.logger.error(f"Erreur création absence: {e}")
        
        self.logger.count('absences_created', created_count)
        self.logger.success(f"{created_count} absences créées")
    
    def _create_disponibilites(self, employees):
        """Crée des disponibilités pour les employés"""
        DisponibiliteUtilisateur = self.models['DisponibiliteUtilisateur']
        
        self.logger.debug("Création disponibilités...", 3)
        
        created_count = 0
        for employee in employees:
            try:
                date_debut = date.today() + timedelta(days=random.randint(1, 30))
                DisponibiliteUtilisateur.objects.create(
                    utilisateur=employee,
                    type_disponibilite=random.choice(['DISPONIBLE', 'INDISPONIBLE']),
                    date_debut=date_debut,
                    date_fin=date_debut + timedelta(days=random.randint(1, 14)),
                    commentaire="Disponibilité test",
                    created_by=employee
                )
                created_count += 1
                
            except Exception as e:
                self.logger.error(f"Erreur création disponibilité: {e}")
        
        self.logger.count('disponibilites_created', created_count)
        self.logger.success(f"{created_count} disponibilités créées")
    
    # ================================================================
    # DONNÉES DE TEST WORKFLOW
    # ================================================================
    
    def _create_test_interim_requests(self):
        """Crée des demandes d'intérim de test"""
        DemandeInterim = self.models['DemandeInterim']
        
        self.logger.debug("Création demandes d'intérim test...", 3)
        
        if not (self.hierarchy_data['postes'] and self.hierarchy_data['motifs_absence']):
            self.logger.warning("Postes ou motifs d'absence manquants")
            return
        
        all_employees = []
        for level_employees in self.hierarchy_data['employees_by_level'].values():
            all_employees.extend(level_employees)
        
        if len(all_employees) < 5:
            self.logger.warning("Pas assez d'employés pour créer des demandes")
            return
        
        created_count = 0
        for i in range(15):  # 15 demandes de test pour 100 employés
            try:
                demandeur = random.choice(all_employees)
                personne_remplacee = random.choice([emp for emp in all_employees if emp != demandeur])
                poste = random.choice(self.hierarchy_data['postes'])
                motif = random.choice(self.hierarchy_data['motifs_absence'])
                
                date_debut = date.today() + timedelta(days=random.randint(1, 30))
                date_fin = date_debut + timedelta(days=random.randint(5, 20))
                
                demande = DemandeInterim.objects.create(
                    demandeur=demandeur,
                    personne_remplacee=personne_remplacee,
                    poste=poste,
                    date_debut=date_debut,
                    date_fin=date_fin,
                    motif_absence=motif,
                    urgence=random.choice(['NORMALE', 'MOYENNE', 'ELEVEE']),
                    description_poste=f"Remplacement de {personne_remplacee.nom_complet} au poste {poste.titre}",
                    instructions_particulieres="Instructions spécifiques pour la mission",
                    competences_indispensables="Compétences sécurité requises",
                    statut=random.choice(['SOUMISE', 'EN_VALIDATION', 'VALIDEE']),
                    propositions_autorisees=True,
                    nb_max_propositions_par_utilisateur=3,
                    niveau_validation_actuel=random.randint(0, 2),
                    niveaux_validation_requis=3
                )
                
                created_count += 1
                self.logger.debug(f"  Demande créée: {demande.numero_demande}", 4)
                
            except Exception as e:
                self.logger.error(f"Erreur création demande intérim: {e}")
        
        self.logger.count('demandes_interim_created', created_count)
        self.logger.success(f"{created_count} demandes d'intérim créées")
    
    def _create_workflow_test_data(self):
        """Crée des données de workflow de test"""
        self.logger.debug("Création données workflow test...", 3)
        
        # Propositions de candidats
        self._create_test_propositions()
        
        # Validations
        self._create_test_validations()
        
        # Notifications
        self._create_test_notifications()
        
        self.logger.success("Données workflow créées")
    
    def _create_test_propositions(self):
        """Crée des propositions de candidats test"""
        PropositionCandidat = self.models['PropositionCandidat']
        DemandeInterim = self.models['DemandeInterim']
        
        self.logger.debug("Création propositions candidats...", 3)
        
        demandes = list(DemandeInterim.objects.all()[:5])  # Quelques demandes
        if not demandes:
            return
        
        # Employés proposants (managers seulement)
        proposants = []
        for level in ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH']:
            proposants.extend(self.hierarchy_data['employees_by_level'].get(level, []))
        
        # Candidats potentiels (tous niveaux)
        candidats = []
        for level_employees in self.hierarchy_data['employees_by_level'].values():
            candidats.extend(level_employees)
        
        if not proposants or not candidats:
            return
        
        created_count = 0
        for demande in demandes:
            # 2-4 propositions par demande
            nb_propositions = random.randint(2, 4)
            candidats_choisis = random.sample(candidats, min(nb_propositions, len(candidats)))
            
            for candidat in candidats_choisis:
                try:
                    proposant = random.choice(proposants)
                    
                    # Source selon le type de profil
                    source_mapping = {
                        'CHEF_EQUIPE': 'CHEF_EQUIPE',
                        'RESPONSABLE': 'RESPONSABLE',
                        'DIRECTEUR': 'DIRECTEUR',
                        'RH': 'RH'
                    }
                    source = source_mapping.get(proposant.type_profil, 'AUTRE')
                    
                    # Bonus selon le niveau hiérarchique
                    bonus_mapping = {
                        'CHEF_EQUIPE': 8,
                        'RESPONSABLE': 15,
                        'DIRECTEUR': 18,
                        'RH': 20
                    }
                    bonus = bonus_mapping.get(proposant.type_profil, 5)
                    
                    proposition = PropositionCandidat.objects.create(
                        demande_interim=demande,
                        candidat_propose=candidat,
                        proposant=proposant,
                        source_proposition=source,
                        justification=f"Je recommande {candidat.nom_complet} pour ses compétences en sécurité et sa disponibilité",
                        competences_specifiques="Surveillance, contrôle d'accès",
                        experience_pertinente=f"{random.randint(1, 5)} ans d'expérience",
                        statut=random.choice(['SOUMISE', 'EVALUEE', 'RETENUE']),
                        bonus_proposition_humaine=bonus,
                        niveau_validation_propose=random.randint(1, 3)
                    )
                    
                    created_count += 1
                    self.logger.debug(f"  Proposition: {candidat.nom_complet} par {proposant.nom_complet} ({source})", 4)
                    
                except Exception as e:
                    self.logger.error(f"Erreur création proposition: {e}")
        
        self.logger.count('propositions_created', created_count)
        self.logger.success(f"{created_count} propositions créées")
    
    def _create_test_validations(self):
        """Crée des validations test"""
        ValidationDemande = self.models['ValidationDemande']
        DemandeInterim = self.models['DemandeInterim']
        
        self.logger.debug("Création validations test...", 3)
        
        demandes = list(DemandeInterim.objects.all()[:3])  # Quelques demandes
        if not demandes:
            return
        
        # Validateurs par niveau
        validateurs = {
            'RESPONSABLE': self.hierarchy_data['employees_by_level'].get('RESPONSABLE', []),
            'DIRECTEUR': self.hierarchy_data['employees_by_level'].get('DIRECTEUR', []),
            'RH': self.hierarchy_data['employees_by_level'].get('RH', [])
        }
        
        created_count = 0
        for demande in demandes:
            # Créer quelques validations
            for type_validation in ['RESPONSABLE', 'DIRECTEUR']:
                validateurs_niveau = validateurs.get(type_validation, [])
                if not validateurs_niveau:
                    continue
                
                try:
                    validateur = random.choice(validateurs_niveau)
                    
                    validation = ValidationDemande.objects.create(
                        demande=demande,
                        type_validation=type_validation,
                        niveau_validation=1 if type_validation == 'RESPONSABLE' else 2,
                        validateur=validateur,
                        decision=random.choice(['APPROUVE', 'APPROUVE_AVEC_MODIF']),
                        commentaire=f"Validation {type_validation} par {validateur.nom_complet}",
                        date_validation=timezone.now() - timedelta(hours=random.randint(1, 72)),
                        candidats_retenus=[],
                        candidats_rejetes=[]
                    )
                    
                    created_count += 1
                    self.logger.debug(f"  Validation {type_validation} par {validateur.nom_complet}", 4)
                    
                except Exception as e:
                    self.logger.error(f"Erreur création validation: {e}")
        
        self.logger.count('validations_created', created_count)
        self.logger.success(f"{created_count} validations créées")
    
    def _create_test_notifications(self):
        """Crée des notifications test"""
        NotificationInterim = self.models['NotificationInterim']
        DemandeInterim = self.models['DemandeInterim']
        
        self.logger.debug("Création notifications test...", 3)
        
        demandes = list(DemandeInterim.objects.all()[:3])
        if not demandes:
            return
        
        all_employees = []
        for level_employees in self.hierarchy_data['employees_by_level'].values():
            all_employees.extend(level_employees)
        
        if not all_employees:
            return
        
        created_count = 0
        for demande in demandes:
            # Créer quelques notifications par demande
            types_notif = ['NOUVELLE_DEMANDE', 'DEMANDE_A_VALIDER', 'PROPOSITION_CANDIDAT']
            
            for type_notif in types_notif[:2]:  # 2 notifications par demande
                try:
                    destinataire = random.choice(all_employees)
                    expediteur = random.choice(all_employees)
                    
                    notification = NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=expediteur,
                        demande=demande,
                        type_notification=type_notif,
                        urgence=random.choice(['NORMALE', 'HAUTE']),
                        statut=random.choice(['NON_LUE', 'LUE']),
                        titre=f"Notification {type_notif.replace('_', ' ').title()}",
                        message=f"Notification test pour la demande {demande.numero_demande}",
                        url_action_principale="#",
                        texte_action_principale="Voir détails",
                        metadata={
                            'type': 'test_notification',
                            'demande_id': demande.id,
                            'urgence': demande.urgence
                        }
                    )
                    
                    created_count += 1
                    self.logger.debug(f"  Notification {type_notif} pour {destinataire.nom_complet}", 4)
                    
                except Exception as e:
                    self.logger.error(f"Erreur création notification: {e}")
        
        self.logger.count('notifications_created', created_count)
        self.logger.success(f"{created_count} notifications créées")
    
    # ================================================================
    # MODES DE MIGRATION ALTERNATIFS
    # ================================================================
    
    def _migrate_structure_only(self):
        """Migration structure seulement"""
        self.logger.info("  Migration structure seulement")
        # Structure déjà créée dans _create_organizational_structure
        self.logger.success("Structure terminée")
    
    def _migrate_interim_data(self):
        """Migration données intérim seulement"""
        self.logger.info("  Migration données intérim...")
        
        # Besoin d'employés minimaux
        if not any(self.hierarchy_data['employees_by_level'].values()):
            self._create_minimal_employees()
        
        self._create_test_interim_requests()
        self._create_workflow_test_data()
        
        self.logger.success("Données intérim créées")
    
    def _migrate_test_data_hierarchical(self):
        """Migration test avec données hiérarchiques complètes"""
        self.logger.info("🧪 Migration test hiérarchique complète...")
        
        # Toutes les étapes
        self._migrate_employees_hierarchical()
        self._create_employee_related_data()
        self._create_test_interim_requests()
        self._create_workflow_test_data()
        
        self.logger.success("Migration test hiérarchique terminée")
    
    def _create_minimal_employees(self):
        """Crée un nombre minimal d'employés pour les tests"""
        self.logger.debug("Création employés minimaux...", 3)
        
        minimal_structure = {
            'ADMIN': 2,
            'RH': 2,
            'DIRECTEUR': 2, 
            'RESPONSABLE': 4,
            'CHEF_EQUIPE': 6,
            'UTILISATEUR': 14
        }
        
        for level_name, count in minimal_structure.items():
            employees = self._create_fictitious_employees(level_name, count)
            self.hierarchy_data['employees_by_level'][level_name] = employees
        
        # Attribution des managers
        self._assign_managers()
        
        self.logger.success("Employés minimaux créés")
    
    # ================================================================
    # STATISTIQUES ET FINALISATION
    # ================================================================
    
    def _log_final_statistics(self):
        """Log des statistiques finales avec détails hiérarchiques"""
        self.logger.info("  STATISTIQUES FINALES DE MIGRATION")
        self.logger.info("=" * 80)
        
        # Timing
        self.logger.log_timing()
        
        # Compteurs généraux
        self.logger.log_counters()
        
        # Détails hiérarchiques
        self.logger.info("")
        self.logger.info("  HIÉRARCHIE CRÉÉE:")
        total_employees = 0
        
        for level_name in ['ADMIN', 'DIRECTEUR', 'RH', 'RESPONSABLE', 'CHEF_EQUIPE', 'UTILISATEUR']:
            employees = self.hierarchy_data['employees_by_level'].get(level_name, [])
            count = len(employees)
            total_employees += count
            expected = HIERARCHY_CONFIG[level_name]['count']
            
            # Calcul des managers
            with_manager = sum(1 for emp in employees if emp.manager)
            
            status = " " if count >= expected else " "
            self.logger.info(f"  {level_name}: {count}/{expected} {status} ({with_manager} avec manager)")
            
            # Exemples d'employés (debug niveau 3+)
            if self.logger.debug_level >= 3 and employees:
                for emp in employees[:2]:  # 2 premiers
                    manager_info = f" -> {emp.manager.nom_complet}" if emp.manager else " (pas de manager)"
                    self.logger.debug(f"    {emp.nom_complet}{manager_info}", 3)
        
        self.logger.info(f"  TOTAL: {total_employees} employés")
        
        # Statistiques managériales
        total_managers = len(set(emp.manager.id for level_emps in self.hierarchy_data['employees_by_level'].values() 
                                for emp in level_emps if emp.manager))
        self.logger.info(f"  MANAGERS UNIQUES: {total_managers}")
        
        # Structure organisationnelle
        self.logger.info("")
        self.logger.info("  STRUCTURE ORGANISATIONNELLE:")
        self.logger.info(f"  Départements: {len(self.hierarchy_data['departments'])}")
        self.logger.info(f"  Sites: {len(self.hierarchy_data['sites'])}")
        self.logger.info(f"  Postes: {len(self.hierarchy_data['postes'])}")
        self.logger.info(f"  Compétences: {len(self.hierarchy_data['competences'])}")
        self.logger.info(f"  Motifs absence: {len(self.hierarchy_data['motifs_absence'])}")
        
        # Configuration Kelio
        self.logger.info("")
        self.logger.info("  CONFIGURATION KELIO:")
        self.logger.info(f"  URL: {KELIO_SAFESECUR_SERVICES_URL}")
        self.logger.info(f"  Sync activée: {'Oui' if self.with_kelio_sync else 'Non'}")
        self.logger.info(f"  Configuration: {self.kelio_config.nom if self.kelio_config else 'Non configurée'}")
        
        # Employés Kelio vs Fictifs
        kelio_count = self.logger.get_count('employees_kelio_synced')
        fictifs_count = self.logger.get_count('employees_fictitious_created')
        self.logger.info(f"  Employés Kelio: {kelio_count}")
        self.logger.info(f"  Employés fictifs: {fictifs_count}")
        
        # Validation finale
        self.logger.info("")
        if total_employees >= self.target_employees:
            self.logger.success(f"  OBJECTIF ATTEINT: {total_employees}/{self.target_employees} employés")
        else:
            self.logger.warning(f"  OBJECTIF PARTIEL: {total_employees}/{self.target_employees} employés")
        
        self.logger.info("=" * 80)


# ================================================================
# UTILITAIRES COMPLÉMENTAIRES
# ================================================================

def validate_hierarchy_config():
    """Valide la configuration hiérarchique"""
    total = sum(config['count'] for config in HIERARCHY_CONFIG.values())
    if total != 100:
        raise ValueError(f"Configuration hiérarchique incorrecte: total = {total}, attendu = 100")
    
    # Vérifier les relations managériales
    for level_name, config in HIERARCHY_CONFIG.items():
        reports_to = config.get('reports_to')
        if reports_to:
            # Gérer le cas où reports_to est une liste (DIRECTEUR -> [RH, ADMIN])
            if isinstance(reports_to, list):
                for manager_type in reports_to:
                    if manager_type not in HIERARCHY_CONFIG:
                        raise ValueError(f"Relation managériale incorrecte: {level_name} -> {manager_type}")
            elif reports_to not in HIERARCHY_CONFIG:
                raise ValueError(f"Relation managériale incorrecte: {level_name} -> {reports_to}")


# Validation de la configuration au chargement
validate_hierarchy_config()

# ================================================================
# LOG DE CONFIRMATION
# ================================================================
