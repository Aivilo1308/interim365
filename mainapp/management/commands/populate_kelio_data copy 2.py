#!/usr/bin/env python
"""
Commande Django Management pour remplir les tables avec les données Kelio
Compatible avec l'architecture des modèles optimisés - VERSION CORRIGÉE

CORRECTIONS APPORTÉES SELON LA NOUVELLE HIÉRARCHIE:
✅ Hiérarchie corrigée : RESPONSABLE → DIRECTEUR → RH/ADMIN
✅ Superutilisateurs avec droits complets automatiques
✅ Types de profil alignés sur les nouveaux modèles
✅ Sources de proposition corrigées
✅ Types de validation alignés sur la hiérarchie
✅ Bonus hiérarchiques selon les nouveaux niveaux
✅ Configuration scoring avec nouveaux bonus
✅ Workflow étapes corrigées
✅ Notifications adaptées à la hiérarchie

TABLES GÉRÉES (ARCHITECTURE CORRIGÉE):
✅ Configuration et cache Kelio optimisés
✅ Configuration de scoring avec bonus hiérarchiques CORRIGÉS
✅ Structure organisationnelle (Départements, Sites, Postes)
✅ Employés et profils utilisateurs avec hiérarchie CORRIGÉE
✅ Compétences et référentiel étendu
✅ Motifs d'absence configurables
✅ Formations et absences utilisateurs
✅ Demandes d'intérim avec workflow corrigé
✅ Propositions de candidats avec sources hiérarchiques CORRIGÉES
✅ Scores détaillés candidats avec bonus hiérarchiques
✅ Validations multi-niveaux selon hiérarchie CORRIGÉE
✅ Notifications intelligentes adaptées
✅ Historique complet des actions avec hiérarchie
✅ Réponses candidats avec gestion des délais
✅ Disponibilités utilisateurs
✅ Étapes de workflow configurables selon hiérarchie

Usage:
    python manage.py populate_kelio_data --mode=full
    python manage.py populate_kelio_data --mode=test --no-test-connection
    python manage.py populate_kelio_data --mode=workflow_demo --with-proposals --with-notifications
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

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    """
    Commande Django pour la migration et population des données Kelio avec workflow intégré CORRIGÉ
    """
    help = 'Remplit les tables Django avec les données depuis Kelio ou données de test incluant workflow complet avec hiérarchie corrigée'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=[
                'full', 'structure_only', 'employees_only', 'interim_data', 
                'workflow_demo', 'scoring_demo', 'notifications_demo', 'test'
            ],
            default='full',
            help='Mode de migration avec hiérarchie corrigée'
        )
        parser.add_argument(
            '--no-test-connection',
            action='store_true',
            help='Ne pas tester la connexion Kelio avant migration'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulation sans modification de la base'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forcer la recréation même si les données existent'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Affichage détaillé des opérations'
        )
        parser.add_argument(
            '--sample-size',
            type=int,
            default=50,
            help='Nombre d\'échantillons à créer pour les données de test (défaut: 50)'
        )
        parser.add_argument(
            '--with-proposals',
            action='store_true',
            help='Créer des propositions de candidats avec hiérarchie corrigée'
        )
        parser.add_argument(
            '--with-workflow',
            action='store_true',
            help='Créer des données de workflow complet'
        )
        parser.add_argument(
            '--with-notifications',
            action='store_true',
            help='Créer des notifications adaptées à la hiérarchie'
        )
    
    def handle(self, *args, **options):
        """Point d'entrée principal de la commande"""
        try:
            # Configuration du niveau de log
            if options['verbose']:
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Affichage des paramètres
            mode = options['mode']
            test_connection = not options['no_test_connection']
            dry_run = options['dry_run']
            force = options['force']
            sample_size = options['sample_size']
            with_proposals = options['with_proposals']
            with_workflow = options['with_workflow']
            with_notifications = options['with_notifications']
            
            self.stdout.write(self.style.SUCCESS('🚀 MIGRATION DONNÉES KELIO - VERSION HIÉRARCHIE CORRIGÉE'))
            self.stdout.write("=" * 80)
            self.stdout.write(f"Mode: {mode}")
            self.stdout.write(f"Test connexion: {'Oui' if test_connection else 'Non'}")
            self.stdout.write(f"Simulation: {'Oui' if dry_run else 'Non'}")
            self.stdout.write(f"Force: {'Oui' if force else 'Non'}")
            self.stdout.write(f"Taille échantillon: {sample_size}")
            self.stdout.write(f"Avec propositions hiérarchiques: {'Oui' if with_proposals else 'Non'}")
            self.stdout.write(f"Avec workflow corrigé: {'Oui' if with_workflow else 'Non'}")
            self.stdout.write(f"Avec notifications: {'Oui' if with_notifications else 'Non'}")
            self.stdout.write("=" * 80)
            
            if dry_run:
                self.stdout.write(self.style.WARNING("🧪 MODE SIMULATION - Aucune modification ne sera effectuée"))
                return
            
            # Lancer la migration corrigée
            migration = KelioDataMigrationCorrected(
                stdout=self.stdout,
                style=self.style,
                force=force,
                sample_size=sample_size,
                with_proposals=with_proposals,
                with_workflow=with_workflow,
                with_notifications=with_notifications
            )
            
            success = migration.run_migration(mode, test_connection)
            
            if success:
                self.stdout.write(
                    self.style.SUCCESS('✅ Migration Kelio avec hiérarchie corrigée terminée avec succès')
                )
            else:
                raise CommandError('❌ Migration Kelio avec hiérarchie corrigée échouée')
                
        except Exception as e:
            logger.error(f"Erreur dans la commande: {e}")
            raise CommandError(f'Erreur lors de la migration: {str(e)}')


# ================================================================
# CLASSE PRINCIPALE DE MIGRATION CORRIGÉE
# ================================================================

class KelioDataMigrationCorrected:
    """
    Gestionnaire principal pour la migration des données Kelio avec hiérarchie CORRIGÉE
    """
    
    def __init__(self, stdout=None, style=None, force=False, sample_size=50, 
                 with_proposals=False, with_workflow=False, with_notifications=False):
        # Import des modèles après setup Django
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
        
        self.stats = {
            'total_created': 0,
            'total_updated': 0,
            'total_errors': 0,
            'by_model': {}
        }
        
        # Configuration Kelio par défaut
        self.kelio_config = None
        self.stdout = stdout
        self.style = style
        self.force = force
        self.sample_size = sample_size
        self.with_proposals = with_proposals
        self.with_workflow = with_workflow
        self.with_notifications = with_notifications
        
        # Stockage des objets créés pour les relations et workflow
        self.created_objects = {
            'departements': [],
            'sites': [],
            'postes': [],
            'employes': [],
            'competences': [],
            'motifs_absence': [],
            'demandes_interim': [],
            'propositions': [],
            'validations': [],
            'configurations_scoring': []
        }
        
    def _write(self, message, style_func=None):
        """Helper pour écrire des messages avec style Django"""
        if self.stdout:
            if style_func and self.style:
                self.stdout.write(style_func(message))
            else:
                self.stdout.write(message)
        logger.info(message)
        
    def run_migration(self, mode='full', test_connection=True):
        """
        Lance la migration complète des données Kelio avec hiérarchie CORRIGÉE
        """
        self._write(f"🚀 Début de la migration Kelio avec hiérarchie corrigée en mode: {mode}")
        start_time = timezone.now()
        
        try:
            # Étape 1: Configuration Kelio
            self._setup_kelio_configuration()
            
            # Étape 2: Configuration du scoring CORRIGÉE
            self._setup_scoring_configuration_corrected()
            
            # Étape 3: Configuration du workflow CORRIGÉE
            self._setup_workflow_configuration_corrected()
            
            # Étape 4: Test de connexion (optionnel)
            if test_connection and mode != 'test':
                self._test_kelio_connection()
            
            # Étape 5: Migration selon le mode
            if mode == 'full':
                self._migrate_full_with_workflow_corrected()
            elif mode == 'structure_only':
                self._migrate_structure_only()
            elif mode == 'employees_only':
                self._migrate_employees_only()
            elif mode == 'interim_data':
                self._migrate_interim_data()
            elif mode == 'workflow_demo':
                self._migrate_workflow_demo_corrected()
            elif mode == 'scoring_demo':
                self._migrate_scoring_demo_corrected()
            elif mode == 'notifications_demo':
                self._migrate_notifications_demo_corrected()
            elif mode == 'test':
                self._migrate_test_data_complete_corrected()
            else:
                raise ValueError(f"Mode de migration non supporté: {mode}")
            
            # Statistiques finales
            duration = (timezone.now() - start_time).total_seconds()
            self._log_final_statistics(duration)
            
            self._write("✅ Migration Kelio avec hiérarchie corrigée terminée avec succès", 
                       self.style.SUCCESS if self.style else None)
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la migration Kelio avec hiérarchie corrigée: {e}")
            self._log_error_statistics()
            self._write(f"❌ Erreur migration: {e}", self.style.ERROR if self.style else None)
            return False
    
    def _setup_kelio_configuration(self):
        """Configure la connexion Kelio avec les paramètres fournis"""
        ConfigurationApiKelio = self.models['ConfigurationApiKelio']
        
        try:
            # Rechercher ou créer la configuration Kelio
            self.kelio_config, created = ConfigurationApiKelio.objects.get_or_create(
                nom='Configuration Production',
                defaults={
                    'url_base': 'https://keliodemo-safesecur.kelio.io',
                    'username': 'webservices',
                    'password': '12345',
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
            )
            
            action = "créée" if created else "récupérée"
            self._write(f"🔧 Configuration Kelio {action}: {self.kelio_config.nom}")
            
            if created:
                self.stats['by_model']['ConfigurationApiKelio'] = {'created': 1, 'updated': 0}
            
        except Exception as e:
            logger.error(f"Erreur configuration Kelio: {e}")
            raise
    
    def _setup_scoring_configuration_corrected(self):
        """
        ✅ Configure les paramètres de scoring avec BONUS HIÉRARCHIQUES CORRIGÉS
        """
        ConfigurationScoring = self.models['ConfigurationScoring']
        
        try:
            # Configuration par défaut avec hiérarchie CORRIGÉE
            config_defaut, created = ConfigurationScoring.objects.get_or_create(
                nom='Configuration Défaut',
                defaults={
                    'description': 'Configuration de scoring par défaut avec hiérarchie corrigée',
                    'poids_similarite_poste': 0.25,
                    'poids_competences': 0.25,
                    'poids_experience': 0.20,
                    'poids_disponibilite': 0.15,
                    'poids_proximite': 0.10,
                    'poids_anciennete': 0.05,
                    'bonus_proposition_humaine': 5,
                    'bonus_experience_similaire': 8,
                    'bonus_recommandation': 10,
                    # ✅ BONUS HIÉRARCHIQUES CORRIGÉS
                    'bonus_manager_direct': 12,
                    'bonus_chef_equipe': 8,
                    'bonus_responsable': 15,     # ✅ Niveau 1 validation
                    'bonus_directeur': 18,       # ✅ Niveau 2 validation
                    'bonus_rh': 20,              # ✅ Niveau 3 validation
                    'bonus_admin': 20,           # ✅ Niveau 3 étendu
                    'bonus_superuser': 0,        # ✅ Pas de bonus spécifique (droits complets)
                    'penalite_indisponibilite_partielle': 15,
                    'penalite_indisponibilite_totale': 50,
                    'penalite_distance_excessive': 10,
                    'configuration_par_defaut': True,
                    'actif': True
                }
            )
            
            # Configuration technique avec hiérarchie adaptée
            config_technique, created_tech = ConfigurationScoring.objects.get_or_create(
                nom='Configuration Technique',
                defaults={
                    'description': 'Configuration pour postes techniques avec hiérarchie corrigée',
                    'poids_similarite_poste': 0.20,
                    'poids_competences': 0.35,
                    'poids_experience': 0.25,
                    'poids_disponibilite': 0.10,
                    'poids_proximite': 0.05,
                    'poids_anciennete': 0.05,
                    'bonus_proposition_humaine': 8,
                    'bonus_experience_similaire': 15,
                    'bonus_recommandation': 12,
                    # ✅ BONUS HIÉRARCHIQUES TECHNIQUES
                    'bonus_manager_direct': 15,
                    'bonus_chef_equipe': 10,
                    'bonus_responsable': 18,
                    'bonus_directeur': 20,
                    'bonus_rh': 15,          # Moins d'accent RH sur technique
                    'bonus_admin': 25,       # Plus d'accent admin sur technique
                    'bonus_superuser': 0,
                    'penalite_indisponibilite_partielle': 20,
                    'penalite_indisponibilite_totale': 60,
                    'penalite_distance_excessive': 15,
                    'configuration_par_defaut': False,
                    'actif': True
                }
            )
            
            # Configuration urgence avec hiérarchie accélérée
            config_urgence, created_urgence = ConfigurationScoring.objects.get_or_create(
                nom='Configuration Urgence',
                defaults={
                    'description': 'Configuration pour demandes urgentes avec validation hiérarchique accélérée',
                    'poids_similarite_poste': 0.15,
                    'poids_competences': 0.20,
                    'poids_experience': 0.15,
                    'poids_disponibilite': 0.35,
                    'poids_proximite': 0.10,
                    'poids_anciennete': 0.05,
                    'bonus_proposition_humaine': 10,
                    'bonus_experience_similaire': 5,
                    'bonus_recommandation': 15,
                    # ✅ BONUS HIÉRARCHIQUES URGENCE (plus élevés)
                    'bonus_manager_direct': 20,
                    'bonus_chef_equipe': 15,
                    'bonus_responsable': 25,     # ✅ Plus élevé pour urgence
                    'bonus_directeur': 30,       # ✅ Plus élevé pour urgence
                    'bonus_rh': 35,              # ✅ Maximum pour urgence
                    'bonus_admin': 35,           # ✅ Maximum pour urgence
                    'bonus_superuser': 0,
                    'penalite_indisponibilite_partielle': 30,
                    'penalite_indisponibilite_totale': 80,
                    'penalite_distance_excessive': 5,
                    'configuration_par_defaut': False,
                    'actif': True
                }
            )
            
            configs_created = sum([created, created_tech, created_urgence])
            self._write(f"⚙️ Configurations de scoring avec hiérarchie corrigée créées: {configs_created}")
            
            self.created_objects['configurations_scoring'] = [config_defaut, config_technique, config_urgence]
            
            if configs_created > 0:
                self._update_stats('ConfigurationScoring', True, count=configs_created)
            
        except Exception as e:
            logger.error(f"Erreur configuration scoring corrigée: {e}")
            raise
    
    def _setup_workflow_configuration_corrected(self):
        """
        ✅ Configure les étapes du workflow d'intérim avec hiérarchie CORRIGÉE
        """
        WorkflowEtape = self.models['WorkflowEtape']
        
        try:
            etapes_workflow = [
                {
                    'nom': 'Création de demande',
                    'type_etape': 'DEMANDE',
                    'ordre': 1,
                    'obligatoire': True,
                    'delai_max_heures': None,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'actif': True
                },
                {
                    'nom': 'Proposition de candidats',
                    'type_etape': 'PROPOSITION_CANDIDATS',
                    'ordre': 2,
                    'obligatoire': True,
                    'delai_max_heures': 48,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'actif': True
                },
                {
                    'nom': 'Validation Responsable (N+1)',      # ✅ CORRIGÉ
                    'type_etape': 'VALIDATION_RESPONSABLE',      # ✅ CORRIGÉ
                    'ordre': 3,
                    'obligatoire': True,
                    'delai_max_heures': 24,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'actif': True
                },
                {
                    'nom': 'Validation Directeur (N+2)',        # ✅ CORRIGÉ
                    'type_etape': 'VALIDATION_DIRECTEUR',        # ✅ CORRIGÉ
                    'ordre': 4,
                    'obligatoire': True,
                    'delai_max_heures': 24,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'actif': True
                },
                {
                    'nom': 'Validation RH/Admin (Final)',       # ✅ CORRIGÉ
                    'type_etape': 'VALIDATION_RH_ADMIN',         # ✅ CORRIGÉ
                    'ordre': 5,
                    'obligatoire': True,
                    'delai_max_heures': 12,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'actif': True
                },
                {
                    'nom': 'Notification candidat',
                    'type_etape': 'NOTIFICATION_CANDIDAT',
                    'ordre': 6,
                    'obligatoire': True,
                    'delai_max_heures': 2,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'actif': True
                },
                {
                    'nom': 'Acceptation candidat',
                    'type_etape': 'ACCEPTATION_CANDIDAT',
                    'ordre': 7,
                    'obligatoire': True,
                    'delai_max_heures': 72,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'actif': True
                },
                {
                    'nom': 'Finalisation',
                    'type_etape': 'FINALISATION',
                    'ordre': 8,
                    'obligatoire': True,
                    'delai_max_heures': None,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'actif': True
                }
            ]
            
            etapes_created = 0
            for etape_data in etapes_workflow:
                etape, created = WorkflowEtape.objects.get_or_create(
                    type_etape=etape_data['type_etape'],
                    defaults=etape_data
                )
                if created:
                    etapes_created += 1
            
            self._write(f"📋 Étapes de workflow avec hiérarchie corrigée créées: {etapes_created}")
            
            if etapes_created > 0:
                self._update_stats('WorkflowEtape', True, count=etapes_created)
            
        except Exception as e:
            logger.error(f"Erreur configuration workflow corrigée: {e}")
            raise
    
    def _test_kelio_connection(self):
        """Test la connexion aux services Kelio"""
        try:
            self._write("🔍 Test de connexion aux services Kelio...")
            
            # Import du service de synchronisation
            try:
                from mainapp.services.kelio_api_simplifie_modif import get_kelio_sync_service
                
                sync_service = get_kelio_sync_service(self.kelio_config)
                test_results = sync_service.test_connexion_complete()
                
                if test_results.get('statut_global', False):
                    self._write("✅ Connexion Kelio réussie", self.style.SUCCESS if self.style else None)
                    
                    # Log détaillé des services
                    for service_name, service_info in test_results.get('services', {}).items():
                        status = "✅" if service_info['statut'] == 'OK' else "❌"
                        self._write(f"  {status} {service_name}: {service_info.get('message', 'OK')}")
                else:
                    self._write("⚠️ Certains services Kelio ne sont pas disponibles", 
                               self.style.WARNING if self.style else None)
                    self._write("Migration en mode dégradé - utilisation de données de test")
                    
            except ImportError as e:
                logger.warning(f"Service Kelio non disponible: {e}")
                self._write("⚠️ Service Kelio non disponible - utilisation de données de test", 
                           self.style.WARNING if self.style else None)
                
        except Exception as e:
            logger.warning(f"⚠️ Test de connexion Kelio échoué: {e}")
            self._write("⚠️ Test connexion échoué - migration avec données de test", 
                       self.style.WARNING if self.style else None)
    
    def _migrate_full_with_workflow_corrected(self):
        """Migration complète avec workflow intégré et hiérarchie CORRIGÉE"""
        self._write("📊 Migration complète avec workflow et hiérarchie corrigée")
        
        # Ordre de migration respectant les dépendances + workflow corrigé
        migration_steps = [
            ("Départements", self._migrate_departements),
            ("Sites", self._migrate_sites),
            ("Postes", self._migrate_postes),
            ("Motifs d'absence", self._migrate_motifs_absence),
            ("Compétences (référentiel)", self._migrate_competences_referentiel),
            ("Employés avec hiérarchie corrigée", self._migrate_employes_corrected),
            ("Compétences employés", self._migrate_competences_employes),
            ("Formations employés", self._migrate_formations_employes),
            ("Absences employés", self._migrate_absences_employes),
            ("Disponibilités employés", self._migrate_disponibilites_employes),
            ("Demandes d'intérim", self._migrate_demandes_interim),
            ("Propositions candidats avec hiérarchie", self._migrate_propositions_candidats_corrected),
            ("Scores détaillés avec bonus hiérarchiques", self._migrate_scores_detailles_corrected),
            ("Validations avec hiérarchie corrigée", self._migrate_validations_corrected),
            ("Workflow demandes", self._migrate_workflow_demandes),
            ("Historique actions avec hiérarchie", self._migrate_historique_actions_corrected),
            ("Notifications adaptées", self._migrate_notifications_corrected),
            ("Réponses candidats", self._migrate_reponses_candidats),
            ("Cache Kelio", self._migrate_cache_kelio)
        ]
        
        for step_name, step_function in migration_steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
                # Continuer la migration même en cas d'erreur sur une étape
    
    def _migrate_workflow_demo_corrected(self):
        """Migration en mode démo workflow avec hiérarchie CORRIGÉE"""
        self._write("🎯 Migration en mode démo workflow avec hiérarchie corrigée")
        
        # Créer une structure minimale + workflow complet corrigé
        steps = [
            ("Structure de base", self._migrate_structure_only),
            ("Employés avec hiérarchie corrigée", self._create_test_employes_corrected),
            ("Demandes d'intérim avec workflow", self._create_demandes_with_workflow_corrected),
            ("Propositions hiérarchiques", self._create_test_propositions_hierarchiques),
            ("Validations multi-niveaux corrigées", self._create_test_validations_hierarchiques),
            ("Notifications intelligentes", self._create_test_notifications_hierarchiques),
            ("Workflow demandes complet", self._create_test_workflow_complet_corrige)
        ]
        
        for step_name, step_function in steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
    
    def _migrate_scoring_demo_corrected(self):
        """Migration en mode démo scoring avec bonus hiérarchiques CORRIGÉS"""
        self._write("📊 Migration en mode démo scoring avec hiérarchie corrigée")
        
        steps = [
            ("Structure de base", self._migrate_structure_only),
            ("Employés hiérarchiques", self._create_test_employes_corrected),
            ("Demandes d'intérim", self._create_test_demandes_interim),
            ("Scores avec bonus hiérarchiques", self._create_test_scores_bonus_hierarchiques),
            ("Comparaisons scoring corrigées", self._create_test_comparaisons_scoring_corrigees)
        ]
        
        for step_name, step_function in steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
    
    def _migrate_notifications_demo_corrected(self):
        """Migration en mode démo notifications avec hiérarchie CORRIGÉE"""
        self._write("🔔 Migration en mode démo notifications avec hiérarchie corrigée")
        
        steps = [
            ("Structure de base", self._migrate_structure_only),
            ("Employés hiérarchiques", self._create_test_employes_corrected),
            ("Demandes d'intérim", self._create_test_demandes_interim),
            ("Notifications hiérarchiques", self._create_test_notifications_hierarchiques),
            ("Notifications avec métadonnées", self._create_test_notifications_metadata_corrigees)
        ]
        
        for step_name, step_function in steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
    
    def _migrate_test_data_complete_corrected(self):
        """Migration avec données de test complètes incluant hiérarchie CORRIGÉE"""
        self._write("🧪 Migration avec données de test complètes + hiérarchie corrigée")
        
        steps = [
            ("Départements test", self._create_test_departements),
            ("Sites test", self._create_test_sites),
            ("Postes test", self._create_test_postes),
            ("Motifs absence test", self._create_test_motifs_absence),
            ("Compétences test", self._create_test_competences),
            ("Employés hiérarchiques test", self._create_test_employes_corrected),
            ("Formations test", self._create_test_formations),
            ("Absences test", self._create_test_absences),
            ("Disponibilités test", self._create_test_disponibilites),
            ("Demandes intérim test", self._create_test_demandes_interim),
            ("Propositions hiérarchiques test", self._create_test_propositions_hierarchiques),
            ("Scores hiérarchiques test", self._create_test_scores_bonus_hierarchiques),
            ("Validations hiérarchiques test", self._create_test_validations_hierarchiques),
            ("Workflow demandes corrigé test", self._create_test_workflow_complet_corrige),
            ("Historique hiérarchique test", self._create_test_historique_actions_corrected),
            ("Notifications hiérarchiques test", self._create_test_notifications_hierarchiques),
            ("Réponses candidats test", self._create_test_reponses_candidats),
            ("Cache test", self._create_test_cache)
        ]
        
        for step_name, step_function in steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
    
    # ================================================================
    # MÉTHODES CORRIGÉES POUR LA HIÉRARCHIE
    # ================================================================
    
    def _create_test_employes_corrected(self):
        """
        ✅ Crée des employés de test avec profils hiérarchiques CORRIGÉS
        """
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        ProfilUtilisateurKelio = self.models['ProfilUtilisateurKelio']
        ProfilUtilisateurExtended = self.models['ProfilUtilisateurExtended']
        
        departements = self.created_objects.get('departements', [])
        sites = self.created_objects.get('sites', [])
        postes = self.created_objects.get('postes', [])
        
        if not all([departements, sites]):
            self._write("⚠️ Données manquantes pour créer les employés")
            return
        
        # ✅ Employés de base avec hiérarchie CORRIGÉE
        base_employees = [
            {
                'user_data': {
                    'username': 'jkouassi', 
                    'first_name': 'Jean', 
                    'last_name': 'Kouassi', 
                    'email': 'jean.kouassi@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP001', 
                    'type_profil': 'CHEF_EQUIPE',      # ✅ Peut proposer, ne valide pas
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 05 06 07 08', 
                    'disponible_interim': True, 
                    'rayon_deplacement_km': 50
                }
            },
            {
                'user_data': {
                    'username': 'mdiabate', 
                    'first_name': 'Marie', 
                    'last_name': 'Diabaté', 
                    'email': 'marie.diabate@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP002', 
                    'type_profil': 'RESPONSABLE',       # ✅ Niveau 1 de validation
                    'statut_employe': 'ACTIF', 
                    'departement': departements[1] if len(departements) > 1 else departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 07 08 09 10', 
                    'disponible_interim': True, 
                    'rayon_deplacement_km': 30
                }
            },
            {
                'user_data': {
                    'username': 'ayao', 
                    'first_name': 'Aya', 
                    'last_name': 'Yao', 
                    'email': 'aya.yao@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP003', 
                    'type_profil': 'UTILISATEUR',       # ✅ Utilisateur standard
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[1] if len(sites) > 1 else sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 31 32 33 34', 
                    'disponible_interim': True, 
                    'rayon_deplacement_km': 25
                }
            },
            {
                'user_data': {
                    'username': 'kkouame', 
                    'first_name': 'Kouadio', 
                    'last_name': 'Kouame', 
                    'email': 'kouadio.kouame@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP004', 
                    'type_profil': 'DIRECTEUR',         # ✅ Niveau 2 de validation
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 01 02 03 04', 
                    'disponible_interim': False, 
                    'rayon_deplacement_km': 200
                }
            },
            {
                'user_data': {
                    'username': 'skonan', 
                    'first_name': 'Sarah', 
                    'last_name': 'Konan', 
                    'email': 'sarah.konan@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP005', 
                    'type_profil': 'RH',                # ✅ Niveau 3 validation finale
                    'statut_employe': 'ACTIF', 
                    'departement': departements[1] if len(departements) > 1 else departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 20 21 22 23', 
                    'disponible_interim': False, 
                    'rayon_deplacement_km': 100
                }
            },
            {
                'user_data': {
                    'username': 'admintest', 
                    'first_name': 'Admin', 
                    'last_name': 'Test', 
                    'email': 'admin.test@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP006', 
                    'type_profil': 'ADMIN',             # ✅ Niveau 3 étendu
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 40 41 42 43', 
                    'disponible_interim': False, 
                    'rayon_deplacement_km': 300
                }
            },
            {
                'user_data': {
                    'username': 'superuser', 
                    'first_name': 'Super', 
                    'last_name': 'User', 
                    'email': 'super.user@entreprise.ci', 
                    'is_active': True,
                    'is_superuser': True                # ✅ Superutilisateur
                },
                'profil_data': {
                    'matricule': 'EMP007', 
                    'type_profil': 'ADMIN',             # ✅ Type ADMIN + is_superuser
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 50 51 52 53', 
                    'disponible_interim': False, 
                    'rayon_deplacement_km': 500
                }
            },
            # Ajout d'employés UTILISATEUR supplémentaires pour les candidatures
            {
                'user_data': {
                    'username': 'candidate1', 
                    'first_name': 'Pierre', 
                    'last_name': 'Assi', 
                    'email': 'pierre.assi@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP008', 
                    'type_profil': 'UTILISATEUR',
                    'statut_employe': 'ACTIF', 
                    'departement': departements[0], 
                    'site': sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 60 61 62 63', 
                    'disponible_interim': True, 
                    'rayon_deplacement_km': 40
                }
            },
            {
                'user_data': {
                    'username': 'candidate2', 
                    'first_name': 'Fatou', 
                    'last_name': 'Bamba', 
                    'email': 'fatou.bamba@entreprise.ci', 
                    'is_active': True
                },
                'profil_data': {
                    'matricule': 'EMP009', 
                    'type_profil': 'UTILISATEUR',
                    'statut_employe': 'ACTIF', 
                    'departement': departements[1] if len(departements) > 1 else departements[0], 
                    'site': sites[1] if len(sites) > 1 else sites[0], 
                    'actif': True
                },
                'extended_data': {
                    'telephone': '+225 70 71 72 73', 
                    'disponible_interim': True, 
                    'rayon_deplacement_km': 35
                }
            }
        ]
        
        created_count = 0
        for emp_data in base_employees:
            try:
                with transaction.atomic():
                    if User.objects.filter(username=emp_data['user_data']['username']).exists():
                        if not self.force:
                            continue
                        else:
                            User.objects.filter(username=emp_data['user_data']['username']).delete()
                    
                    user = User.objects.create_user(**emp_data['user_data'])
                    profil = ProfilUtilisateur.objects.create(user=user, **emp_data['profil_data'])
                    
                    # Poste si disponible
                    if postes and not profil.poste:
                        profil.poste = random.choice(postes)
                        profil.save()
                    
                    ProfilUtilisateurKelio.objects.create(
                        profil=profil,
                        kelio_employee_key=1000 + created_count,
                        kelio_badge_code=f'B{created_count:03d}'
                    )
                    
                    ProfilUtilisateurExtended.objects.create(profil=profil, **emp_data['extended_data'])
                    
                    self.created_objects['employes'].append(profil)
                    created_count += 1
                    self._update_stats('ProfilUtilisateur', True)
                    
            except Exception as e:
                logger.error(f"Erreur création employé: {e}")
        
        self._write(f"    ✅ {created_count} employés avec hiérarchie corrigée créés")
        
        # Afficher la hiérarchie créée
        if created_count > 0:
            self._write("    👥 Hiérarchie créée:")
            hierarchy_count = {}
            for emp in self.created_objects['employes']:
                hierarchy_count[emp.type_profil] = hierarchy_count.get(emp.type_profil, 0) + 1
            
            for profil_type, count in hierarchy_count.items():
                self._write(f"      • {profil_type}: {count} employé(s)")
    
    def _create_test_propositions_hierarchiques(self):
        """
        ✅ Crée des propositions de candidats avec sources hiérarchiques CORRIGÉES
        """
        PropositionCandidat = self.models['PropositionCandidat']
        demandes = self.created_objects.get('demandes_interim', [])
        employes = self.created_objects.get('employes', [])
        
        if not demandes or not employes:
            self._write("⚠️ Pas de demandes ou d'employés pour créer les propositions hiérarchiques")
            return
        
        created_count = 0
        
        # ✅ Trouver les proposants selon la hiérarchie CORRIGÉE
        proposants_hierarchiques = {
            'CHEF_EQUIPE': [emp for emp in employes if emp.type_profil == 'CHEF_EQUIPE'],
            'RESPONSABLE': [emp for emp in employes if emp.type_profil == 'RESPONSABLE'],
            'DIRECTEUR': [emp for emp in employes if emp.type_profil == 'DIRECTEUR'],
            'RH': [emp for emp in employes if emp.type_profil == 'RH'],
            'ADMIN': [emp for emp in employes if emp.type_profil == 'ADMIN']
        }
        
        # Candidats potentiels (employés UTILISATEUR principalement)
        candidats_potentiels = [emp for emp in employes if emp.type_profil == 'UTILISATEUR']
        
        for demande in demandes[:10]:  # Traiter quelques demandes
            # Créer 2-4 propositions par demande avec différentes sources hiérarchiques
            nb_propositions = random.randint(2, 4)
            
            if len(candidats_potentiels) < nb_propositions:
                continue
            
            candidats_choisis = random.sample(candidats_potentiels, nb_propositions)
            
            for i, candidat in enumerate(candidats_choisis):
                # ✅ Sélectionner un proposant selon la hiérarchie avec distribution réaliste
                if i == 0:  # Premier candidat souvent proposé par chef équipe ou responsable
                    source_types = ['CHEF_EQUIPE', 'RESPONSABLE']
                    weights = [0.6, 0.4]
                elif i == 1:  # Deuxième candidat par niveaux supérieurs
                    source_types = ['RESPONSABLE', 'DIRECTEUR']
                    weights = [0.7, 0.3]
                else:  # Autres candidats par tous niveaux
                    source_types = ['CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN']
                    weights = [0.3, 0.3, 0.2, 0.1, 0.1]
                
                source_type = random.choices(source_types, weights=weights)[0]
                proposants_disponibles = proposants_hierarchiques.get(source_type, [])
                
                if not proposants_disponibles:
                    continue
                
                proposant = random.choice(proposants_disponibles)
                
                # ✅ Sources CORRIGÉES selon la hiérarchie
                source_mapping = {
                    'CHEF_EQUIPE': 'CHEF_EQUIPE',
                    'RESPONSABLE': 'RESPONSABLE',        # ✅ CORRIGÉ
                    'DIRECTEUR': 'DIRECTEUR',            # ✅ CORRIGÉ  
                    'RH': 'RH',                          # ✅ CORRIGÉ
                    'ADMIN': 'ADMIN'                     # ✅ CORRIGÉ
                }
                
                source_proposition = source_mapping.get(proposant.type_profil, 'AUTRE')
                
                # Manager direct si applicable
                if proposant == getattr(demande.demandeur, 'manager', None):
                    source_proposition = 'MANAGER_DIRECT'
                
                # Justifications adaptées à la hiérarchie
                justifications_par_niveau = {
                    'CHEF_EQUIPE': [
                        f"En tant que chef d'équipe, je recommande {candidat.nom_complet} pour sa proximité avec l'équipe",
                        f"J'ai travaillé directement avec {candidat.nom_complet} et peux attester de ses compétences"
                    ],
                    'RESPONSABLE': [
                        f"En ma qualité de responsable, je valide les compétences de {candidat.nom_complet} pour ce poste",
                        f"Candidat évalué et approuvé par mon service pour cette mission d'intérim"
                    ],
                    'DIRECTEUR': [
                        f"Proposition directoriale: {candidat.nom_complet} a un excellent dossier pour cette mission",
                        f"Validation directeur pour {candidat.nom_complet} - profil stratégique confirmé"
                    ],
                    'RH': [
                        f"Validation RH: {candidat.nom_complet} répond aux critères requis et est disponible",
                        f"Candidat pré-qualifié par les Ressources Humaines avec profil adapté"
                    ],
                    'ADMIN': [
                        f"Proposition administrative: {candidat.nom_complet} avec autorisation exceptionnelle",
                        f"Candidat validé au niveau administratif pour cette mission critique"
                    ]
                }
                
                justifications = justifications_par_niveau.get(proposant.type_profil, [
                    f"Proposition de {candidat.nom_complet} pour cette mission"
                ])
                
                justification = random.choice(justifications)
                
                try:
                    proposition = PropositionCandidat.objects.create(
                        demande_interim=demande,
                        candidat_propose=candidat,
                        proposant=proposant,
                        source_proposition=source_proposition,
                        justification=justification,
                        competences_specifiques=f"Compétences validées niveau {proposant.type_profil}",
                        experience_pertinente=f"Expérience confirmée par {proposant.type_profil}",
                        statut=random.choice(['SOUMISE', 'EN_EVALUATION', 'EVALUEE', 'RETENUE']),
                        niveau_validation_propose=self._get_niveau_validation_pour_type(proposant.type_profil),
                        score_automatique=random.randint(60, 95),
                        bonus_proposition_humaine=self._get_bonus_hierarchique_corrige(proposant.type_profil)
                    )
                    
                    created_count += 1
                    self.created_objects.setdefault('propositions', []).append(proposition)
                    self._update_stats('PropositionCandidat', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création proposition hiérarchique: {e}")
        
        self._write(f"    ✅ {created_count} propositions avec hiérarchie corrigée créées")
        
        # Statistiques par niveau hiérarchique
        if created_count > 0:
            stats_hierarchiques = {}
            for prop in self.created_objects.get('propositions', []):
                source = prop.source_proposition
                stats_hierarchiques[source] = stats_hierarchiques.get(source, 0) + 1
            
            self._write("    📊 Répartition par niveau hiérarchique:")
            for source, count in stats_hierarchiques.items():
                bonus = self._get_bonus_hierarchique_corrige_from_source(source)
                self._write(f"      • {source}: {count} proposition(s) (bonus +{bonus} pts)")
    
    def _create_test_scores_bonus_hierarchiques(self):
        """
        ✅ Crée des scores détaillés avec bonus hiérarchiques CORRIGÉS
        """
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        propositions = self.created_objects.get('propositions', [])
        
        if not propositions:
            self._write("⚠️ Pas de propositions pour créer les scores avec bonus hiérarchiques")
            return
        
        created_count = 0
        
        for proposition in propositions:
            try:
                # Scores de base réalistes
                score_similarite = random.randint(40, 95)
                score_competences = random.randint(30, 90)
                score_experience = random.randint(25, 85)
                score_disponibilite = random.randint(60, 100)
                score_proximite = random.randint(30, 100)
                score_anciennete = random.randint(20, 80)
                
                # ✅ Bonus hiérarchique CORRIGÉ selon la source
                bonus_hierarchique = self._get_bonus_hierarchique_corrige_from_source(
                    proposition.source_proposition
                )
                
                # Autres bonus
                bonus_experience = random.randint(0, 8) if score_experience > 70 else 0
                bonus_recommandation = random.randint(0, 10) if proposition.justification else 0
                penalite_indisponibilite = random.randint(0, 5)
                
                score_detail = ScoreDetailCandidat.objects.create(
                    candidat=proposition.candidat_propose,
                    demande_interim=proposition.demande_interim,
                    proposition_humaine=proposition,
                    score_similarite_poste=score_similarite,
                    score_competences=score_competences,
                    score_experience=score_experience,
                    score_disponibilite=score_disponibilite,
                    score_proximite=score_proximite,
                    score_anciennete=score_anciennete,
                    bonus_proposition_humaine=proposition.bonus_proposition_humaine,
                    bonus_experience_similaire=bonus_experience,
                    bonus_recommandation=bonus_recommandation,
                    bonus_hierarchique=bonus_hierarchique,         # ✅ Nouveau bonus hiérarchique
                    penalite_indisponibilite=penalite_indisponibilite,
                    calcule_par='HUMAIN'
                )
                
                # Calculer le score total avec la nouvelle méthode
                score_detail.calculer_score_total()
                score_detail.save()
                
                # Mettre à jour le score dans la proposition
                proposition.score_automatique = score_detail.score_total
                proposition.save()
                
                created_count += 1
                self._update_stats('ScoreDetailCandidat', True)
                
            except Exception as e:
                logger.error(f"Erreur création score avec bonus hiérarchique: {e}")
        
        self._write(f"    ✅ {created_count} scores avec bonus hiérarchiques corrigés créés")
        
        # Afficher les bonus par niveau
        if created_count > 0:
            self._write("    🎯 Bonus hiérarchiques appliqués:")
            bonus_info = {
                'CHEF_EQUIPE': 8,
                'RESPONSABLE': 15,       # ✅ Niveau 1
                'DIRECTEUR': 18,         # ✅ Niveau 2
                'RH': 20,                # ✅ Niveau 3
                'ADMIN': 20              # ✅ Niveau 3 étendu
            }
            for niveau, bonus in bonus_info.items():
                self._write(f"      • {niveau}: +{bonus} points")
    
    def _create_test_validations_hierarchiques(self):
        """
        ✅ Crée des validations selon la hiérarchie CORRIGÉE
        """
        ValidationDemande = self.models['ValidationDemande']
        demandes = self.created_objects.get('demandes_interim', [])
        employes = self.created_objects.get('employes', [])
        
        if not demandes or not employes:
            self._write("⚠️ Pas de demandes ou d'employés pour créer les validations hiérarchiques")
            return
        
        created_count = 0
        
        # ✅ Validateurs selon la hiérarchie CORRIGÉE
        validateurs_par_niveau = {
            1: [emp for emp in employes if emp.type_profil == 'RESPONSABLE'],     # ✅ Niveau 1
            2: [emp for emp in employes if emp.type_profil == 'DIRECTEUR'],       # ✅ Niveau 2
            3: [emp for emp in employes if emp.type_profil in ['RH', 'ADMIN']]    # ✅ Niveau 3
        }
        
        for demande in demandes[:12]:  # Traiter quelques demandes
            # ✅ Processus de validation selon la hiérarchie CORRIGÉE
            niveaux_validation = [
                (1, 'RESPONSABLE', validateurs_par_niveau[1]),    # ✅ NIVEAU 1: RESPONSABLE
                (2, 'DIRECTEUR', validateurs_par_niveau[2]),      # ✅ NIVEAU 2: DIRECTEUR
                (3, random.choice(['RH', 'ADMIN']), validateurs_par_niveau[3])  # ✅ NIVEAU 3: RH/ADMIN
            ]
            
            decision_precedente = 'APPROUVE'
            
            for niveau, type_validation, validateurs_niveau in niveaux_validation:
                if not validateurs_niveau or decision_precedente == 'REFUSE':
                    break
                
                validateur = random.choice(validateurs_niveau)
                
                # Décisions réalistes selon le niveau et la hiérarchie
                if niveau == 1:  # RESPONSABLE
                    decisions_possibles = ['APPROUVE', 'APPROUVE_AVEC_MODIF', 'REFUSE', 'CANDIDAT_AJOUTE']
                    probabilites = [0.6, 0.2, 0.1, 0.1]
                elif niveau == 2:  # DIRECTEUR
                    decisions_possibles = ['APPROUVE', 'APPROUVE_AVEC_MODIF', 'REFUSE']
                    probabilites = [0.7, 0.2, 0.1]
                else:  # RH/ADMIN (niveau 3)
                    decisions_possibles = ['APPROUVE', 'APPROUVE_AVEC_MODIF']
                    probabilites = [0.8, 0.2]
                
                decision = random.choices(decisions_possibles, weights=probabilites)[0]
                decision_precedente = decision
                
                # Candidats retenus/rejetés selon la décision
                candidats_retenus = []
                candidats_rejetes = []
                
                if decision.startswith('APPROUVE'):
                    # Simuler la rétention de candidats
                    nb_candidats = random.randint(1, 3)
                    for i in range(nb_candidats):
                        candidats_retenus.append({
                            'candidat_id': random.randint(1, 100),
                            'candidat_nom': f'Candidat Test {i+1}',
                            'score': random.randint(75, 95),
                            'source': type_validation,
                            'justification': f"Retenu au niveau {niveau} par {type_validation}",
                            'niveau_validation': niveau
                        })
                
                # ✅ Commentaires adaptés à la hiérarchie CORRIGÉE
                commentaires_par_niveau = {
                    'RESPONSABLE': f"Validation niveau 1 (Responsable): {decision}. Candidats évalués selon critères opérationnels.",
                    'DIRECTEUR': f"Validation niveau 2 (Directeur): {decision}. Validation stratégique et budgétaire confirmée.",
                    'RH': f"Validation finale RH: {decision}. Conformité RH et autorisation définitive accordée.",
                    'ADMIN': f"Validation finale Admin: {decision}. Validation administrative et autorisations spéciales."
                }
                
                commentaire = commentaires_par_niveau.get(type_validation, 
                    f"Validation {type_validation} niveau {niveau}: {decision}")
                
                # Nouveau candidat si ajout (pour niveau 1 principalement)
                nouveau_candidat = None
                justification_nouveau = ""
                if decision == 'CANDIDAT_AJOUTE' and niveau == 1:
                    candidats_possibles = [emp for emp in employes 
                                         if emp.type_profil == 'UTILISATEUR']
                    if candidats_possibles:
                        nouveau_candidat = random.choice(candidats_possibles)
                        justification_nouveau = f"Candidat {nouveau_candidat.nom_complet} ajouté par {validateur.nom_complet} lors de la validation niveau {niveau} ({type_validation})"
                
                try:
                    validation = ValidationDemande.objects.create(
                        demande=demande,
                        type_validation=type_validation,             # ✅ Types CORRIGÉS
                        niveau_validation=niveau,
                        validateur=validateur,
                        decision=decision,
                        commentaire=commentaire,
                        date_demande_validation=timezone.now() - timedelta(days=niveau),
                        date_validation=timezone.now() - timedelta(days=niveau-1, hours=random.randint(2, 20)),
                        candidats_retenus=candidats_retenus,
                        candidats_rejetes=candidats_rejetes,
                        nouveau_candidat_propose=nouveau_candidat,
                        justification_nouveau_candidat=justification_nouveau
                    )
                    
                    created_count += 1
                    self.created_objects.setdefault('validations', []).append(validation)
                    self._update_stats('ValidationDemande', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création validation hiérarchique: {e}")
        
        self._write(f"    ✅ {created_count} validations avec hiérarchie corrigée créées")
        
        # Statistiques par niveau de validation
        if created_count > 0:
            stats_validation = {}
            for validation in self.created_objects.get('validations', []):
                niveau = f"Niveau {validation.niveau_validation} ({validation.type_validation})"
                stats_validation[niveau] = stats_validation.get(niveau, 0) + 1
            
            self._write("    📊 Répartition des validations par niveau:")
            for niveau, count in stats_validation.items():
                self._write(f"      • {niveau}: {count} validation(s)")
    
    def _create_test_notifications_hierarchiques(self):
        """
        ✅ Crée des notifications adaptées à la hiérarchie CORRIGÉE
        """
        NotificationInterim = self.models['NotificationInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        employes = self.created_objects.get('employes', [])
        propositions = self.created_objects.get('propositions', [])
        validations = self.created_objects.get('validations', [])
        
        if not demandes or not employes:
            self._write("⚠️ Pas de données pour créer notifications hiérarchiques")
            return
        
        created_count = 0
        
        # ✅ Destinataires selon la hiérarchie CORRIGÉE
        destinataires_par_niveau = {
            'CHEF_EQUIPE': [emp for emp in employes if emp.type_profil == 'CHEF_EQUIPE'],
            'RESPONSABLE': [emp for emp in employes if emp.type_profil == 'RESPONSABLE'],
            'DIRECTEUR': [emp for emp in employes if emp.type_profil == 'DIRECTEUR'],
            'RH': [emp for emp in employes if emp.type_profil == 'RH'],
            'ADMIN': [emp for emp in employes if emp.type_profil == 'ADMIN'],
            'SUPERUSER': [emp for emp in employes if emp.is_superuser]
        }
        
        # ✅ Templates de notifications par niveau hiérarchique
        templates_hierarchiques = {
            'NOUVELLE_DEMANDE': {
                'CHEF_EQUIPE': {
                    'titre': 'Nouvelle demande - Équipe concernée',
                    'message': 'Une nouvelle demande d\'intérim concernant votre équipe nécessite votre attention.',
                    'urgence': 'NORMALE'
                },
                'RESPONSABLE': {
                    'titre': 'Demande nécessitant validation N+1',
                    'message': 'Nouvelle demande d\'intérim en attente de votre validation de niveau 1.',
                    'urgence': 'HAUTE'
                },
                'DIRECTEUR': {
                    'titre': 'Information demande intérim',
                    'message': 'Nouvelle demande d\'intérim créée dans votre périmètre.',
                    'urgence': 'NORMALE'
                },
                'RH': {
                    'titre': 'Nouvelle demande RH',
                    'message': 'Nouvelle demande d\'intérim pour suivi RH.',
                    'urgence': 'NORMALE'
                },
                'ADMIN': {
                    'titre': 'Nouvelle demande - Suivi admin',
                    'message': 'Nouvelle demande d\'intérim pour supervision administrative.',
                    'urgence': 'NORMALE'
                }
            },
            'DEMANDE_A_VALIDER': {
                'RESPONSABLE': {
                    'titre': 'URGENT - Validation niveau 1 requise',
                    'message': 'Demande d\'intérim en attente de votre validation de niveau 1 (Responsable).',
                    'urgence': 'CRITIQUE'
                },
                'DIRECTEUR': {
                    'titre': 'URGENT - Validation niveau 2 requise',
                    'message': 'Demande d\'intérim en attente de votre validation de niveau 2 (Directeur).',
                    'urgence': 'CRITIQUE'
                },
                'RH': {
                    'titre': 'URGENT - Validation finale RH requise',
                    'message': 'Demande d\'intérim en attente de validation finale RH.',
                    'urgence': 'CRITIQUE'
                },
                'ADMIN': {
                    'titre': 'URGENT - Validation finale Admin requise',
                    'message': 'Demande d\'intérim en attente de validation finale administrative.',
                    'urgence': 'CRITIQUE'
                }
            },
            'PROPOSITION_CANDIDAT': {
                'TOUS': {
                    'titre': 'Nouveau candidat proposé par {niveau_proposant}',
                    'message': 'Un candidat a été proposé par un {niveau_proposant} pour évaluation.',
                    'urgence': 'NORMALE'
                }
            }
        }
        
        for demande in demandes[:8]:
            # 1. ✅ Notifications de création selon la hiérarchie
            for niveau, employes_niveau in destinataires_par_niveau.items():
                if not employes_niveau:
                    continue
                
                template = templates_hierarchiques['NOUVELLE_DEMANDE'].get(niveau)
                if not template:
                    continue
                
                destinataire = random.choice(employes_niveau)
                
                # Métadonnées hiérarchiques
                metadata = {
                    'demande_id': demande.id,
                    'niveau_destinataire': niveau,
                    'urgence_demande': demande.urgence,
                    'workflow_etape': 'creation',
                    'hierarchie_corrigee': True,
                    'niveau_validation_requis': self._get_niveau_validation_pour_type(niveau)
                }
                
                try:
                    NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=demande.demandeur,
                        demande=demande,
                        type_notification='NOUVELLE_DEMANDE',
                        urgence=template['urgence'],
                        titre=template['titre'],
                        message=template['message'],
                        url_action_principale=f"/interim/demande/{demande.id}/",
                        texte_action_principale="Consulter",
                        metadata=metadata
                    )
                    created_count += 1
                    
                except Exception as e:
                    logger.error(f"Erreur notification hiérarchique création: {e}")
            
            # 2. ✅ Notifications de validation selon les niveaux
            for niveau in [1, 2, 3]:
                if niveau == 1:
                    niveau_type = 'RESPONSABLE'
                    employes_niveau = destinataires_par_niveau['RESPONSABLE']
                elif niveau == 2:
                    niveau_type = 'DIRECTEUR'
                    employes_niveau = destinataires_par_niveau['DIRECTEUR']
                else:
                    niveau_type = random.choice(['RH', 'ADMIN'])
                    employes_niveau = destinataires_par_niveau[niveau_type]
                
                if not employes_niveau:
                    continue
                
                template = templates_hierarchiques['DEMANDE_A_VALIDER'].get(niveau_type)
                if not template:
                    continue
                
                destinataire = random.choice(employes_niveau)
                
                metadata = {
                    'demande_id': demande.id,
                    'niveau_validation': niveau,
                    'type_validateur': niveau_type,
                    'urgence_demande': demande.urgence,
                    'workflow_etape': f'validation_niveau_{niveau}',
                    'hierarchie_corrigee': True,
                    'delai_max_heures': [24, 24, 12][niveau-1]
                }
                
                try:
                    NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=None,  # Notification système
                        demande=demande,
                        type_notification='DEMANDE_A_VALIDER',
                        urgence=template['urgence'],
                        titre=template['titre'],
                        message=template['message'],
                        url_action_principale=f"/interim/validation/{demande.id}/niveau/{niveau}/",
                        texte_action_principale=f"Valider niveau {niveau}",
                        url_action_secondaire=f"/interim/demande/{demande.id}/",
                        texte_action_secondaire="Voir détails",
                        metadata=metadata
                    )
                    created_count += 1
                    
                except Exception as e:
                    logger.error(f"Erreur notification validation hiérarchique: {e}")
            
            # 3. ✅ Notifications pour propositions selon la source hiérarchique
            for proposition in [p for p in propositions if p.demande_interim == demande][:3]:
                # Notifier selon le niveau de la source
                niveau_proposant = self._get_niveau_display_from_source(proposition.source_proposition)
                
                # Notifier les niveaux supérieurs
                niveaux_a_notifier = self._get_niveaux_superieurs(proposition.source_proposition)
                
                for niveau_notifie in niveaux_a_notifier:
                    employes_niveau = destinataires_par_niveau.get(niveau_notifie, [])
                    if not employes_niveau:
                        continue
                    
                    destinataire = random.choice(employes_niveau)
                    
                    template = templates_hierarchiques['PROPOSITION_CANDIDAT']['TOUS']
                    titre = template['titre'].format(niveau_proposant=niveau_proposant)
                    message = template['message'].format(niveau_proposant=niveau_proposant)
                    
                    metadata = {
                        'proposition_id': proposition.id,
                        'candidat_id': proposition.candidat_propose.id,
                        'source_proposition': proposition.source_proposition,
                        'niveau_proposant': niveau_proposant,
                        'niveau_destinataire': niveau_notifie,
                        'score_candidat': proposition.score_automatique or 0,
                        'workflow_etape': 'proposition_candidat',
                        'hierarchie_corrigee': True
                    }
                    
                    try:
                        NotificationInterim.objects.create(
                            destinataire=destinataire,
                            expediteur=proposition.proposant,
                            demande=demande,
                            proposition_liee=proposition,
                            type_notification='PROPOSITION_CANDIDAT',
                            urgence=template['urgence'],
                            titre=titre,
                            message=message,
                            url_action_principale=f"/interim/proposition/{proposition.id}/",
                            texte_action_principale="Évaluer",
                            metadata=metadata
                        )
                        created_count += 1
                        
                    except Exception as e:
                        logger.error(f"Erreur notification proposition hiérarchique: {e}")
        
        self._write(f"    ✅ {created_count} notifications avec hiérarchie corrigée créées")
        
        # Statistiques par niveau hiérarchique
        if created_count > 0:
            self._write("    🔔 Notifications créées par niveau hiérarchique:")
            self._write("      • CHEF_EQUIPE: Notifications d'équipe")
            self._write("      • RESPONSABLE: Validations niveau 1")
            self._write("      • DIRECTEUR: Validations niveau 2")
            self._write("      • RH/ADMIN: Validations finales")
            self._write("      • SUPERUSER: Notifications de supervision")
    
    def _create_test_workflow_complet_corrige(self):
        """
        ✅ Crée un workflow complet avec hiérarchie CORRIGÉE
        """
        WorkflowDemande = self.models['WorkflowDemande']
        WorkflowEtape = self.models['WorkflowEtape']
        demandes = self.created_objects.get('demandes_interim', [])
        
        if not demandes:
            self._write("⚠️ Pas de demandes pour créer le workflow complet corrigé")
            return
        
        created_count = 0
        etapes = list(WorkflowEtape.objects.filter(actif=True).order_by('ordre'))
        
        for demande in demandes:
            try:
                # Sélectionner une étape selon la hiérarchie
                etapes_possibles = [
                    ('PROPOSITION_CANDIDATS', 'Phase proposition'),
                    ('VALIDATION_RESPONSABLE', 'Validation niveau 1'),     # ✅ CORRIGÉ
                    ('VALIDATION_DIRECTEUR', 'Validation niveau 2'),       # ✅ CORRIGÉ
                    ('VALIDATION_RH_ADMIN', 'Validation finale'),          # ✅ CORRIGÉ
                    ('NOTIFICATION_CANDIDAT', 'Notification en cours')
                ]
                
                etape_type, etape_desc = random.choice(etapes_possibles)
                etape_actuelle = WorkflowEtape.objects.filter(type_etape=etape_type, actif=True).first()
                
                if not etape_actuelle:
                    etape_actuelle = etapes[0] if etapes else None
                
                if not etape_actuelle:
                    continue
                
                # ✅ Historique avec hiérarchie CORRIGÉE
                historique_actions = [
                    {
                        'date': (timezone.now() - timedelta(days=5)).isoformat(),
                        'utilisateur': {
                            'id': demande.demandeur.id,
                            'nom': demande.demandeur.nom_complet,
                            'type_profil': demande.demandeur.type_profil
                        },
                        'action': 'Création de la demande',
                        'commentaire': 'Demande créée avec workflow hiérarchique corrigé',
                        'etape': 'DEMANDE',
                        'metadata': {
                            'type': 'creation',
                            'hierarchie_version': 'corrigee',
                            'niveaux_validation_requis': 3
                        }
                    }
                ]
                
                # Ajouter des actions hiérarchiques selon l'étape
                if etape_type in ['VALIDATION_RESPONSABLE', 'VALIDATION_DIRECTEUR', 'VALIDATION_RH_ADMIN']:
                    # Actions de validation hiérarchiques
                    actions_hierarchiques = [
                        {
                            'date': (timezone.now() - timedelta(days=3)).isoformat(),
                            'utilisateur': {
                                'nom': 'Chef Équipe Test',
                                'type_profil': 'CHEF_EQUIPE'
                            },
                            'action': 'Proposition candidat',
                            'commentaire': 'Candidat proposé par chef d\'équipe',
                            'etape': 'PROPOSITION_CANDIDATS',
                            'metadata': {
                                'type': 'proposition',
                                'source_hierarchique': 'CHEF_EQUIPE',
                                'niveau_proposition': 0
                            }
                        }
                    ]
                    
                    if etape_type != 'VALIDATION_RESPONSABLE':
                        actions_hierarchiques.append({
                            'date': (timezone.now() - timedelta(days=2)).isoformat(),
                            'utilisateur': {
                                'nom': 'Responsable Test',
                                'type_profil': 'RESPONSABLE'
                            },
                            'action': 'Validation niveau 1 (Responsable)',      # ✅ CORRIGÉ
                            'commentaire': 'Validation responsable approuvée',
                            'etape': 'VALIDATION_RESPONSABLE',
                            'metadata': {
                                'type': 'validation',
                                'niveau_validation': 1,
                                'decision': 'APPROUVE',
                                'type_validateur': 'RESPONSABLE'
                            }
                        })
                    
                    if etape_type == 'VALIDATION_RH_ADMIN':
                        actions_hierarchiques.append({
                            'date': (timezone.now() - timedelta(days=1)).isoformat(),
                            'utilisateur': {
                                'nom': 'Directeur Test',
                                'type_profil': 'DIRECTEUR'
                            },
                            'action': 'Validation niveau 2 (Directeur)',        # ✅ CORRIGÉ
                            'commentaire': 'Validation directeur approuvée',
                            'etape': 'VALIDATION_DIRECTEUR',
                            'metadata': {
                                'type': 'validation',
                                'niveau_validation': 2,
                                'decision': 'APPROUVE',
                                'type_validateur': 'DIRECTEUR'
                            }
                        })
                    
                    historique_actions.extend(actions_hierarchiques)
                
                workflow = WorkflowDemande.objects.create(
                    demande=demande,
                    etape_actuelle=etape_actuelle,
                    nb_propositions_recues=random.randint(2, 6),
                    nb_candidats_evalues=random.randint(1, 4),
                    nb_niveaux_validation_passes=random.randint(0, 3),
                    historique_actions=historique_actions
                )
                
                created_count += 1
                self._update_stats('WorkflowDemande', True)
                
            except Exception as e:
                logger.error(f"Erreur création workflow complet corrigé: {e}")
        
        self._write(f"    ✅ {created_count} workflows complets avec hiérarchie corrigée créés")
        
        if created_count > 0:
            self._write("    🔄 Workflow avec hiérarchie corrigée:")
            self._write("      • Niveau 1: RESPONSABLE (validation opérationnelle)")
            self._write("      • Niveau 2: DIRECTEUR (validation stratégique)")
            self._write("      • Niveau 3: RH/ADMIN (validation finale)")
            self._write("      • CHEF_EQUIPE: Propositions uniquement")
            self._write("      • SUPERUSER: Droits complets automatiques")
    
    def _create_test_historique_actions_corrected(self):
        """
        ✅ Crée un historique détaillé avec informations hiérarchiques CORRIGÉES
        """
        HistoriqueAction = self.models['HistoriqueAction']
        demandes = self.created_objects.get('demandes_interim', [])
        propositions = self.created_objects.get('propositions', [])
        validations = self.created_objects.get('validations', [])
        
        if not demandes:
            self._write("⚠️ Pas de demandes pour créer l'historique corrigé")
            return
        
        created_count = 0
        
        # Actions pour les demandes avec informations hiérarchiques
        for demande in demandes:
            try:
                # Action de création avec contexte hiérarchique
                HistoriqueAction.objects.create(
                    demande=demande,
                    action='CREATION_DEMANDE',
                    utilisateur=demande.demandeur,
                    description=f"Création de la demande {demande.numero_demande} avec workflow hiérarchique corrigé",
                    niveau_hierarchique=demande.demandeur.type_profil,       # ✅ Nouveau champ
                    is_superuser=demande.demandeur.is_superuser,             # ✅ Nouveau champ
                    donnees_apres={
                        'poste_titre': demande.poste.titre if demande.poste else 'Non défini',
                        'urgence': demande.urgence,
                        'date_debut': str(demande.date_debut) if demande.date_debut else None,
                        'workflow_version': 'hierarchie_corrigee',
                        'niveaux_validation_requis': demande.niveaux_validation_requis,
                        'demandeur_niveau': demande.demandeur.type_profil
                    }
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique demande corrigé: {e}")
        
        # Actions pour les propositions avec niveau hiérarchique
        for proposition in propositions:
            try:
                # ✅ Action CORRIGÉE selon la hiérarchie
                action_mapping = {
                    'CHEF_EQUIPE': 'PROPOSITION_CANDIDAT',
                    'RESPONSABLE': 'PROPOSITION_CANDIDAT',
                    'DIRECTEUR': 'PROPOSITION_CANDIDAT',
                    'RH': 'PROPOSITION_CANDIDAT',
                    'ADMIN': 'PROPOSITION_CANDIDAT'
                }
                
                action = action_mapping.get(proposition.proposant.type_profil, 'PROPOSITION_CANDIDAT')
                
                HistoriqueAction.objects.create(
                    demande=proposition.demande_interim,
                    proposition=proposition,
                    action=action,
                    utilisateur=proposition.proposant,
                    description=f"Proposition hiérarchique de {proposition.candidat_propose.nom_complet} par {proposition.proposant.type_profil}",
                    niveau_hierarchique=proposition.proposant.type_profil,   # ✅ Niveau du proposant
                    is_superuser=proposition.proposant.is_superuser,         # ✅ Status superuser
                    donnees_apres={
                        'candidat_nom': proposition.candidat_propose.nom_complet,
                        'source_proposition': proposition.source_proposition,
                        'justification': proposition.justification[:100],
                        'bonus_hierarchique': self._get_bonus_hierarchique_corrige_from_source(proposition.source_proposition),
                        'niveau_validation_propose': proposition.niveau_validation_propose,
                        'workflow_version': 'hierarchie_corrigee'
                    }
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique proposition corrigé: {e}")
        
        # Actions pour les validations avec hiérarchie corrigée
        for validation in validations:
            try:
                # ✅ Actions de validation CORRIGÉES
                action_mapping = {
                    'RESPONSABLE': 'VALIDATION_RESPONSABLE',     # ✅ CORRIGÉ
                    'DIRECTEUR': 'VALIDATION_DIRECTEUR',         # ✅ CORRIGÉ
                    'RH': 'VALIDATION_RH',                       # ✅ CORRIGÉ
                    'ADMIN': 'VALIDATION_ADMIN'                 # ✅ CORRIGÉ
                }
                
                action = action_mapping.get(validation.type_validation, 'VALIDATION_RESPONSABLE')
                
                HistoriqueAction.objects.create(
                    demande=validation.demande,
                    validation=validation,
                    action=action,
                    utilisateur=validation.validateur,
                    description=f"Validation hiérarchique {validation.type_validation} niveau {validation.niveau_validation}: {validation.decision}",
                    niveau_validation=validation.niveau_validation,
                    niveau_hierarchique=validation.validateur.type_profil,   # ✅ Niveau du validateur
                    is_superuser=validation.validateur.is_superuser,         # ✅ Status superuser
                    donnees_apres={
                        'decision': validation.decision,
                        'commentaire': validation.commentaire,
                        'nb_candidats_retenus': len(validation.candidats_retenus),
                        'type_validation': validation.type_validation,
                        'niveau_validation': validation.niveau_validation,
                        'workflow_version': 'hierarchie_corrigee',
                        'validateur_niveau': validation.validateur.type_profil
                    }
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique validation corrigé: {e}")
        
        self._write(f"    ✅ {created_count} actions d'historique avec hiérarchie corrigée créées")
        
        if created_count > 0:
            self._write("    📚 Historique avec informations hiérarchiques:")
            self._write("      • Niveau hiérarchique de chaque acteur")
            self._write("      • Status superutilisateur")
            self._write("      • Actions typées selon la hiérarchie")
            self._write("      • Métadonnées de workflow corrigées")
        
        self._update_stats('HistoriqueAction', True, count=created_count)
    
    def _create_test_notifications_metadata_corrigees(self):
        """
        ✅ Crée des notifications avec métadonnées hiérarchiques CORRIGÉES
        """
        NotificationInterim = self.models['NotificationInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        employes = self.created_objects.get('employes', [])
        
        if not demandes or not employes:
            self._write("⚠️ Pas de données pour créer notifications avec métadonnées corrigées")
            return
        
        created_count = 0
        
        # ✅ Scénarios avec métadonnées hiérarchiques CORRIGÉES
        scenarios_metadata = [
            {
                'type': 'DEMANDE_A_VALIDER',
                'titre': 'Validation hiérarchique requise - Analytics intégrés',
                'metadata_template': {
                    'hierarchie_corrigee': {
                        'niveau_validation_requis': 'RESPONSABLE',  # ✅ Niveau 1
                        'niveau_suivant': 'DIRECTEUR',              # ✅ Niveau 2
                        'niveau_final': 'RH_ADMIN',                 # ✅ Niveau 3
                        'progression_actuelle': 'NIVEAU_1',
                        'etapes_restantes': 2,
                        'validateurs_disponibles': {
                            'RESPONSABLE': ['Marie Diabaté'],
                            'DIRECTEUR': ['Kouadio Kouame'],
                            'RH': ['Sarah Konan'],
                            'ADMIN': ['Admin Test']
                        }
                    },
                    'analytics_validation': {
                        'temps_moyen_validation_n1_heures': 6,
                        'temps_moyen_validation_n2_heures': 4,
                        'temps_moyen_validation_n3_heures': 2,
                        'taux_approbation_par_niveau': {
                            'RESPONSABLE': 85,
                            'DIRECTEUR': 92,
                            'RH_ADMIN': 96
                        },
                        'facteurs_risque': []
                    },
                    'recommandations_ia': {
                        'action_immediate': 'CONTACTER_RESPONSABLE',
                        'validateur_optimal': 'Marie Diabaté (RESPONSABLE)',
                        'probabilite_approbation': 87,
                        'delai_estime_total_heures': 12,
                        'alternatives': ['ESCALADE_DIRECTE', 'VALIDATION_URGENCE']
                    }
                }
            },
            {
                'type': 'PROPOSITION_CANDIDAT',
                'titre': 'Proposition avec scoring hiérarchique avancé',
                'metadata_template': {
                    'scoring_hierarchique': {
                        'bonus_base_source': 0,              # Sera calculé dynamiquement
                        'coefficient_niveau': 1.0,           # Sera ajusté selon le niveau
                        'comparaison_sources': {
                            'CHEF_EQUIPE': {'bonus': 8, 'fiabilite': 75},
                            'RESPONSABLE': {'bonus': 15, 'fiabilite': 85},    # ✅ CORRIGÉ
                            'DIRECTEUR': {'bonus': 18, 'fiabilite': 90},      # ✅ CORRIGÉ
                            'RH': {'bonus': 20, 'fiabilite': 95},             # ✅ CORRIGÉ
                            'ADMIN': {'bonus': 20, 'fiabilite': 95}           # ✅ CORRIGÉ
                        },
                        'impact_decision': {
                            'influence_validation_n1': 'FORTE',
                            'influence_validation_n2': 'MOYENNE',
                            'influence_validation_finale': 'FAIBLE'
                        }
                    },
                    'prediction_workflow': {
                        'probabilite_validation_globale': 78,
                        'niveau_risque_refus': 'FAIBLE',
                        'facteurs_positifs': ['BONUS_HIERARCHIQUE', 'EXPERIENCE'],
                        'facteurs_negatifs': ['DISPONIBILITE_PARTIELLE'],
                        'delai_estime_workflow_heures': 36
                    }
                }
            },
            {
                'type': 'RETARD_WORKFLOW',
                'titre': 'Diagnostic hiérarchique automatique',
                'metadata_template': {
                    'diagnostic_hierarchique': {
                        'niveau_bloque': 'RESPONSABLE',         # ✅ Niveau 1
                        'validateur_responsable': 'Marie Diabaté',
                        'duree_blocage_heures': 18,
                        'sla_niveau_depassement': 150,         # 150% du SLA
                        'impact_niveaux_suivants': {
                            'DIRECTEUR': 'RETARD_PREVU_6H',
                            'RH_ADMIN': 'RETARD_PREVU_12H'
                        },
                        'causes_probables': [
                            'ABSENCE_VALIDATEUR',
                            'SURCHARGE_VALIDATION',
                            'COMPLEXITE_DOSSIER'
                        ]
                    },
                    'resolution_automatique': {
                        'actions_prises': [
                            'RAPPEL_AUTOMATIQUE_ENVOYE',
                            'NOTIFICATION_MANAGER',
                            'ESCALADE_NIVEAU_SUPERIEUR_PROGRAMMEE'
                        ],
                        'alternatives_disponibles': {
                            'DELEGATION_INTERNE': 'Autre responsable du département',
                            'ESCALADE_DIRECTE': 'Validation directeur exceptionnelle',
                            'VALIDATION_URGENCE': 'Processus d\'urgence activé'
                        },
                        'delai_escalade_automatique_heures': 4
                    },
                    'impact_business': {
                        'cout_retard_par_heure': 8500,         # FCFA
                        'services_affectes': ['PRODUCTION', 'COMMERCIAL'],
                        'criticite_mission': 'MOYENNE',
                        'impact_client': 'FAIBLE'
                    }
                }
            }
        ]
        
        for i, demande in enumerate(demandes[:6]):
            scenario = scenarios_metadata[i % len(scenarios_metadata)]
            
            # Sélectionner un destinataire selon la hiérarchie
            niveau_destinataire = ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'][i % 4]
            destinataires_possibles = [emp for emp in employes if emp.type_profil == niveau_destinataire]
            
            if not destinataires_possibles:
                continue
            
            destinataire = random.choice(destinataires_possibles)
            
            # ✅ Personnaliser les métadonnées avec la hiérarchie CORRIGÉE
            metadata = scenario['metadata_template'].copy()
            
            # Ajouter le contexte hiérarchique spécifique
            metadata['context_hierarchique'] = {
                'demande_id': demande.id,
                'destinataire_niveau': destinataire.type_profil,
                'destinataire_is_superuser': destinataire.is_superuser,
                'workflow_version': 'hierarchie_corrigee_v2',
                'niveaux_validation': {
                    'niveau_1': 'RESPONSABLE',
                    'niveau_2': 'DIRECTEUR', 
                    'niveau_3': 'RH_ADMIN'
                },
                'permissions_destinataire': {
                    'peut_proposer': destinataire.peut_proposer_candidat(demande)[0] if hasattr(destinataire, 'peut_proposer_candidat') else False,
                    'peut_valider_niveau_1': destinataire.type_profil in ['RESPONSABLE', 'RH', 'ADMIN'] or destinataire.is_superuser,
                    'peut_valider_niveau_2': destinataire.type_profil in ['DIRECTEUR', 'RH', 'ADMIN'] or destinataire.is_superuser,
                    'peut_valider_final': destinataire.type_profil in ['RH', 'ADMIN'] or destinataire.is_superuser,
                    'niveau_max_validation': destinataire.get_niveau_validation_max() if hasattr(destinataire, 'get_niveau_validation_max') else 0
                }
            }
            
            # Ajuster le scoring si c'est une proposition
            if scenario['type'] == 'PROPOSITION_CANDIDAT':
                metadata['scoring_hierarchique']['bonus_base_source'] = self._get_bonus_hierarchique_corrige(destinataire.type_profil)
                metadata['scoring_hierarchique']['coefficient_niveau'] = [1.0, 1.2, 1.4, 1.6, 1.8][['UTILISATEUR', 'CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH'].index(destinataire.type_profil) if destinataire.type_profil in ['UTILISATEUR', 'CHEF_EQUIPE', 'RESPONSABLE', 'DIRECTEUR', 'RH'] else 0]
            
            # Tracking et audit
            metadata['tracking_corrige'] = {
                'notification_id': f'NOTIF_HIER_{timezone.now().strftime("%Y%m%d_%H%M%S")}_{i}',
                'hierarchie_version': 'V2_CORRIGEE',
                'generation_timestamp': timezone.now().isoformat(),
                'algorithme_scoring': 'HIERARCHIQUE_CORRIGE_V2',
                'tags': ['hierarchie_corrigee', 'metadata_avancee', 'analytics_integres']
            }
            
            try:
                notification = NotificationInterim.objects.create(
                    destinataire=destinataire,
                    expediteur=random.choice(employes) if random.choice([True, False]) else None,
                    demande=demande,
                    type_notification=scenario['type'],
                    urgence='CRITIQUE',
                    statut='NON_LUE',
                    titre=scenario['titre'],
                    message=f"Notification avec métadonnées hiérarchiques corrigées pour {demande.numero_demande}. "
                            f"Niveau destinataire: {destinataire.type_profil}. "
                            f"Consultez les métadonnées pour le contexte hiérarchique complet.",
                    url_action_principale=f"/interim/demande/{demande.id}/hierarchique/",
                    texte_action_principale="Action hiérarchique",
                    url_action_secondaire=f"/interim/metadata/{demande.id}/hierarchie/",
                    texte_action_secondaire="Voir hiérarchie",
                    metadata=metadata
                )
                
                created_count += 1
                self._update_stats('NotificationInterim', True)
                
            except Exception as e:
                logger.error(f"Erreur notification avec métadonnées hiérarchiques corrigées: {e}")
        
        self._write(f"    ✅ {created_count} notifications avec métadonnées hiérarchiques corrigées créées")
        
        if created_count > 0:
            self._write("    🎯 Métadonnées hiérarchiques corrigées intégrées:")
            self._write("      • Analytics de validation par niveau (RESPONSABLE → DIRECTEUR → RH/ADMIN)")
            self._write("      • Scoring hiérarchique avec bonus corrigés")
            self._write("      • Diagnostic automatique des blocages par niveau")
            self._write("      • Permissions granulaires selon le type de profil")
            self._write("      • Prédictions de workflow avec hiérarchie")
            self._write("      • Escalade automatique intelligente")
    
    def _create_test_comparaisons_scoring_corrigees(self):
        """
        ✅ Crée des comparaisons de scoring avec bonus hiérarchiques CORRIGÉS
        """
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        PropositionCandidat = self.models['PropositionCandidat']
        
        propositions = self.created_objects.get('propositions', [])
        configurations = self.created_objects.get('configurations_scoring', [])
        
        if not propositions or not configurations:
            self._write("⚠️ Pas de données pour créer les comparaisons de scoring corrigées")
            return
        
        created_count = 0
        
        # Prendre quelques propositions et créer des scores avec différentes configs
        for proposition in propositions[:8]:
            for config in configurations:
                try:
                    # Simuler le même candidat évalué avec différentes configurations
                    base_scores = {
                        'similarite': random.randint(60, 85),
                        'competences': random.randint(55, 80),
                        'experience': random.randint(45, 75),
                        'disponibilite': random.randint(80, 95),
                        'proximite': random.randint(40, 70),
                        'anciennete': random.randint(30, 60)
                    }
                    
                    # Calculer le score pondéré selon la configuration
                    poids = config.get_poids_dict()
                    score_pondere = sum(
                        base_scores[critere] * poids_val 
                        for critere, poids_val in poids.items() 
                        if critere in base_scores
                    )
                    
                    # ✅ Ajouter les bonus hiérarchiques CORRIGÉS selon la configuration
                    bonus_dict = config.get_bonus_dict()
                    bonus_total = config.bonus_proposition_humaine
                    
                    # Bonus selon la source hiérarchique
                    source_bonus_mapping = {
                        'MANAGER_DIRECT': bonus_dict.get('manager_direct', 12),
                        'CHEF_EQUIPE': bonus_dict.get('chef_equipe', 8),
                        'RESPONSABLE': bonus_dict.get('responsable', 15),        # ✅ CORRIGÉ
                        'DIRECTEUR': bonus_dict.get('directeur', 18),            # ✅ CORRIGÉ
                        'RH': bonus_dict.get('rh', 20),                          # ✅ CORRIGÉ
                        'ADMIN': bonus_dict.get('admin', 20),                    # ✅ CORRIGÉ
                        'SUPERUSER': bonus_dict.get('superuser', 0)              # ✅ Pas de bonus spécifique
                    }
                    
                    bonus_hierarchique = source_bonus_mapping.get(proposition.source_proposition, 5)
                    bonus_total += bonus_hierarchique
                    
                    # Bonus d'expérience et recommandation
                    if base_scores['experience'] > 70:
                        bonus_total += bonus_dict.get('experience_similaire', 8)
                    if proposition.justification:
                        bonus_total += bonus_dict.get('recommandation', 10)
                    
                    score_final = min(100, int(score_pondere + bonus_total))
                    
                    # Créer un score détaillé unique avec suffixe de config
                    calcule_par = f'CONFIG_{config.nom.replace(" ", "_").upper()}'[:20]
                    
                    score_detail = ScoreDetailCandidat.objects.create(
                        candidat=proposition.candidat_propose,
                        demande_interim=proposition.demande_interim,
                        proposition_humaine=proposition,
                        score_similarite_poste=base_scores['similarite'],
                        score_competences=base_scores['competences'],
                        score_experience=base_scores['experience'],
                        score_disponibilite=base_scores['disponibilite'],
                        score_proximite=base_scores['proximite'],
                        score_anciennete=base_scores['anciennete'],
                        bonus_proposition_humaine=bonus_total,
                        bonus_hierarchique=bonus_hierarchique,           # ✅ Nouveau champ
                        score_total=score_final,
                        calcule_par=calcule_par
                    )
                    
                    created_count += 1
                    self._update_stats('ScoreDetailCandidat', True)
                    
                except Exception as e:
                    logger.error(f"Erreur comparaison scoring corrigée: {e}")
        
        self._write(f"    ✅ {created_count} scores de comparaison avec hiérarchie corrigée créés")
        
        if created_count > 0:
            self._write("    📈 Configurations de scoring hiérarchiques disponibles:")
            for config in configurations:
                bonus_dict = config.get_bonus_dict()
                self._write(f"      • {config.nom}:")
                self._write(f"        - Similarité: {config.poids_similarite_poste*100:.0f}%, "
                          f"Compétences: {config.poids_competences*100:.0f}%")
                self._write(f"        - Bonus RESPONSABLE: +{bonus_dict.get('responsable', 15)} pts")
                self._write(f"        - Bonus DIRECTEUR: +{bonus_dict.get('directeur', 18)} pts")
                self._write(f"        - Bonus RH/ADMIN: +{bonus_dict.get('rh', 20)}/{bonus_dict.get('admin', 20)} pts")
    
    # ================================================================
    # MÉTHODES UTILITAIRES POUR LA HIÉRARCHIE CORRIGÉE
    # ================================================================
    
    def _get_bonus_hierarchique_corrige(self, type_profil):
        """
        ✅ Retourne le bonus hiérarchique selon le type de profil CORRIGÉ
        """
        bonus_map = {
            'CHEF_EQUIPE': 8,
            'RESPONSABLE': 15,       # ✅ Niveau 1 validation
            'DIRECTEUR': 18,         # ✅ Niveau 2 validation
            'RH': 20,                # ✅ Niveau 3 validation
            'ADMIN': 20,             # ✅ Niveau 3 étendu
            'UTILISATEUR': 0         # Pas de bonus
        }
        return bonus_map.get(type_profil, 5)
    
    def _get_bonus_hierarchique_corrige_from_source(self, source_proposition):
        """
        ✅ Retourne le bonus hiérarchique selon la source de proposition CORRIGÉE
        """
        bonus_map = {
            'MANAGER_DIRECT': 12,
            'CHEF_EQUIPE': 8,
            'RESPONSABLE': 15,       # ✅ CORRIGÉ
            'DIRECTEUR': 18,         # ✅ CORRIGÉ
            'RH': 20,                # ✅ CORRIGÉ
            'ADMIN': 20,             # ✅ CORRIGÉ
            'SUPERUSER': 0,          # Pas de bonus spécifique (droits complets)
            'AUTRE': 3
        }
        return bonus_map.get(source_proposition, 5)
    
    def _get_niveau_validation_pour_type(self, type_profil):
        """
        ✅ Retourne le niveau de validation selon le type de profil CORRIGÉ
        """
        niveau_map = {
            'UTILISATEUR': 0,        # Pas de validation
            'CHEF_EQUIPE': 0,        # Peut proposer, ne valide pas
            'RESPONSABLE': 1,        # ✅ Niveau 1 validation
            'DIRECTEUR': 2,          # ✅ Niveau 2 validation
            'RH': 3,                 # ✅ Niveau 3 validation finale
            'ADMIN': 3               # ✅ Niveau 3 étendu
        }
        return niveau_map.get(type_profil, 0)
    
    def _get_niveau_display_from_source(self, source_proposition):
        """
        ✅ Retourne l'affichage du niveau selon la source CORRIGÉE
        """
        display_map = {
            'MANAGER_DIRECT': 'Manager direct',
            'CHEF_EQUIPE': 'Chef d\'équipe',
            'RESPONSABLE': 'Responsable (N+1)',      # ✅ CORRIGÉ
            'DIRECTEUR': 'Directeur (N+2)',          # ✅ CORRIGÉ
            'RH': 'RH (Final)',                      # ✅ CORRIGÉ
            'ADMIN': 'Admin (Final)',                # ✅ CORRIGÉ
            'SUPERUSER': 'Superutilisateur',
            'AUTRE': 'Autre'
        }
        return display_map.get(source_proposition, 'Non défini')
    
    def _get_niveaux_superieurs(self, source_proposition):
        """
        ✅ Retourne les niveaux hiérarchiques supérieurs à notifier CORRIGÉS
        """
        hierarchie_map = {
            'CHEF_EQUIPE': ['RESPONSABLE', 'DIRECTEUR', 'RH', 'ADMIN'],
            'RESPONSABLE': ['DIRECTEUR', 'RH', 'ADMIN'],                # ✅ CORRIGÉ
            'DIRECTEUR': ['RH', 'ADMIN'],                               # ✅ CORRIGÉ
            'RH': ['ADMIN'],                                            # ✅ CORRIGÉ
            'ADMIN': [],                                                # ✅ Niveau le plus élevé
            'SUPERUSER': []                                             # ✅ Droits complets
        }
        return hierarchie_map.get(source_proposition, [])
    
    # ================================================================
    # MÉTHODES HÉRITÉES ET ADAPTÉES (inchangées)
    # ================================================================
    
    def _migrate_employes_corrected(self):
        """Migration des employés avec hiérarchie corrigée"""
        self._create_test_employes_corrected()
    
    def _migrate_propositions_candidats_corrected(self):
        """Migration des propositions avec hiérarchie corrigée"""
        self._create_test_propositions_hierarchiques()
    
    def _migrate_scores_detailles_corrected(self):
        """Migration des scores avec bonus hiérarchiques corrigés"""
        self._create_test_scores_bonus_hierarchiques()
    
    def _migrate_validations_corrected(self):
        """Migration des validations avec hiérarchie corrigée"""
        self._create_test_validations_hierarchiques()
    
    def _migrate_notifications_corrected(self):
        """Migration des notifications avec hiérarchie corrigée"""
        self._create_test_notifications_hierarchiques()
    
    def _migrate_historique_actions_corrected(self):
        """Migration de l'historique avec hiérarchie corrigée"""
        self._create_test_historique_actions_corrected()
    
    # ================================================================
    # MÉTHODES DE BASE INCHANGÉES
    # ================================================================
    
    def _migrate_structure_only(self):
        """Migration de la structure organisationnelle"""
        steps = [
            ("Départements", self._create_test_departements),
            ("Sites", self._create_test_sites),
            ("Postes", self._create_test_postes),
            ("Motifs d'absence", self._create_test_motifs_absence),
            ("Compétences", self._create_test_competences)
        ]
        
        for step_name, step_function in steps:
            try:
                step_function()
            except Exception as e:
                logger.error(f"Erreur {step_name}: {e}")
    
    def _migrate_employees_only(self):
        """Migration des employés uniquement"""
        steps = [
            ("Employés", self._create_test_employes_corrected),
            ("Formations", self._create_test_formations),
            ("Absences", self._create_test_absences),
            ("Disponibilités", self._create_test_disponibilites)
        ]
        
        for step_name, step_function in steps:
            try:
                step_function()
            except Exception as e:
                logger.error(f"Erreur {step_name}: {e}")
    
    def _migrate_interim_data(self):
        """Migration des données d'intérim"""
        steps = [
            ("Demandes intérim", self._create_test_demandes_interim),
            ("Disponibilités", self._create_test_disponibilites)
        ]
        
        for step_name, step_function in steps:
            try:
                step_function()
            except Exception as e:
                logger.error(f"Erreur {step_name}: {e}")
    
    def _create_demandes_with_workflow_corrected(self):
        """Crée des demandes d'intérim avec workflow corrigé"""
        DemandeInterim = self.models['DemandeInterim']
        WorkflowDemande = self.models['WorkflowDemande']
        WorkflowEtape = self.models['WorkflowEtape']
        
        employes = self.created_objects.get('employes', [])
        postes = self.created_objects.get('postes', [])
        motifs = self.created_objects.get('motifs_absence', [])
        
        if not all([employes, postes, motifs]):
            self._write("⚠️ Données manquantes pour créer demandes avec workflow corrigé")
            return
        
        created_count = 0
        
        # ✅ Scénarios workflow avec hiérarchie CORRIGÉE
        scenarios_workflow_corriges = [
            {
                'nombre': 3,
                'statut': 'SOUMISE',
                'etape': 'DEMANDE',
                'description': 'Demandes nouvellement créées'
            },
            {
                'nombre': 4,
                'statut': 'EN_PROPOSITION',
                'etape': 'PROPOSITION_CANDIDATS',
                'description': 'Demandes en phase de proposition'
            },
            {
                'nombre': 3,
                'statut': 'EN_VALIDATION',
                'etape': 'VALIDATION_RESPONSABLE',        # ✅ CORRIGÉ
                'description': 'Demandes en validation Responsable (N+1)'
            },
            {
                'nombre': 2,
                'statut': 'EN_VALIDATION',
                'etape': 'VALIDATION_DIRECTEUR',          # ✅ CORRIGÉ
                'description': 'Demandes en validation Directeur (N+2)'
            },
            {
                'nombre': 2,
                'statut': 'CANDIDAT_PROPOSE',
                'etape': 'VALIDATION_RH_ADMIN',           # ✅ CORRIGÉ
                'description': 'Demandes en validation finale RH/Admin'
            },
            {
                'nombre': 1,
                'statut': 'EN_COURS',
                'etape': 'ACCEPTATION_CANDIDAT',
                'description': 'Missions en cours'
            }
        ]
        
        for scenario in scenarios_workflow_corriges:
            for i in range(scenario['nombre']):
                try:
                    demandeur = random.choice(employes)
                    personne_remplacee = random.choice([emp for emp in employes if emp != demandeur])
                    poste = random.choice(postes)
                    motif = random.choice(motifs)
                    
                    # Dates logiques selon le scénario
                    if scenario['statut'] == 'EN_COURS':
                        date_debut = date.today() - timedelta(days=random.randint(0, 15))
                        date_fin = date_debut + timedelta(days=random.randint(10, 60))
                    else:
                        date_debut = date.today() + timedelta(days=random.randint(1, 30))
                        date_fin = date_debut + timedelta(days=random.randint(5, 45))
                    
                    urgence = random.choice(['NORMALE', 'MOYENNE', 'ELEVEE', 'CRITIQUE'])
                    
                    demande = DemandeInterim.objects.create(
                        demandeur=demandeur,
                        personne_remplacee=personne_remplacee,
                        poste=poste,
                        date_debut=date_debut,
                        date_fin=date_fin,
                        motif_absence=motif,
                        urgence=urgence,
                        description_poste=f"Remplacement de {personne_remplacee.nom_complet} au poste {poste.titre}",
                        instructions_particulieres=f"Mission {scenario['description'].lower()} avec hiérarchie corrigée",
                        competences_indispensables="Selon fiche de poste + hiérarchie de validation corrigée",
                        statut=scenario['statut'],
                        propositions_autorisees=True,
                        nb_max_propositions_par_utilisateur=3,
                        date_limite_propositions=timezone.now() + timedelta(days=2),
                        niveau_validation_actuel=random.randint(0, 2),
                        niveaux_validation_requis=3,  # ✅ 3 niveaux : RESPONSABLE → DIRECTEUR → RH/ADMIN
                        poids_scoring_automatique=0.7,
                        poids_scoring_humain=0.3
                    )
                    
                    # Créer le workflow associé avec hiérarchie corrigée
                    etape_workflow = WorkflowEtape.objects.filter(
                        type_etape=scenario['etape'],
                        actif=True
                    ).first()
                    
                    if etape_workflow:
                        workflow = WorkflowDemande.objects.create(
                            demande=demande,
                            etape_actuelle=etape_workflow,
                            nb_propositions_recues=random.randint(0, 5),
                            nb_candidats_evalues=random.randint(0, 3),
                            nb_niveaux_validation_passes=random.randint(0, 2),
                            historique_actions=[
                                {
                                    'date': (timezone.now() - timedelta(days=random.randint(1, 7))).isoformat(),
                                    'utilisateur': {
                                        'id': demandeur.id,
                                        'nom': demandeur.nom_complet,
                                        'type_profil': demandeur.type_profil
                                    },
                                    'action': 'Création demande avec hiérarchie corrigée',
                                    'commentaire': f'Demande créée en mode {scenario["description"]} avec workflow hiérarchique corrigé',
                                    'etape': etape_workflow.nom,
                                    'metadata': {
                                        'type': 'creation_workflow_corrige',
                                        'scenario': scenario['description'],
                                        'urgence': urgence,
                                        'hierarchie_version': 'RESPONSABLE_DIRECTEUR_RH_ADMIN',
                                        'niveaux_validation': 3
                                    }
                                }
                            ]
                        )
                    
                    created_count += 1
                    self.created_objects.setdefault('demandes_interim', []).append(demande)
                    self._update_stats('DemandeInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création demande workflow corrigé: {e}")
        
        self._write(f"    ✅ {created_count} demandes avec workflow hiérarchique corrigé créées")
        
        if created_count > 0:
            self._write("    🔄 Workflow hiérarchique corrigé appliqué:")
            for scenario in scenarios_workflow_corriges:
                self._write(f"      • {scenario['description']}: {scenario['nombre']} demande(s)")
    
    # ================================================================
    # MÉTHODES DE BASE HÉRITÉES (simplifiées)
    # ================================================================
    
    def _create_test_departements(self):
        """Crée des départements de test"""
        Departement = self.models['Departement']
        
        test_data = [
            {'nom': 'Ressources Humaines', 'code': 'RH', 'description': 'Gestion du personnel', 'kelio_department_key': 1, 'actif': True},
            {'nom': 'Informatique', 'code': 'IT', 'description': 'Développement informatique', 'kelio_department_key': 2, 'actif': True},
            {'nom': 'Comptabilité', 'code': 'COMPTA', 'description': 'Gestion financière', 'kelio_department_key': 3, 'actif': True},
            {'nom': 'Commercial', 'code': 'COM', 'description': 'Ventes et clients', 'kelio_department_key': 4, 'actif': True},
            {'nom': 'Direction', 'code': 'DIR', 'description': 'Direction générale', 'kelio_department_key': 5, 'actif': True},
            {'nom': 'Production', 'code': 'PROD', 'description': 'Production et opérations', 'kelio_department_key': 6, 'actif': True},
            {'nom': 'Logistique', 'code': 'LOG', 'description': 'Transport et logistique', 'kelio_department_key': 7, 'actif': True}
        ]
        
        created_count = 0
        for data in test_data:
            dept, created = Departement.objects.get_or_create(code=data['code'], defaults=data)
            if created:
                created_count += 1
                self.created_objects['departements'].append(dept)
            self._update_stats('Departement', created)
            
        self._write(f"    ✅ {created_count} départements créés")
    
    def _create_test_sites(self):
        """Crée des sites de test"""
        Site = self.models['Site']
        
        test_data = [
            {'nom': 'Siège Social Abidjan', 'adresse': 'Avenue Chardy, Plateau', 'ville': 'Abidjan', 'code_postal': '01000', 'kelio_site_key': 1, 'actif': True},
            {'nom': 'Agence Bouaké', 'adresse': 'Boulevard de la Paix', 'ville': 'Bouaké', 'code_postal': '01000', 'kelio_site_key': 2, 'actif': True},
            {'nom': 'Antenne Yamoussoukro', 'adresse': 'Avenue Houphouët-Boigny', 'ville': 'Yamoussoukro', 'code_postal': '01000', 'kelio_site_key': 3, 'actif': True},
            {'nom': 'Bureau San Pedro', 'adresse': 'Zone Industrielle', 'ville': 'San Pedro', 'code_postal': '28000', 'kelio_site_key': 4, 'actif': True},
            {'nom': 'Agence Korhogo', 'adresse': 'Avenue de l\'Indépendance', 'ville': 'Korhogo', 'code_postal': '36000', 'kelio_site_key': 5, 'actif': True}
        ]
        
        created_count = 0
        for data in test_data:
            site, created = Site.objects.get_or_create(nom=data['nom'], defaults=data)
            if created:
                created_count += 1
                self.created_objects['sites'].append(site)
            self._update_stats('Site', created)
            
        self._write(f"    ✅ {created_count} sites créés")
    
    def _create_test_postes(self):
        """Crée des postes de test"""
        Poste = self.models['Poste']
        departements = self.created_objects.get('departements', [])
        sites = self.created_objects.get('sites', [])
        
        if not departements or not sites:
            self._write("⚠️ Départements ou sites manquants")
            return
        
        # Sélectionner quelques départements et sites
        dept_it = next((d for d in departements if d.code == 'IT'), departements[0])
        dept_rh = next((d for d in departements if d.code == 'RH'), departements[0])
        site_abidjan = sites[0] if sites else None
        site_bouake = sites[1] if len(sites) > 1 else sites[0]
        
        test_data = [
            {'titre': 'Développeur Full Stack', 'departement': dept_it, 'site': site_abidjan, 'interim_autorise': True, 'kelio_job_key': 1},
            {'titre': 'Chef de Projet IT', 'departement': dept_it, 'site': site_abidjan, 'interim_autorise': True, 'kelio_job_key': 2},
            {'titre': 'Chargé de Recrutement', 'departement': dept_rh, 'site': site_abidjan, 'interim_autorise': True, 'kelio_job_key': 3},
            {'titre': 'Technicien Support', 'departement': dept_it, 'site': site_bouake, 'interim_autorise': True, 'kelio_job_key': 4},
            {'titre': 'Analyste RH', 'departement': dept_rh, 'site': site_abidjan, 'interim_autorise': True, 'kelio_job_key': 5},
            {'titre': 'Assistant Direction', 'departement': departements[0], 'site': site_abidjan, 'interim_autorise': True, 'kelio_job_key': 6}
        ]
        
        created_count = 0
        for data in test_data:
            poste_data = {
                'titre': data['titre'],
                'description': f"Poste de {data['titre']} avec workflow hiérarchique corrigé",
                'departement': data['departement'],
                'site': data['site'],
                'interim_autorise': data['interim_autorise'],
                'kelio_job_key': data['kelio_job_key'],
                'actif': True
            }
            poste, created = Poste.objects.get_or_create(
                titre=data['titre'],
                site=data['site'],
                defaults=poste_data
            )
            if created:
                created_count += 1
                self.created_objects['postes'].append(poste)
            self._update_stats('Poste', created)
            
        self._write(f"    ✅ {created_count} postes créés")
    
    def _create_test_motifs_absence(self):
        """Crée des motifs d'absence de test"""
        MotifAbsence = self.models['MotifAbsence']
        
        test_data = [
            {'nom': 'Congé payé', 'code': 'CP', 'categorie': 'CONGE', 'couleur': '#28a745', 'kelio_absence_type_key': 1, 'actif': True},
            {'nom': 'Arrêt maladie', 'code': 'AM', 'categorie': 'MALADIE', 'couleur': '#dc3545', 'kelio_absence_type_key': 2, 'actif': True},
            {'nom': 'Formation', 'code': 'FORM', 'categorie': 'FORMATION', 'couleur': '#17a2b8', 'kelio_absence_type_key': 3, 'actif': True},
            {'nom': 'RTT', 'code': 'RTT', 'categorie': 'CONGE', 'couleur': '#20c997', 'kelio_absence_type_key': 4, 'actif': True},
            {'nom': 'Congé maternité', 'code': 'CM', 'categorie': 'CONGE', 'couleur': '#ffc107', 'kelio_absence_type_key': 5, 'actif': True},
            {'nom': 'Mission externe', 'code': 'MISS', 'categorie': 'PROFESSIONNEL', 'couleur': '#6f42c1', 'kelio_absence_type_key': 6, 'actif': True}
        ]
        
        created_count = 0
        for data in test_data:
            motif_data = {**data, 'description': f"Motif: {data['nom']}"}
            motif, created = MotifAbsence.objects.get_or_create(code=data['code'], defaults=motif_data)
            if created:
                created_count += 1
                self.created_objects['motifs_absence'].append(motif)
            self._update_stats('MotifAbsence', created)
            
        self._write(f"    ✅ {created_count} motifs d'absence créés")
    
    def _create_test_competences(self):
        """Crée des compétences de test"""
        Competence = self.models['Competence']
        
        test_data = [
            {'nom': 'Python', 'categorie': 'Programmation', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 1, 'actif': True},
            {'nom': 'Django', 'categorie': 'Frameworks Web', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 2, 'actif': True},
            {'nom': 'Management d\'équipe', 'categorie': 'Management', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 3, 'actif': True},
            {'nom': 'Anglais', 'categorie': 'Langues', 'type_competence': 'LINGUISTIQUE', 'kelio_skill_key': 4, 'actif': True},
            {'nom': 'Excel', 'categorie': 'Bureautique', 'type_competence': 'LOGICIEL', 'kelio_skill_key': 5, 'actif': True},
            {'nom': 'Gestion de projet', 'categorie': 'Management', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 6, 'actif': True},
            {'nom': 'Communication', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 7, 'actif': True}
        ]
        
        created_count = 0
        for data in test_data:
            competence_data = {**data, 'description': f"Compétence: {data['nom']}"}
            competence, created = Competence.objects.get_or_create(nom=data['nom'], defaults=competence_data)
            if created:
                created_count += 1
                self.created_objects['competences'].append(competence)
            self._update_stats('Competence', created)
            
        self._write(f"    ✅ {created_count} compétences créées")
    
    def _create_test_demandes_interim(self):
        """Crée des demandes d'intérim de test"""
        DemandeInterim = self.models['DemandeInterim']
        employes = self.created_objects.get('employes', [])
        postes = self.created_objects.get('postes', [])
        motifs = self.created_objects.get('motifs_absence', [])
        
        if not all([employes, postes, motifs]):
            self._write("⚠️ Données manquantes pour créer les demandes d'intérim")
            return
        
        created_count = 0
        
        for i in range(min(15, self.sample_size // 3)):
            try:
                demandeur = random.choice(employes)
                personne_remplacee = random.choice([emp for emp in employes if emp != demandeur])
                poste = random.choice(postes)
                motif = random.choice(motifs)
                
                date_debut = date.today() + timedelta(days=random.randint(1, 60))
                date_fin = date_debut + timedelta(days=random.randint(5, 30))
                
                demande = DemandeInterim.objects.create(
                    demandeur=demandeur,
                    personne_remplacee=personne_remplacee,
                    poste=poste,
                    date_debut=date_debut,
                    date_fin=date_fin,
                    motif_absence=motif,
                    urgence=random.choice(['NORMALE', 'MOYENNE', 'ELEVEE', 'CRITIQUE']),
                    description_poste=f"Remplacement de {personne_remplacee.nom_complet} avec workflow hiérarchique corrigé",
                    instructions_particulieres="Mission avec validation hiérarchique RESPONSABLE → DIRECTEUR → RH/ADMIN",
                    competences_indispensables="Selon fiche de poste + adaptation workflow corrigé",
                    statut=random.choice(['SOUMISE', 'EN_VALIDATION', 'VALIDEE']),
                    propositions_autorisees=True,
                    nb_max_propositions_par_utilisateur=3,
                    niveaux_validation_requis=3,  # ✅ 3 niveaux selon hiérarchie corrigée
                    poids_scoring_automatique=0.7,
                    poids_scoring_humain=0.3
                )
                
                created_count += 1
                self.created_objects.setdefault('demandes_interim', []).append(demande)
                self._update_stats('DemandeInterim', True)
                
            except Exception as e:
                logger.error(f"Erreur demande intérim: {e}")
        
        self._write(f"    ✅ {created_count} demandes d'intérim avec hiérarchie corrigée créées")
    
    # Méthodes simplifiées pour les autres créations
    def _create_test_formations(self):
        """Formations simplifiées"""
        employes = self.created_objects.get('employes', [])
        if not employes: return
        
        FormationUtilisateur = self.models['FormationUtilisateur']
        created_count = 0
        
        for employe in employes[:10]:
            try:
                FormationUtilisateur.objects.create(
                    utilisateur=employe,
                    titre=f"Formation {random.choice(['Django', 'Management', 'Excel', 'Leadership'])}",
                    organisme="Institut Formation CI",
                    date_debut=date.today() - timedelta(days=random.randint(30, 365)),
                    duree_jours=random.randint(1, 5),
                    source_donnee='KELIO'
                )
                created_count += 1
                self._update_stats('FormationUtilisateur', True)
            except Exception as e:
                logger.error(f"Erreur formation: {e}")
        
        self._write(f"    ✅ {created_count} formations créées")
    
    def _create_test_absences(self):
        """Absences simplifiées"""
        employes = self.created_objects.get('employes', [])
        if not employes: return
        
        AbsenceUtilisateur = self.models['AbsenceUtilisateur']
        created_count = 0
        
        for employe in employes[:15]:
            try:
                date_debut = date.today() - timedelta(days=random.randint(0, 90))
                AbsenceUtilisateur.objects.create(
                    utilisateur=employe,
                    type_absence=random.choice(['Congé payé', 'Formation', 'RTT', 'Arrêt maladie']),
                    date_debut=date_debut,
                    date_fin=date_debut + timedelta(days=random.randint(1, 5)),
                    duree_jours=random.randint(1, 5),
                    source_donnee='KELIO'
                )
                created_count += 1
                self._update_stats('AbsenceUtilisateur', True)
            except Exception as e:
                logger.error(f"Erreur absence: {e}")
        
        self._write(f"    ✅ {created_count} absences créées")
    
    def _create_test_disponibilites(self):
        """Disponibilités simplifiées"""
        employes = self.created_objects.get('employes', [])
        if not employes: return
        
        DisponibiliteUtilisateur = self.models['DisponibiliteUtilisateur']
        created_count = 0
        
        for employe in employes:
            try:
                date_debut = date.today() + timedelta(days=random.randint(1, 30))
                DisponibiliteUtilisateur.objects.create(
                    utilisateur=employe,
                    type_disponibilite=random.choice(['DISPONIBLE', 'INDISPONIBLE']),
                    date_debut=date_debut,
                    date_fin=date_debut + timedelta(days=random.randint(1, 14)),
                    commentaire="Disponibilité test avec hiérarchie corrigée",
                    created_by=employe
                )
                created_count += 1
                self._update_stats('DisponibiliteUtilisateur', True)
            except Exception as e:
                logger.error(f"Erreur disponibilité: {e}")
        
        self._write(f"    ✅ {created_count} disponibilités créées")
    
    def _create_test_reponses_candidats(self):
        """Crée des réponses de candidats aux propositions"""
        ReponseCandidatInterim = self.models['ReponseCandidatInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        employes = self.created_objects.get('employes', [])
        
        if not demandes or not employes:
            self._write("⚠️ Pas de demandes ou d'employés pour créer les réponses candidats")
            return
        
        created_count = 0
        
        # Sélectionner quelques demandes avec candidats sélectionnés
        for demande in demandes[:10]:
            if employes:
                candidat = random.choice(employes)
                
                # Différents types de réponses
                reponse_type = random.choice(['ACCEPTE', 'REFUSE', 'EN_ATTENTE'])
                
                # Dates
                date_proposition = timezone.now() - timedelta(days=random.randint(1, 10))
                date_limite = date_proposition + timedelta(days=3)
                date_reponse = None
                
                if reponse_type != 'EN_ATTENTE':
                    date_reponse = date_proposition + timedelta(hours=random.randint(2, 60))
                
                # Motifs et commentaires pour les refus
                motif_refus = None
                commentaire_refus = ""
                
                if reponse_type == 'REFUSE':
                    motifs_possibles = ['INDISPONIBLE', 'COMPETENCES', 'DISTANCE', 'PERSONNEL']
                    motif_refus = random.choice(motifs_possibles)
                    commentaires_refus = {
                        'INDISPONIBLE': 'Malheureusement indisponible aux dates proposées',
                        'COMPETENCES': 'Ne me sens pas suffisamment compétent pour ce poste',
                        'DISTANCE': 'Trop éloigné de mon domicile',
                        'PERSONNEL': 'Raisons personnelles'
                    }
                    commentaire_refus = commentaires_refus.get(motif_refus, '')
                
                try:
                    reponse, created = ReponseCandidatInterim.objects.get_or_create(
                        demande=demande,
                        candidat=candidat,
                        reponse=reponse_type,
                        motif_refus=motif_refus,
                        commentaire_refus=commentaire_refus,
                        date_proposition=date_proposition,
                        date_reponse=date_reponse,
                        date_limite_reponse=date_limite,
                        salaire_propose=random.randint(2000000, 5000000) if random.choice([True, False]) else None,  # FCFA
                        avantages_proposes="Transport + repas" if random.choice([True, False]) else "",
                        nb_rappels_envoyes=random.randint(0, 2) if reponse_type == 'EN_ATTENTE' else 0,
                        derniere_date_rappel=timezone.now() - timedelta(hours=random.randint(6, 48)) if reponse_type == 'EN_ATTENTE' else None
                    )
                    
                    created_count += 1
                    self._update_stats('ReponseCandidatInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création réponse candidat: {e}")
        
        self._write(f"    ✅ {created_count} réponses candidats créées")
    
    def _create_test_cache(self):
        """Cache Kelio simplifié"""
        if not self.kelio_config: return
        
        CacheApiKelio = self.models['CacheApiKelio']
        created_count = 0
        
        try:
            cache_entry = CacheApiKelio.objects.create(
                configuration=self.kelio_config,
                cle_cache='test_cache_key_hierarchie_corrigee',
                service_name='employees',
                parametres_requete={'test': 'data', 'hierarchie': 'corrigee'},
                donnees={'test': 'cache_data', 'workflow': 'hierarchique'},
                date_expiration=timezone.now() + timedelta(hours=1),
                nb_acces=0,
                taille_donnees=150
            )
            created_count = 1
            self._update_stats('CacheApiKelio', True)
        except Exception as e:
            logger.error(f"Erreur cache: {e}")
        
        self._write(f"    ✅ {created_count} entrée(s) de cache créée(s)")
    
    # Méthodes héritées inchangées
    def _migrate_departements(self): self._create_test_departements()
    def _migrate_sites(self): self._create_test_sites()
    def _migrate_postes(self): self._create_test_postes()
    def _migrate_motifs_absence(self): self._create_test_motifs_absence()
    def _migrate_competences_referentiel(self): self._create_test_competences()
    def _migrate_competences_employes(self): pass  # Déjà gérées dans employes
    def _migrate_formations_employes(self): self._create_test_formations()
    def _migrate_absences_employes(self): self._create_test_absences()
    def _migrate_disponibilites_employes(self): self._create_test_disponibilites()
    def _migrate_demandes_interim(self): self._create_test_demandes_interim()
    def _migrate_workflow_demandes(self): self._create_test_workflow_complet_corrige()
    def _migrate_reponses_candidats(self): self._create_test_reponses_candidats()
    def _migrate_cache_kelio(self): self._create_test_cache()
    
    # ================================================================
    # MÉTHODES UTILITAIRES
    # ================================================================
    
    def _update_stats(self, model_name, created, count=1):
        """Met à jour les statistiques de migration"""
        if model_name not in self.stats['by_model']:
            self.stats['by_model'][model_name] = {'created': 0, 'updated': 0}
        
        if created:
            self.stats['by_model'][model_name]['created'] += count
            self.stats['total_created'] += count
        else:
            self.stats['by_model'][model_name]['updated'] += count
            self.stats['total_updated'] += count
    
    def _log_final_statistics(self, duration):
        """Affiche les statistiques finales avec détails hiérarchie corrigée"""
        self._write("📊 STATISTIQUES DE MIGRATION HIÉRARCHIE CORRIGÉE")
        self._write("=" * 80)
        self._write(f"⏱️  Durée totale: {duration:.2f} secondes")
        self._write(f"✅ Total créé: {self.stats['total_created']}")
        self._write(f"🔄 Total mis à jour: {self.stats['total_updated']}")
        self._write(f"❌ Total erreurs: {self.stats['total_errors']}")
        self._write("")
        self._write("📋 Détail par modèle:")
        
        for model_name, stats in self.stats['by_model'].items():
            created = stats['created']
            updated = stats['updated']
            total = created + updated
            if total > 0:
                self._write(f"  📦 {model_name}: {created} créé(s), {updated} mis à jour")
        
        self._write("")
        self._write("🎯 RÉSUMÉ DES DONNÉES AVEC HIÉRARCHIE CORRIGÉE:")
        self._write(f"  🏢 {len(self.created_objects.get('departements', []))} départements")
        self._write(f"  🏪 {len(self.created_objects.get('sites', []))} sites")
        self._write(f"  💼 {len(self.created_objects.get('postes', []))} postes")
        self._write(f"  👥 {len(self.created_objects.get('employes', []))} employés avec hiérarchie corrigée")
        self._write(f"  🎯 {len(self.created_objects.get('competences', []))} compétences")
        self._write(f"  🏥 {len(self.created_objects.get('motifs_absence', []))} motifs d'absence")
        self._write(f"  📋 {len(self.created_objects.get('demandes_interim', []))} demandes d'intérim")
        self._write(f"  👤 {len(self.created_objects.get('propositions', []))} propositions hiérarchiques")
        self._write(f"  ✅ {len(self.created_objects.get('validations', []))} validations multi-niveaux")
        self._write(f"  ⚙️ {len(self.created_objects.get('configurations_scoring', []))} configurations scoring corrigées")
        
        self._write("")
        self._write("🔄 HIÉRARCHIE DE VALIDATION CORRIGÉE:")
        self._write("  • Niveau 1: RESPONSABLE (validation opérationnelle)")
        self._write("  • Niveau 2: DIRECTEUR (validation stratégique)")
        self._write("  • Niveau 3: RH/ADMIN (validation finale)")
        self._write("  • CHEF_EQUIPE: Propositions uniquement")
        self._write("  • SUPERUSER: Droits complets automatiques")
        
        if self.with_workflow:
            self._write("  🔄 Workflow hiérarchique corrigé activé")
        if self.with_proposals:
            self._write("  👥 Propositions hiérarchiques activées")
        if self.with_notifications:
            self._write("  🔔 Notifications adaptées à la hiérarchie")
        
        self._write("=" * 80)
    
    def _log_error_statistics(self):
        """Affiche les statistiques en cas d'erreur"""
        self._write("❌ MIGRATION HIÉRARCHIE CORRIGÉE INTERROMPUE", self.style.ERROR if self.style else None)
        self._write("=" * 80)
        self._write(f"Erreurs rencontrées: {self.stats['total_errors']}")
        self._write(f"Éléments créés avant interruption: {self.stats['total_created']}")
        self._write("=" * 80)


# ================================================================
# LOG DE CONFIRMATION ET FINALISATION
# ================================================================

'''
logger.info("✅ Module populate_kelio_data.py CORRIGÉ terminé avec succès")
logger.info("🔧 Corrections apportées selon la nouvelle hiérarchie:")
logger.info("   • ✅ Hiérarchie : RESPONSABLE → DIRECTEUR → RH/ADMIN")
logger.info("   • ✅ Superutilisateurs : Droits complets automatiques")
logger.info("   • ✅ CHEF_EQUIPE : Peut proposer, ne valide pas")
logger.info("   • ✅ Types de profil alignés sur les nouveaux modèles")
logger.info("   • ✅ Sources de proposition corrigées")
logger.info("   • ✅ Types de validation alignés sur la hiérarchie")
logger.info("   • ✅ Bonus hiérarchiques selon les nouveaux niveaux")
logger.info("   • ✅ Configuration scoring avec bonus corrigés")
logger.info("   • ✅ Workflow étapes corrigées")
logger.info("   • ✅ Notifications adaptées à la hiérarchie")
logger.info("   • ✅ Historique enrichi avec niveau hiérarchique")
logger.info("🚀 Prêt pour utilisation avec les commandes Django manage.py")

print("🎯 populate_kelio_data.py CORRIGÉ TERMINÉ - Hiérarchie de validation cohérente")
print("💡 Usage avec hiérarchie corrigée:")
print("   python manage.py populate_kelio_data --mode=full")
print("   python manage.py populate_kelio_data --mode=workflow_demo --with-proposals --with-notifications")
print("   python manage.py populate_kelio_data --mode=test --sample-size=100 --with-workflow")
print("🔄 Hiérarchie: CHEF_EQUIPE → RESPONSABLE → DIRECTEUR → RH/ADMIN + SUPERUSER")
'''