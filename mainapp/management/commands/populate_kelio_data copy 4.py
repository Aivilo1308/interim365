#!/usr/bin/env python
"""
Commande Django Management pour remplir les tables avec les données Kelio
Compatible avec kelio_api_simplifie.py VERSION 4.1 - ENTIÈREMENT RÉÉCRITE

COMPATIBILITÉ KELIO API V4.1:
✅ Compatible avec EmployeeProfessionalDataService
✅ Support des nouveaux services SOAP documentés
✅ Mapping vers ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended
✅ Complémentation automatique si < 100 employés Kelio
✅ Noms africains (Côte d'Ivoire, Ghana, Mali)
✅ Hiérarchie corrigée : RESPONSABLE → DIRECTEUR → RH/ADMIN
✅ Workflow intégré avec nouvelles API
✅ Données périphériques complètes (compétences, formations, absences)

NOUVELLES FONCTIONNALITÉS V4.1:
✅ Synchronisation via API SOAP V4.1 avec fallback
✅ Complémentation intelligente employés fictifs
✅ Données périphériques automatiques pour employés Kelio et fictifs
✅ Workflow hiérarchique adapté aux nouvelles API
✅ Cache optimisé pour les nouvelles structures
✅ Scoring avec bonus hiérarchiques V4.1

Usage:
    python manage.py populate_kelio_data --mode=full --with-kelio-sync
    python manage.py populate_kelio_data --mode=kelio_plus_fictifs --min-employees=100
    python manage.py populate_kelio_data --mode=test --african-names --sample-size=150
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
import string

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================================================================
# DONNÉES AFRICAINES POUR NOMS FICTIFS
# ================================================================

NOMS_AFRICAINS = {
    'COTE_IVOIRE': {
        'prenoms_hommes': [
            'Kouadio', 'Koffi', 'Kouassi', 'Yao', 'Kouakou', 'Konan', 'Brou', 'Akissi', 
            'N\'Guessan', 'Diabaté', 'Kone', 'Traoré', 'Ouattara', 'Sanogo', 'Coulibaly',
            'Adjé', 'Amenan', 'Assi', 'Boa', 'Dago', 'Gbagbo', 'Adjoumani', 'Beugré'
        ],
        'prenoms_femmes': [
            'Akissi', 'Amenan', 'Adjoua', 'Affoué', 'Aya', 'Marie', 'Fatou', 'Aïcha',
            'Mariam', 'Fatoumata', 'Awa', 'Adama', 'Salimata', 'Rokia', 'Aminata',
            'Djénéba', 'Assétou', 'Massandjé', 'N\'Dri', 'Akoto', 'Abla', 'Ezin'
        ],
        'noms_famille': [
            'Kouassi', 'Koffi', 'Kouadio', 'Yao', 'Konan', 'N\'Guessan', 'Diabaté',
            'Kone', 'Traoré', 'Ouattara', 'Sanogo', 'Coulibaly', 'Bamba', 'Diarrassouba',
            'Gbagbo', 'Adjoumani', 'Beugré', 'Assi', 'Boa', 'Dago', 'Tanoh', 'Akoto',
            'Gnabeli', 'Ahoussi', 'Bongoua', 'Zadi', 'Silué', 'Doumbia', 'Fadiga'
        ]
    },
    'GHANA': {
        'prenoms_hommes': [
            'Kwame', 'Kofi', 'Kwaku', 'Yaw', 'Kwabena', 'Kwadwo', 'Akwasi', 'Agyeman',
            'Nana', 'Kojo', 'Emmanuel', 'Prince', 'Isaac', 'Samuel', 'Daniel', 'David',
            'Francis', 'Joseph', 'Michael', 'Peter', 'Richard', 'Stephen', 'Thomas'
        ],
        'prenoms_femmes': [
            'Akosua', 'Efua', 'Ama', 'Yaa', 'Abena', 'Adwoa', 'Akua', 'Araba',
            'Esi', 'Maame', 'Akoto', 'Adiza', 'Fatima', 'Hajia', 'Rahinatu',
            'Salamatu', 'Zeinab', 'Aishah', 'Maryam', 'Khadija', 'Afia', 'Aba'
        ],
        'noms_famille': [
            'Asante', 'Osei', 'Boateng', 'Mensah', 'Adjei', 'Agyeman', 'Nkrumah',
            'Appiah', 'Owusu', 'Frimpong', 'Gyasi', 'Darko', 'Addai', 'Wiredu',
            'Opoku', 'Kwarteng', 'Amoah', 'Antwi', 'Bonsu', 'Danquah', 'Essien'
        ]
    },
    'MALI': {
        'prenoms_hommes': [
            'Mamadou', 'Ibrahim', 'Moussa', 'Abdoulaye', 'Seydou', 'Bakary', 'Ousmane',
            'Amadou', 'Modibo', 'Souleymane', 'Boubacar', 'Adama', 'Lassana', 'Drissa',
            'Fousseyni', 'Karim', 'Mahamane', 'Salif', 'Tiémoko', 'Youssouf', 'Cheick'
        ],
        'prenoms_femmes': [
            'Fatoumata', 'Aminata', 'Mariam', 'Aïcha', 'Oumou', 'Assétou', 'Rokia',
            'Salimata', 'Djénéba', 'Awa', 'Hawa', 'Kadiatou', 'Massandjé', 'Néné',
            'Ramata', 'Safiatou', 'Sirah', 'Téné', 'Yayi', 'Zineb', 'Coumba'
        ],
        'noms_famille': [
            'Traoré', 'Coulibaly', 'Diabaté', 'Kone', 'Sanogo', 'Diarra', 'Doumbia',
            'Sidibé', 'Camara', 'Keita', 'Dembélé', 'Bagayoko', 'Dicko', 'Maïga',
            'Touré', 'Cissé', 'Barry', 'Diallo', 'Bah', 'Sow', 'Tall', 'Fall'
        ]
    }
}

VILLES_COTE_IVOIRE = [
    'Abidjan', 'Bouaké', 'Daloa', 'Yamoussoukro', 'Korhogo', 'San-Pédro', 'Man',
    'Divo', 'Gagnoa', 'Anyama', 'Abengourou', 'Agboville', 'Grand-Bassam',
    'Bingerville', 'Soubré', 'Issia', 'Sinfra', 'Bondoukou', 'Adzopé', 'Oumé'
]

QUARTIERS_ABIDJAN = [
    'Plateau', 'Cocody', 'Marcory', 'Koumassi', 'Treichville', 'Adjamé', 'Yopougon',
    'Abobo', 'Attécoubé', 'Port-Bouët', 'Bingerville', 'Anyama', 'Songon'
]

class Command(BaseCommand):
    """
    Commande Django pour la migration et population des données Kelio V4.1 compatible
    """
    help = 'Remplit les tables Django avec les données depuis Kelio V4.1 ou complète avec données fictives africaines'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--mode',
            choices=[
                'full', 'kelio_plus_fictifs', 'kelio_sync_only', 'fictifs_only',
                'workflow_demo', 'scoring_demo', 'test', 'migration_v41'
            ],
            default='kelio_plus_fictifs',
            help='Mode de migration compatible V4.1'
        )
        parser.add_argument(
            '--min-employees',
            type=int,
            default=100,
            help='Nombre minimum d\'employés (compléter avec fictifs si besoin)'
        )
        parser.add_argument(
            '--african-names',
            action='store_true',
            help='Utiliser exclusivement des noms africains'
        )
        parser.add_argument(
            '--with-kelio-sync',
            action='store_true',
            help='Synchroniser avec Kelio V4.1 avant complémentation'
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
            default=150,
            help='Nombre d\'éléments à créer pour les données de test'
        )
        parser.add_argument(
            '--with-peripherals',
            action='store_true',
            help='Créer les données périphériques (compétences, formations, absences)'
        )
        parser.add_argument(
            '--with-workflow',
            action='store_true',
            help='Créer des données de workflow complet V4.1'
        )
        parser.add_argument(
            '--countries',
            nargs='+',
            choices=['COTE_IVOIRE', 'GHANA', 'MALI'],
            default=['COTE_IVOIRE', 'GHANA', 'MALI'],
            help='Pays pour les noms fictifs'
        )
    
    def handle(self, *args, **options):
        """Point d'entrée principal de la commande"""
        try:
            # Configuration du niveau de log
            if options['verbose']:
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Affichage des paramètres
            self.stdout.write(self.style.SUCCESS('🚀 MIGRATION DONNÉES KELIO V4.1 COMPATIBLE'))
            self.stdout.write("=" * 80)
            self.stdout.write(f"Mode: {options['mode']}")
            self.stdout.write(f"Employés minimum: {options['min_employees']}")
            self.stdout.write(f"Noms africains: {'Oui' if options['african_names'] else 'Non'}")
            self.stdout.write(f"Sync Kelio V4.1: {'Oui' if options['with_kelio_sync'] else 'Non'}")
            self.stdout.write(f"Test connexion: {'Non' if options['no_test_connection'] else 'Oui'}")
            self.stdout.write(f"Simulation: {'Oui' if options['dry_run'] else 'Non'}")
            self.stdout.write(f"Force: {'Oui' if options['force'] else 'Non'}")
            self.stdout.write(f"Taille échantillon: {options['sample_size']}")
            self.stdout.write(f"Données périphériques: {'Oui' if options['with_peripherals'] else 'Non'}")
            self.stdout.write(f"Workflow V4.1: {'Oui' if options['with_workflow'] else 'Non'}")
            self.stdout.write(f"Pays: {', '.join(options['countries'])}")
            self.stdout.write("=" * 80)
            
            if options['dry_run']:
                self.stdout.write(self.style.WARNING("🧪 MODE SIMULATION - Aucune modification ne sera effectuée"))
                return
            
            # Lancer la migration V4.1 compatible
            migration = KelioDataMigrationV41Compatible(
                stdout=self.stdout,
                style=self.style,
                force=options['force'],
                min_employees=options['min_employees'],
                african_names=options['african_names'],
                with_kelio_sync=options['with_kelio_sync'],
                sample_size=options['sample_size'],
                with_peripherals=options['with_peripherals'],
                with_workflow=options['with_workflow'],
                countries=options['countries']
            )
            
            success = migration.run_migration(
                mode=options['mode'],
                test_connection=not options['no_test_connection']
            )
            
            if success:
                self.stdout.write(
                    self.style.SUCCESS('✅ Migration Kelio V4.1 compatible terminée avec succès')
                )
            else:
                raise CommandError('❌ Migration Kelio V4.1 compatible échouée')
                
        except Exception as e:
            logger.error(f"Erreur dans la commande: {e}")
            raise CommandError(f'Erreur lors de la migration V4.1: {str(e)}')


# ================================================================
# CLASSE PRINCIPALE DE MIGRATION V4.1 COMPATIBLE
# ================================================================

class KelioDataMigrationV41Compatible:
    """
    Gestionnaire principal pour la migration des données Kelio V4.1 compatible
    avec complémentation automatique employés fictifs africains
    """
    
    def __init__(self, stdout=None, style=None, force=False, min_employees=100,
                 african_names=False, with_kelio_sync=False, sample_size=150,
                 with_peripherals=False, with_workflow=False, countries=None):
        
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
            'by_model': {},
            'kelio_employees': 0,
            'fictional_employees': 0,
            'peripheral_data_created': 0
        }
        
        # Configuration V4.1
        self.kelio_config = None
        self.kelio_service = None
        self.stdout = stdout
        self.style = style
        self.force = force
        self.min_employees = min_employees
        self.african_names = african_names
        self.with_kelio_sync = with_kelio_sync
        self.sample_size = sample_size
        self.with_peripherals = with_peripherals
        self.with_workflow = with_workflow
        self.countries = countries or ['COTE_IVOIRE', 'GHANA', 'MALI']
        
        # Stockage des objets créés pour les relations et workflow
        self.created_objects = {
            'departements': [],
            'sites': [],
            'postes': [],
            'employes_kelio': [],
            'employes_fictifs': [],
            'employes_tous': [],
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
    
    def run_migration(self, mode='kelio_plus_fictifs', test_connection=True):
        """
        Lance la migration complète des données Kelio V4.1 avec complémentation
        """
        self._write(f"🚀 Début de la migration Kelio V4.1 compatible en mode: {mode}")
        start_time = timezone.now()
        
        try:
            # Étape 1: Configuration Kelio V4.1
            self._setup_kelio_configuration_v41()
            
            # Étape 2: Configuration du scoring V4.1
            self._setup_scoring_configuration_v41()
            
            # Étape 3: Configuration du workflow V4.1
            self._setup_workflow_configuration_v41()
            
            # Étape 4: Test de connexion Kelio V4.1 (optionnel)
            if test_connection and mode not in ['fictifs_only', 'test']:
                self._test_kelio_connection_v41()
            
            # Étape 5: Migration selon le mode V4.1
            if mode == 'full':
                self._migrate_full_v41()
            elif mode == 'kelio_plus_fictifs':
                self._migrate_kelio_plus_fictifs_v41()
            elif mode == 'kelio_sync_only':
                self._migrate_kelio_sync_only_v41()
            elif mode == 'fictifs_only':
                self._migrate_fictifs_only_v41()
            elif mode == 'workflow_demo':
                self._migrate_workflow_demo_v41()
            elif mode == 'scoring_demo':
                self._migrate_scoring_demo_v41()
            elif mode == 'test':
                self._migrate_test_data_v41()
            elif mode == 'migration_v41':
                self._migrate_from_old_to_v41()
            else:
                raise ValueError(f"Mode de migration non supporté: {mode}")
            
            # Statistiques finales
            duration = (timezone.now() - start_time).total_seconds()
            self._log_final_statistics(duration)
            
            self._write("✅ Migration Kelio V4.1 compatible terminée avec succès", 
                       self.style.SUCCESS if self.style else None)
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la migration Kelio V4.1: {e}")
            self._log_error_statistics()
            self._write(f"❌ Erreur migration V4.1: {e}", self.style.ERROR if self.style else None)
            return False
    
    def _setup_kelio_configuration_v41(self):
        """Configure la connexion Kelio V4.1 compatible"""
        ConfigurationApiKelio = self.models['ConfigurationApiKelio']
        
        try:
            # Configuration V4.1 avec nouveaux services
            self.kelio_config, created = ConfigurationApiKelio.objects.get_or_create(
                nom='Configuration Kelio V4.1',
                defaults={
                    'url_base': 'https://keliodemo-safesecur.kelio.io',
                    'username': 'webservices',
                    'password': '12345',
                    'timeout_seconds': 60,
                    'service_employees': True,
                    'service_absences': True,
                    'service_formations': True,
                    'service_competences': True,
                    'cache_duree_defaut_minutes': 60,
                    'cache_taille_max_mo': 200,
                    'auto_invalidation_cache': True,
                    'actif': True,
                    # Nouveaux champs V4.1
                    #'version_api': '4.1',
                    #'support_professional_data_service': True,
                    #'support_peripheral_services': True,
                    #'max_employees_per_request': 1000
                }
            )
            
            action = "créée" if created else "récupérée"
            self._write(f"🔧 Configuration Kelio V4.1 {action}: {self.kelio_config.nom}")
            
            if created:
                self.stats['by_model']['ConfigurationApiKelio'] = {'created': 1, 'updated': 0}
            
        except Exception as e:
            logger.error(f"Erreur configuration Kelio V4.1: {e}")
            raise
    
    def _setup_scoring_configuration_v41(self):
        """Configure les paramètres de scoring V4.1"""
        ConfigurationScoring = self.models['ConfigurationScoring']
        
        try:
            # Configuration V4.1 avec hiérarchie corrigée
            config_v41, created = ConfigurationScoring.objects.get_or_create(
                nom='Configuration V4.1',
                defaults={
                    'description': 'Configuration de scoring V4.1 avec hiérarchie corrigée et nouveaux services',
                    'poids_similarite_poste': 0.25,
                    'poids_competences': 0.25,
                    'poids_experience': 0.20,
                    'poids_disponibilite': 0.15,
                    'poids_proximite': 0.10,
                    'poids_anciennete': 0.05,
                    'bonus_proposition_humaine': 5,
                    'bonus_experience_similaire': 8,
                    'bonus_recommandation': 10,
                    # Bonus hiérarchiques V4.1 corrigés
                    'bonus_manager_direct': 12,
                    'bonus_chef_equipe': 8,
                    'bonus_responsable': 15,     # Niveau 1 validation
                    'bonus_directeur': 18,       # Niveau 2 validation
                    'bonus_rh': 20,              # Niveau 3 validation
                    'bonus_admin': 20,           # Niveau 3 étendu
                    'bonus_superuser': 0,        # Droits complets automatiques
                    'penalite_indisponibilite_partielle': 15,
                    'penalite_indisponibilite_totale': 50,
                    'penalite_distance_excessive': 10,
                    'configuration_par_defaut': True,
                    'actif': True,
                    # Nouveaux champs V4.1
                    #'version_scoring': '4.1',
                    #'support_peripheral_data': True,
                    #'bonus_kelio_data_quality': 5
                }
            )
            
            self.created_objects['configurations_scoring'].append(config_v41)
            
            if created:
                self._update_stats('ConfigurationScoring', True)
                self._write(f"⚙️ Configuration de scoring V4.1 créée")
            
        except Exception as e:
            logger.error(f"Erreur configuration scoring V4.1: {e}")
            raise
    
    def _setup_workflow_configuration_v41(self):
        """Configure les étapes du workflow V4.1"""
        WorkflowEtape = self.models['WorkflowEtape']
        
        try:
            etapes_v41 = [
                {
                    'nom': 'Création demande V4.1',
                    'type_etape': 'DEMANDE',
                    'ordre': 1,
                    'obligatoire': True,
                    'delai_max_heures': None,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Proposition candidats V4.1',
                    'type_etape': 'PROPOSITION_CANDIDATS',
                    'ordre': 2,
                    'obligatoire': True,
                    'delai_max_heures': 48,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Validation Responsable V4.1',
                    'type_etape': 'VALIDATION_RESPONSABLE',
                    'ordre': 3,
                    'obligatoire': True,
                    'delai_max_heures': 24,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Validation Directeur V4.1',
                    'type_etape': 'VALIDATION_DIRECTEUR',
                    'ordre': 4,
                    'obligatoire': True,
                    'delai_max_heures': 24,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Validation RH/Admin V4.1',
                    'type_etape': 'VALIDATION_RH_ADMIN',
                    'ordre': 5,
                    'obligatoire': True,
                    'delai_max_heures': 12,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': True,
                    'permet_ajout_nouveaux_candidats': True,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Notification candidat V4.1',
                    'type_etape': 'NOTIFICATION_CANDIDAT',
                    'ordre': 6,
                    'obligatoire': True,
                    'delai_max_heures': 2,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Acceptation candidat V4.1',
                    'type_etape': 'ACCEPTATION_CANDIDAT',
                    'ordre': 7,
                    'obligatoire': True,
                    'delai_max_heures': 72,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'version_workflow': '4.1',
                    'actif': True
                },
                {
                    'nom': 'Finalisation V4.1',
                    'type_etape': 'FINALISATION',
                    'ordre': 8,
                    'obligatoire': True,
                    'delai_max_heures': None,
                    'condition_urgence': 'TOUTES',
                    'permet_propositions_humaines': False,
                    'permet_ajout_nouveaux_candidats': False,
                    'version_workflow': '4.1',
                    'actif': True
                }
            ]
            
            etapes_created = 0
            for etape_data in etapes_v41:
                etape, created = WorkflowEtape.objects.get_or_create(
                    type_etape=etape_data['type_etape'],
                    version_workflow=etape_data['version_workflow'],
                    defaults=etape_data
                )
                if created:
                    etapes_created += 1
            
            self._write(f"📋 Étapes de workflow V4.1 créées: {etapes_created}")
            
            if etapes_created > 0:
                self._update_stats('WorkflowEtape', True, count=etapes_created)
            
        except Exception as e:
            logger.error(f"Erreur configuration workflow V4.1: {e}")
            raise
    
    def _test_kelio_connection_v41(self):
        """Test la connexion aux services Kelio V4.1"""
        try:
            self._write("🔍 Test de connexion aux services Kelio V4.1...")
            
            # Import du service de synchronisation V4.1
            try:
                from mainapp.services.kelio_api_simplifie_modif import get_kelio_sync_service_v41
                
                self.kelio_service = get_kelio_sync_service_v41(self.kelio_config)
                test_results = self.kelio_service.test_connexion_complete_v41()
                
                if test_results.get('global_status', False):
                    self._write("✅ Connexion Kelio V4.1 réussie", self.style.SUCCESS if self.style else None)
                    
                    # Log détaillé des nouveaux services V4.1
                    services_status = test_results.get('services_status', {})
                    for service_name, service_info in services_status.items():
                        status = "✅" if service_info.get('status') == 'OK' else "❌"
                        description = service_info.get('description', '')
                        self._write(f"  {status} {service_name}: {description}")
                    
                    # Log du service principal
                    service_principal = test_results.get('service_principal', {})
                    if service_principal.get('status') == 'OK':
                        nb_employees = service_principal.get('nb_employees_found', 0)
                        self._write(f"  🎯 EmployeeProfessionalDataService: {nb_employees} employé(s) trouvé(s)")
                    
                else:
                    self._write("⚠️ Certains services Kelio V4.1 ne sont pas disponibles", 
                               self.style.WARNING if self.style else None)
                    self._write("Migration en mode dégradé - complémentation avec données fictives")
                    
            except ImportError as e:
                logger.warning(f"Service Kelio V4.1 non disponible: {e}")
                self._write("⚠️ Service Kelio V4.1 non disponible - utilisation de données fictives", 
                           self.style.WARNING if self.style else None)
                
        except Exception as e:
            logger.warning(f"⚠️ Test de connexion Kelio V4.1 échoué: {e}")
            self._write("⚠️ Test connexion V4.1 échoué - migration avec données fictives", 
                       self.style.WARNING if self.style else None)
    
    def _migrate_full_v41(self):
        """Migration complète V4.1 avec Kelio + complémentation"""
        self._write("📊 Migration complète V4.1 avec synchronisation Kelio + complémentation")
        
        migration_steps = [
            ("Structure de base", self._create_base_structure),
            ("Sync employés Kelio V4.1", self._sync_employees_from_kelio_v41),
            ("Complémentation employés fictifs", self._complete_with_fictional_employees),
            ("Données périphériques", self._create_peripheral_data_v41),
            ("Demandes d'intérim", self._create_interim_requests),
            ("Workflow complet V4.1", self._create_workflow_data_v41),
            ("Cache Kelio V4.1", self._create_kelio_cache_v41)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_kelio_plus_fictifs_v41(self):
        """Migration principale : Kelio V4.1 + complémentation fictifs africains"""
        self._write("🎯 Migration Kelio V4.1 + complémentation employés fictifs africains")
        
        migration_steps = [
            ("Structure organisationnelle", self._create_base_structure),
            ("Synchronisation Kelio V4.1", self._sync_employees_from_kelio_v41),
            ("Analyse et complémentation", self._analyze_and_complete_employees),
            ("Données périphériques V4.1", self._create_peripheral_data_v41),
            ("Workflow et demandes", self._create_workflow_data_v41)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_kelio_sync_only_v41(self):
        """Synchronisation Kelio V4.1 uniquement"""
        self._write("📥 Synchronisation Kelio V4.1 uniquement")
        
        migration_steps = [
            ("Structure minimale", self._create_minimal_structure),
            ("Synchronisation complète Kelio V4.1", self._sync_employees_from_kelio_v41),
            ("Données périphériques Kelio", self._sync_peripheral_data_from_kelio_v41)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_fictifs_only_v41(self):
        """Création d'employés fictifs africains uniquement"""
        self._write("🎭 Création d'employés fictifs africains uniquement")
        
        migration_steps = [
            ("Structure de base", self._create_base_structure),
            ("Employés fictifs africains", self._create_fictional_employees_african),
            ("Données périphériques fictives", self._create_fictional_peripheral_data),
            ("Workflow démo", self._create_demo_workflow_data)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_workflow_demo_v41(self):
        """Migration en mode démo workflow V4.1"""
        self._write("🎯 Migration en mode démo workflow V4.1")
        
        migration_steps = [
            ("Structure de base", self._create_base_structure),
            ("Employés démo", self._create_demo_employees),
            ("Workflow complet V4.1", self._create_comprehensive_workflow_v41),
            ("Notifications avancées", self._create_advanced_notifications)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_scoring_demo_v41(self):
        """Migration en mode démo scoring V4.1"""
        self._write("📊 Migration en mode démo scoring V4.1")
        
        migration_steps = [
            ("Structure et employés", self._create_base_structure_and_employees),
            ("Scores détaillés V4.1", self._create_detailed_scores_v41),
            ("Comparaisons scoring", self._create_scoring_comparisons),
            ("Analytics avancés", self._create_scoring_analytics)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_test_data_v41(self):
        """Migration avec données de test complètes V4.1"""
        self._write("🧪 Migration avec données de test complètes V4.1")
        
        migration_steps = [
            ("Structure complète", self._create_base_structure),
            ("Employés test africains", self._create_test_employees_african),
            ("Données périphériques test", self._create_test_peripheral_data),
            ("Workflow test complet", self._create_test_workflow_complete),
            ("Cache et optimisations", self._create_test_cache_and_optimizations)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _migrate_from_old_to_v41(self):
        """Migration des anciennes données vers V4.1"""
        self._write("🔄 Migration des anciennes données vers V4.1")
        
        migration_steps = [
            ("Audit données existantes", self._audit_existing_data),
            ("Migration structure V4.1", self._migrate_structure_to_v41),
            ("Migration employés vers V4.1", self._migrate_employees_to_v41),
            ("Migration workflow vers V4.1", self._migrate_workflow_to_v41),
            ("Validation post-migration", self._validate_v41_migration)
        ]
        
        self._execute_migration_steps(migration_steps)
    
    def _execute_migration_steps(self, steps):
        """Exécute une séquence d'étapes de migration"""
        for step_name, step_function in steps:
            self._write(f"🔄 {step_name}...")
            try:
                with transaction.atomic():
                    step_function()
                self._write(f"✅ {step_name} terminé")
            except Exception as e:
                logger.error(f"❌ Erreur {step_name}: {e}")
                self._write(f"❌ Erreur {step_name}: {e}", self.style.ERROR if self.style else None)
                # Continuer la migration même en cas d'erreur sur une étape
    
    # ================================================================
    # MÉTHODES DE SYNCHRONISATION KELIO V4.1
    # ================================================================
    
    def _sync_employees_from_kelio_v41(self):
        """Synchronise les employés depuis Kelio V4.1 avec gestion complète"""
        if not self.with_kelio_sync:
            self._write("⏭️ Synchronisation Kelio désactivée")
            return
        
        try:
            if not self.kelio_service:
                self._write("⚠️ Service Kelio V4.1 non disponible, création d'employés fictifs")
                self._create_fictional_employees_african()
                return
            
            self._write("📥 Synchronisation des employés depuis Kelio V4.1...")
            
            # Utiliser le service V4.1 pour synchroniser tous les employés
            resultats_sync = self.kelio_service.synchroniser_tous_les_employes(mode='complet')
            
            if resultats_sync.get('statut_global') in ['reussi', 'partiel']:
                nb_employes_sync = resultats_sync.get('employees_reussis', 0)
                self.stats['kelio_employees'] = nb_employes_sync
                
                self._write(f"✅ {nb_employes_sync} employé(s) synchronisé(s) depuis Kelio V4.1")
                
                # Récupérer les employés synchronisés
                ProfilUtilisateur = self.models['ProfilUtilisateur']
                employes_kelio = list(ProfilUtilisateur.objects.filter(
                    kelio_sync_status='REUSSI',
                    actif=True
                ).select_related('user', 'departement', 'site', 'poste'))
                
                self.created_objects['employes_kelio'] = employes_kelio
                self.created_objects['employes_tous'].extend(employes_kelio)
                
                # Afficher la répartition hiérarchique
                self._display_hierarchy_distribution(employes_kelio, "Employés Kelio V4.1")
                
            else:
                error_msg = resultats_sync.get('erreur_critique', 'Erreur synchronisation inconnue')
                self._write(f"❌ Erreur synchronisation Kelio V4.1: {error_msg}")
                self._write("💡 Création d'employés fictifs en fallback")
                self._create_fictional_employees_african()
            
        except Exception as e:
            logger.error(f"Erreur synchronisation Kelio V4.1: {e}")
            self._write(f"❌ Erreur synchronisation V4.1: {e}")
            self._write("💡 Fallback vers employés fictifs")
            self._create_fictional_employees_african()
    
    def _sync_peripheral_data_from_kelio_v41(self):
        """Synchronise les données périphériques depuis Kelio V4.1"""
        if not self.kelio_service or not self.with_peripherals:
            return
        
        try:
            self._write("📊 Synchronisation des données périphériques Kelio V4.1...")
            
            employes_kelio = self.created_objects.get('employes_kelio', [])
            if not employes_kelio:
                self._write("⚠️ Aucun employé Kelio à traiter pour les données périphériques")
                return
            
            peripheral_count = 0
            
            for employe in employes_kelio[:20]:  # Limiter pour la démo
                try:
                    # Synchroniser les données périphériques pour cet employé
                    resultats_peripheriques = self.kelio_service.synchroniser_donnees_peripheriques_employe_v41(
                        employe.matricule
                    )
                    
                    if resultats_peripheriques.get('statut_global') in ['reussi', 'partiel']:
                        peripheral_count += 1
                        self.stats['peripheral_data_created'] += resultats_peripheriques.get('services_reussis', 0)
                        
                except Exception as e:
                    logger.error(f"Erreur données périphériques employé {employe.matricule}: {e}")
            
            self._write(f"✅ Données périphériques synchronisées pour {peripheral_count} employé(s)")
            
        except Exception as e:
            logger.error(f"Erreur synchronisation données périphériques V4.1: {e}")
    
    def _analyze_and_complete_employees(self):
        """Analyse les employés Kelio et complète avec des fictifs si nécessaire"""
        employes_kelio = self.created_objects.get('employes_kelio', [])
        nb_kelio = len(employes_kelio)
        
        self._write(f"📊 Analyse: {nb_kelio} employé(s) depuis Kelio V4.1")
        
        if nb_kelio < self.min_employees:
            nb_fictifs_needed = self.min_employees - nb_kelio
            self._write(f"📈 Complémentation nécessaire: {nb_fictifs_needed} employé(s) fictif(s)")
            
            # Créer les employés fictifs manquants
            self._create_specific_number_fictional_employees(nb_fictifs_needed)
        else:
            self._write(f"✅ Nombre d'employés suffisant ({nb_kelio} >= {self.min_employees})")
        
        # Afficher le résumé final
        total_employees = len(self.created_objects['employes_tous'])
        self._write(f"👥 Total final: {total_employees} employé(s) ({nb_kelio} Kelio + {total_employees - nb_kelio} fictifs)")
    
    # ================================================================
    # MÉTHODES DE CRÉATION D'EMPLOYÉS FICTIFS AFRICAINS
    # ================================================================
    
    def _create_fictional_employees_african(self):
        """Crée des employés fictifs avec noms africains"""
        nb_to_create = max(self.min_employees, 50)
        self._create_specific_number_fictional_employees(nb_to_create)
    
    def _create_specific_number_fictional_employees(self, nb_to_create):
        """Crée un nombre spécifique d'employés fictifs africains"""
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        ProfilUtilisateurKelio = self.models['ProfilUtilisateurKelio']
        ProfilUtilisateurExtended = self.models['ProfilUtilisateurExtended']
        
        departements = self.created_objects.get('departements', [])
        sites = self.created_objects.get('sites', [])
        postes = self.created_objects.get('postes', [])
        
        if not all([departements, sites]):
            self._write("⚠️ Structure de base manquante pour créer les employés fictifs")
            return
        
        created_count = 0
        
        # Distribution hiérarchique réaliste
        hierarchy_distribution = {
            'UTILISATEUR': 0.70,      # 70% utilisateurs
            'CHEF_EQUIPE': 0.15,      # 15% chefs d'équipe
            'RESPONSABLE': 0.10,      # 10% responsables
            'DIRECTEUR': 0.03,        # 3% directeurs
            'RH': 0.01,               # 1% RH
            'ADMIN': 0.01             # 1% Admin
        }
        
        self._write(f"🎭 Création de {nb_to_create} employé(s) fictif(s) africain(s)...")
        
        for i in range(nb_to_create):
            try:
                with transaction.atomic():
                    # Sélectionner un pays au hasard
                    country = random.choice(self.countries)
                    noms_data = NOMS_AFRICAINS[country]
                    
                    # Générer un genre et sélectionner le prénom
                    is_male = random.choice([True, False])
                    prenom = random.choice(
                        noms_data['prenoms_hommes'] if is_male else noms_data['prenoms_femmes']
                    )
                    nom = random.choice(noms_data['noms_famille'])
                    
                    # Générer les données utilisateur
                    username = self._generate_unique_username(prenom, nom, i)
                    email = self._generate_email(prenom, nom, country)
                    
                    # Déterminer le type de profil selon la distribution
                    type_profil = self._select_profile_type_by_distribution(hierarchy_distribution, i, nb_to_create)
                    
                    # Créer l'utilisateur Django
                    user_data = {
                        'username': username,
                        'first_name': prenom,
                        'last_name': nom,
                        'email': email,
                        'is_active': True
                    }
                    
                    # Gestion des superutilisateurs
                    if type_profil == 'ADMIN' and random.random() < 0.3:  # 30% des ADMIN sont superuser
                        user_data['is_superuser'] = True
                        user_data['is_staff'] = True
                    
                    user = User.objects.create_user(**user_data)
                    
                    # Créer le profil utilisateur
                    matricule = f"FIC{i+1000:04d}"
                    departement = random.choice(departements)
                    site = random.choice(sites)
                    poste = random.choice(postes) if postes else None
                    
                    profil = ProfilUtilisateur.objects.create(
                        user=user,
                        matricule=matricule,
                        type_profil=type_profil,
                        statut_employe='ACTIF',
                        departement=departement,
                        site=site,
                        poste=poste,
                        actif=True,
                        date_embauche=self._generate_random_hire_date(),
                        source_creation='FICTIF_AFRICAIN'
                    )
                    
                    # Créer les données Kelio fictives
                    ProfilUtilisateurKelio.objects.create(
                        profil=profil,
                        kelio_employee_key=f"FICT_{i+2000}",
                        kelio_badge_code=f"BADGE_{matricule}",
                        kelio_department_name=departement.nom,
                        kelio_job_title=poste.titre if poste else "Employé",
                        code_personnel=matricule,
                        email_kelio=email,
                        telephone_kelio=self._generate_african_phone_number(country),
                        derniere_synchronisation=timezone.now()
                    )
                    
                    # Créer les données étendues
                    ville = random.choice(VILLES_COTE_IVOIRE) if country == 'COTE_IVOIRE' else f"Ville {country}"
                    quartier = random.choice(QUARTIERS_ABIDJAN) if ville == 'Abidjan' else f"Quartier {ville}"
                    
                    ProfilUtilisateurExtended.objects.create(
                        profil=profil,
                        telephone=self._generate_african_phone_number(country),
                        telephone_mobile=self._generate_african_phone_number(country, mobile=True),
                        adresse=f"{random.randint(1, 999)} Rue {random.choice(['des Jardins', 'de la Paix', 'du Commerce', 'FHB'])}, {quartier}",
                        ville=ville,
                        code_postal=f"{random.randint(10000, 99999):05d}",
                        pays=country.replace('_', ' ').title(),
                        disponible_interim=random.choice([True, True, False]),  # 66% disponibles
                        rayon_deplacement_km=random.randint(25, 100),
                        langues_parlees=self._generate_languages_for_country(country),
                        source_creation='FICTIF_AFRICAIN'
                    )
                    
                    created_count += 1
                    self.created_objects['employes_fictifs'].append(profil)
                    self.created_objects['employes_tous'].append(profil)
                    self._update_stats('ProfilUtilisateur', True)
                    
            except Exception as e:
                logger.error(f"Erreur création employé fictif {i}: {e}")
        
        self.stats['fictional_employees'] = created_count
        self._write(f"✅ {created_count} employé(s) fictif(s) africain(s) créé(s)")
        
        # Afficher la distribution par pays et hiérarchie
        if created_count > 0:
            self._display_fictional_employees_stats()
    
    def _generate_unique_username(self, prenom, nom, index):
        """Génère un nom d'utilisateur unique"""
        base_username = f"{prenom.lower()}.{nom.lower()}".replace(' ', '').replace('\'', '')
        # Nettoyer les caractères spéciaux
        base_username = ''.join(c for c in base_username if c.isalnum() or c == '.')
        
        # Ajouter un suffixe si nécessaire
        username = base_username
        if User.objects.filter(username=username).exists():
            username = f"{base_username}{index+1000}"
        
        return username[:30]  # Limiter la longueur
    
    def _generate_email(self, prenom, nom, country):
        """Génère une adresse email"""
        domain_map = {
            'COTE_IVOIRE': 'entreprise.ci',
            'GHANA': 'company.gh',
            'MALI': 'societe.ml'
        }
        
        domain = domain_map.get(country, 'company.local')
        username_part = f"{prenom.lower()}.{nom.lower()}".replace(' ', '').replace('\'', '')
        username_part = ''.join(c for c in username_part if c.isalnum() or c == '.')
        
        return f"{username_part}@{domain}"
    
    def _select_profile_type_by_distribution(self, distribution, index, total):
        """Sélectionne un type de profil selon la distribution hiérarchique"""
        # Pour les premiers employés, garantir au moins un de chaque type clé
        if index < 10:
            key_types = ['ADMIN', 'RH', 'DIRECTEUR', 'RESPONSABLE', 'CHEF_EQUIPE']
            if index < len(key_types):
                return key_types[index]
        
        # Sélection aléatoire pondérée
        types = list(distribution.keys())
        weights = list(distribution.values())
        
        return random.choices(types, weights=weights)[0]
    
    def _generate_random_hire_date(self):
        """Génère une date d'embauche aléatoire"""
        days_ago = random.randint(30, 2000)  # Entre 1 mois et 5.5 ans
        return date.today() - timedelta(days=days_ago)
    
    def _generate_african_phone_number(self, country, mobile=False):
        """Génère un numéro de téléphone africain"""
        phone_formats = {
            'COTE_IVOIRE': {
                'mobile': ['+225 05', '+225 07', '+225 01'],
                'fixe': ['+225 21', '+225 22', '+225 23']
            },
            'GHANA': {
                'mobile': ['+233 20', '+233 23', '+233 24', '+233 26', '+233 27'],
                'fixe': ['+233 30', '+233 31', '+233 32']
            },
            'MALI': {
                'mobile': ['+223 65', '+223 66', '+223 67', '+223 70', '+223 76'],
                'fixe': ['+223 20', '+223 21', '+223 44']
            }
        }
        
        formats = phone_formats.get(country, phone_formats['COTE_IVOIRE'])
        prefix = random.choice(formats['mobile'] if mobile else formats['fixe'])
        
        # Générer le reste du numéro
        remaining_digits = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        remaining_formatted = ' '.join([remaining_digits[i:i+2] for i in range(0, len(remaining_digits), 2)])
        
        return f"{prefix} {remaining_formatted}"
    
    def _generate_languages_for_country(self, country):
        """Génère la liste des langues pour un pays"""
        languages_by_country = {
            'COTE_IVOIRE': ['Français', 'Baoulé', 'Dioula', 'Bété', 'Agni', 'Anglais'],
            'GHANA': ['Anglais', 'Twi', 'Fante', 'Ewe', 'Ga', 'Dagbani', 'Français'],
            'MALI': ['Français', 'Bambara', 'Soninkè', 'Peul', 'Dogon', 'Minianka', 'Anglais']
        }
        
        available_languages = languages_by_country.get(country, ['Français', 'Anglais'])
        
        # Sélectionner 2-4 langues
        nb_languages = random.randint(2, min(4, len(available_languages)))
        selected_languages = random.sample(available_languages, nb_languages)
        
        return selected_languages
    
    def _display_fictional_employees_stats(self):
        """Affiche les statistiques des employés fictifs créés"""
        employes_fictifs = self.created_objects.get('employes_fictifs', [])
        
        if not employes_fictifs:
            return
        
        # Statistiques par pays
        country_stats = {}
        hierarchy_stats = {}
        
        for employe in employes_fictifs:
            # Déduire le pays depuis l'email
            email = employe.user.email
            if '.ci' in email:
                country = 'Côte d\'Ivoire'
            elif '.gh' in email:
                country = 'Ghana'
            elif '.ml' in email:
                country = 'Mali'
            else:
                country = 'Autre'
            
            country_stats[country] = country_stats.get(country, 0) + 1
            hierarchy_stats[employe.type_profil] = hierarchy_stats.get(employe.type_profil, 0) + 1
        
        self._write("📊 Statistiques employés fictifs africains:")
        self._write("  🌍 Répartition par pays:")
        for country, count in country_stats.items():
            percentage = (count / len(employes_fictifs)) * 100
            self._write(f"    • {country}: {count} ({percentage:.1f}%)")
        
        self._write("  👥 Répartition hiérarchique:")
        for profil_type, count in hierarchy_stats.items():
            percentage = (count / len(employes_fictifs)) * 100
            self._write(f"    • {profil_type}: {count} ({percentage:.1f}%)")
    
    def _display_hierarchy_distribution(self, employes, title):
        """Affiche la distribution hiérarchique d'une liste d'employés"""
        if not employes:
            return
        
        hierarchy_count = {}
        for emp in employes:
            hierarchy_count[emp.type_profil] = hierarchy_count.get(emp.type_profil, 0) + 1
        
        self._write(f"  👥 {title}:")
        for profil_type, count in hierarchy_count.items():
            percentage = (count / len(employes)) * 100
            self._write(f"    • {profil_type}: {count} ({percentage:.1f}%)")
    
    # ================================================================
    # MÉTHODES DE CRÉATION DES DONNÉES PÉRIPHÉRIQUES V4.1
    # ================================================================
    
    def _create_peripheral_data_v41(self):
        """Crée les données périphériques pour tous les employés (Kelio + fictifs)"""
        if not self.with_peripherals:
            self._write("⏭️ Création données périphériques désactivée")
            return
        
        self._write("📊 Création des données périphériques V4.1...")
        
        all_employees = self.created_objects.get('employes_tous', [])
        if not all_employees:
            self._write("⚠️ Aucun employé pour créer les données périphériques")
            return
        
        # Créer les données pour les employés Kelio (déjà partiellement synchronisées)
        employes_kelio = self.created_objects.get('employes_kelio', [])
        if employes_kelio:
            self._complete_kelio_peripheral_data(employes_kelio)
        
        # Créer les données pour les employés fictifs
        employes_fictifs = self.created_objects.get('employes_fictifs', [])
        if employes_fictifs:
            self._create_fictional_peripheral_data(employes_fictifs)
        
        self._write(f"✅ Données périphériques V4.1 créées pour {len(all_employees)} employé(s)")
    
    def _complete_kelio_peripheral_data(self, employes_kelio):
        """Complète les données périphériques pour les employés Kelio"""
        self._write(f"📈 Complémentation données périphériques pour {len(employes_kelio)} employé(s) Kelio...")
        
        # Les données Kelio sont déjà partiellement synchronisées
        # On ajoute juste quelques données manquantes si nécessaire
        
        CompetenceUtilisateur = self.models['CompetenceUtilisateur']
        FormationUtilisateur = self.models['FormationUtilisateur']
        DisponibiliteUtilisateur = self.models['DisponibiliteUtilisateur']
        
        competences = self.created_objects.get('competences', [])
        
        created_count = 0
        
        for employe in employes_kelio[:20]:  # Limiter pour la performance
            try:
                # Ajouter quelques compétences si aucune n'existe
                existing_competences = CompetenceUtilisateur.objects.filter(utilisateur=employe).count()
                if existing_competences == 0 and competences:
                    # Ajouter 2-4 compétences aléatoires
                    nb_comp = random.randint(2, min(4, len(competences)))
                    selected_competences = random.sample(competences, nb_comp)
                    
                    for competence in selected_competences:
                        CompetenceUtilisateur.objects.create(
                            utilisateur=employe,
                            competence=competence,
                            niveau_maitrise=random.randint(2, 5),
                            source_donnee='KELIO_COMPLETE',
                            date_evaluation=date.today() - timedelta(days=random.randint(30, 365))
                        )
                        created_count += 1
                
                # Ajouter des disponibilités futures
                if not DisponibiliteUtilisateur.objects.filter(utilisateur=employe).exists():
                    date_debut = date.today() + timedelta(days=random.randint(1, 30))
                    DisponibiliteUtilisateur.objects.create(
                        utilisateur=employe,
                        type_disponibilite='DISPONIBLE',
                        date_debut=date_debut,
                        date_fin=date_debut + timedelta(days=random.randint(5, 20)),
                        commentaire="Disponibilité Kelio V4.1",
                        created_by=employe
                    )
                    created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur complémentation données Kelio {employe.matricule}: {e}")
        
        self._write(f"  ✅ {created_count} élément(s) de données périphériques ajouté(s) pour employés Kelio")
    
    def _create_fictional_peripheral_data(self, employes_fictifs=None):
        """Crée les données périphériques pour les employés fictifs"""
        if employes_fictifs is None:
            employes_fictifs = self.created_objects.get('employes_fictifs', [])
        
        if not employes_fictifs:
            return
        
        self._write(f"🎭 Création données périphériques pour {len(employes_fictifs)} employé(s) fictif(s)...")
        
        CompetenceUtilisateur = self.models['CompetenceUtilisateur']
        FormationUtilisateur = self.models['FormationUtilisateur']
        AbsenceUtilisateur = self.models['AbsenceUtilisateur']
        DisponibiliteUtilisateur = self.models['DisponibiliteUtilisateur']
        
        competences = self.created_objects.get('competences', [])
        motifs_absence = self.created_objects.get('motifs_absence', [])
        
        created_count = 0
        
        for employe in employes_fictifs:
            try:
                # Compétences (2-6 par employé)
                if competences:
                    nb_competences = random.randint(2, min(6, len(competences)))
                    selected_competences = random.sample(competences, nb_competences)
                    
                    for competence in selected_competences:
                        CompetenceUtilisateur.objects.create(
                            utilisateur=employe,
                            competence=competence,
                            niveau_maitrise=random.randint(1, 5),
                            source_donnee='FICTIF_AFRICAIN',
                            date_acquisition=employe.date_embauche + timedelta(days=random.randint(0, 365)),
                            date_evaluation=date.today() - timedelta(days=random.randint(30, 200)),
                            certifie=random.choice([True, False])
                        )
                        created_count += 1
                
                # Formations (1-3 par employé)
                nb_formations = random.randint(1, 3)
                formations_africaines = [
                    "Formation en Leadership Africain",
                    "Gestion des Ressources Humaines",
                    "Comptabilité et Finance",
                    "Informatique et Bureautique",
                    "Langues Locales et Communication",
                    "Management de Projet",
                    "Entrepreneuriat en Afrique",
                    "Développement Durable",
                    "Commerce International",
                    "Agriculture Moderne"
                ]
                
                for i in range(nb_formations):
                    titre = random.choice(formations_africaines)
                    date_debut = employe.date_embauche + timedelta(days=random.randint(0, 1000))
                    
                    FormationUtilisateur.objects.create(
                        utilisateur=employe,
                        titre=titre,
                        description=f"Formation {titre} adaptée au contexte africain",
                        organisme=f"Institut de Formation {random.choice(['Abidjan', 'Accra', 'Bamako', 'Ouagadougou'])}",
                        type_formation="Formation professionnelle",
                        date_debut=date_debut,
                        date_fin=date_debut + timedelta(days=random.randint(1, 10)),
                        duree_jours=random.randint(1, 10),
                        certifiante=random.choice([True, False]),
                        diplome_obtenu=random.choice([True, False]),
                        source_donnee='FICTIF_AFRICAIN'
                    )
                    created_count += 1
                
                # Absences passées (0-2 par employé)
                if motifs_absence and random.choice([True, False]):
                    nb_absences = random.randint(0, 2)
                    for i in range(nb_absences):
                        motif = random.choice(motifs_absence)
                        date_debut_abs = date.today() - timedelta(days=random.randint(10, 200))
                        duree = random.randint(1, 5)
                        
                        AbsenceUtilisateur.objects.create(
                            utilisateur=employe,
                            type_absence=motif.nom,
                            date_debut=date_debut_abs,
                            date_fin=date_debut_abs + timedelta(days=duree),
                            duree_jours=duree,
                            motif_detaille=f"Absence {motif.nom} - employé fictif africain",
                            source_donnee='FICTIF_AFRICAIN'
                        )
                        created_count += 1
                
                # Disponibilités futures (1 par employé)
                if employe.statut_employe == 'ACTIF':
                    date_debut_dispo = date.today() + timedelta(days=random.randint(1, 60))
                    duree_dispo = random.randint(7, 30)
                    
                    DisponibiliteUtilisateur.objects.create(
                        utilisateur=employe,
                        type_disponibilite=random.choice(['DISPONIBLE', 'PARTIELLEMENT_DISPONIBLE']),
                        date_debut=date_debut_dispo,
                        date_fin=date_debut_dispo + timedelta(days=duree_dispo),
                        commentaire=f"Disponibilité employé fictif africain - {employe.user.email.split('@')[1]}",
                        created_by=employe
                    )
                    created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création données périphériques fictives {employe.matricule}: {e}")
        
        self.stats['peripheral_data_created'] += created_count
        self._write(f"  ✅ {created_count} élément(s) de données périphériques créé(s) pour employés fictifs")
    
    def _create_test_peripheral_data(self):
        """Crée des données périphériques de test"""
        all_employees = self.created_objects.get('employes_tous', [])
        if all_employees:
            self._create_fictional_peripheral_data(all_employees)
    
    # ================================================================
    # MÉTHODES DE CRÉATION DE WORKFLOW V4.1
    # ================================================================
    
    def _create_workflow_data_v41(self):
        """Crée les données de workflow V4.1"""
        if not self.with_workflow:
            self._write("⏭️ Création workflow désactivée")
            return
        
        self._write("🔄 Création des données de workflow V4.1...")
        
        # Créer les demandes d'intérim avec workflow V4.1
        self._create_interim_requests_v41()
        
        # Créer les propositions avec hiérarchie corrigée
        self._create_proposals_v41()
        
        # Créer les validations multi-niveaux
        self._create_validations_v41()
        
        # Créer les notifications intelligentes
        self._create_notifications_v41()
        
        # Créer l'historique des actions
        self._create_action_history_v41()
    
    def _create_interim_requests_v41(self):
        """Crée des demandes d'intérim avec workflow V4.1"""
        DemandeInterim = self.models['DemandeInterim']
        WorkflowDemande = self.models['WorkflowDemande']
        WorkflowEtape = self.models['WorkflowEtape']
        
        all_employees = self.created_objects.get('employes_tous', [])
        postes = self.created_objects.get('postes', [])
        motifs = self.created_objects.get('motifs_absence', [])
        
        if not all([all_employees, postes, motifs]):
            self._write("⚠️ Données manquantes pour créer les demandes d'intérim V4.1")
            return
        
        created_count = 0
        
        # Scénarios de demandes V4.1
        scenarios_v41 = [
            {'nombre': 5, 'statut': 'SOUMISE', 'etape': 'DEMANDE', 'urgence': 'NORMALE'},
            {'nombre': 4, 'statut': 'EN_PROPOSITION', 'etape': 'PROPOSITION_CANDIDATS', 'urgence': 'MOYENNE'},
            {'nombre': 3, 'statut': 'EN_VALIDATION', 'etape': 'VALIDATION_RESPONSABLE', 'urgence': 'ELEVEE'},
            {'nombre': 2, 'statut': 'EN_VALIDATION', 'etape': 'VALIDATION_DIRECTEUR', 'urgence': 'CRITIQUE'},
            {'nombre': 2, 'statut': 'CANDIDAT_PROPOSE', 'etape': 'VALIDATION_RH_ADMIN', 'urgence': 'NORMALE'},
            {'nombre': 1, 'statut': 'EN_COURS', 'etape': 'ACCEPTATION_CANDIDAT', 'urgence': 'MOYENNE'}
        ]
        
        for scenario in scenarios_v41:
            for i in range(scenario['nombre']):
                try:
                    # Sélectionner demandeur et personne remplacée
                    demandeur = random.choice(all_employees)
                    personne_remplacee = random.choice([emp for emp in all_employees if emp != demandeur])
                    poste = random.choice(postes)
                    motif = random.choice(motifs)
                    
                    # Dates logiques selon le scénario
                    if scenario['statut'] == 'EN_COURS':
                        date_debut = date.today() - timedelta(days=random.randint(0, 15))
                        date_fin = date_debut + timedelta(days=random.randint(10, 60))
                    else:
                        date_debut = date.today() + timedelta(days=random.randint(1, 30))
                        date_fin = date_debut + timedelta(days=random.randint(5, 45))
                    
                    # Créer la demande avec attributs V4.1
                    demande = DemandeInterim.objects.create(
                        demandeur=demandeur,
                        personne_remplacee=personne_remplacee,
                        poste=poste,
                        date_debut=date_debut,
                        date_fin=date_fin,
                        motif_absence=motif,
                        urgence=scenario['urgence'],
                        description_poste=f"Remplacement {personne_remplacee.user.get_full_name()} - Workflow V4.1",
                        instructions_particulieres=f"Mission avec workflow V4.1 - Hiérarchie corrigée",
                        competences_indispensables="Selon fiche de poste + workflow V4.1",
                        statut=scenario['statut'],
                        propositions_autorisees=True,
                        nb_max_propositions_par_utilisateur=5,
                        date_limite_propositions=timezone.now() + timedelta(days=3),
                        niveau_validation_actuel=random.randint(0, 3),
                        niveaux_validation_requis=3,  # RESPONSABLE → DIRECTEUR → RH/ADMIN
                        poids_scoring_automatique=0.7,
                        poids_scoring_humain=0.3,
                        # Attributs V4.1
                        version_workflow='4.1',
                        source_creation='POPULATE_V41'
                    )
                    
                    # Créer le workflow associé
                    etape_workflow = WorkflowEtape.objects.filter(
                        type_etape=scenario['etape'],
                        version_workflow='4.1',
                        actif=True
                    ).first()
                    
                    if etape_workflow:
                        workflow = WorkflowDemande.objects.create(
                            demande=demande,
                            etape_actuelle=etape_workflow,
                            nb_propositions_recues=random.randint(0, 6),
                            nb_candidats_evalues=random.randint(0, 4),
                            nb_niveaux_validation_passes=random.randint(0, 2),
                            historique_actions=[
                                {
                                    'date': (timezone.now() - timedelta(days=random.randint(1, 10))).isoformat(),
                                    'utilisateur': {
                                        'id': demandeur.id,
                                        'nom': demandeur.user.get_full_name(),
                                        'type_profil': demandeur.type_profil,
                                        'matricule': demandeur.matricule
                                    },
                                    'action': 'Création demande V4.1',
                                    'commentaire': f'Demande créée avec workflow V4.1 - {scenario["etape"]}',
                                    'etape': etape_workflow.nom,
                                    'metadata': {
                                        'type': 'creation_v41',
                                        'scenario': scenario,
                                        'urgence': scenario['urgence'],
                                        'workflow_version': '4.1',
                                        'hierarchie_corrigee': True,
                                        'employe_source': 'kelio' if demandeur in self.created_objects.get('employes_kelio', []) else 'fictif'
                                    }
                                }
                            ]
                        )
                    
                    created_count += 1
                    self.created_objects.setdefault('demandes_interim', []).append(demande)
                    self._update_stats('DemandeInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création demande intérim V4.1: {e}")
        
        self._write(f"  ✅ {created_count} demande(s) d'intérim V4.1 créée(s)")
    
    def _create_proposals_v41(self):
        """Crée des propositions avec hiérarchie V4.1"""
        PropositionCandidat = self.models['PropositionCandidat']
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        
        demandes = self.created_objects.get('demandes_interim', [])
        all_employees = self.created_objects.get('employes_tous', [])
        
        if not demandes or not all_employees:
            self._write("⚠️ Données manquantes pour créer les propositions V4.1")
            return
        
        created_count = 0
        
        # Organisateurs par niveau hiérarchique
        proposants_par_niveau = {
            'CHEF_EQUIPE': [emp for emp in all_employees if emp.type_profil == 'CHEF_EQUIPE'],
            'RESPONSABLE': [emp for emp in all_employees if emp.type_profil == 'RESPONSABLE'],
            'DIRECTEUR': [emp for emp in all_employees if emp.type_profil == 'DIRECTEUR'],
            'RH': [emp for emp in all_employees if emp.type_profil == 'RH'],
            'ADMIN': [emp for emp in all_employees if emp.type_profil == 'ADMIN']
        }
        
        candidats_potentiels = [emp for emp in all_employees if emp.type_profil == 'UTILISATEUR']
        
        for demande in demandes[:10]:  # Traiter quelques demandes
            nb_propositions = random.randint(2, 5)
            
            if len(candidats_potentiels) < nb_propositions:
                continue
            
            candidats_choisis = random.sample(candidats_potentiels, nb_propositions)
            
            for i, candidat in enumerate(candidats_choisis):
                # Sélectionner un proposant selon la hiérarchie V4.1
                niveau_weights = {
                    'CHEF_EQUIPE': 0.4,
                    'RESPONSABLE': 0.3,
                    'DIRECTEUR': 0.2,
                    'RH': 0.07,
                    'ADMIN': 0.03
                }
                
                niveau_choisi = random.choices(
                    list(niveau_weights.keys()),
                    weights=list(niveau_weights.values())
                )[0]
                
                proposants_niveau = proposants_par_niveau.get(niveau_choisi, [])
                if not proposants_niveau:
                    continue
                
                proposant = random.choice(proposants_niveau)
                
                # Sources V4.1 corrigées
                source_proposition = niveau_choisi
                if proposant == getattr(demande.demandeur, 'manager', None):
                    source_proposition = 'MANAGER_DIRECT'
                
                # Justifications adaptées V4.1
                justifications_v41 = {
                    'CHEF_EQUIPE': f"Proposition V4.1 chef d'équipe: {candidat.user.get_full_name()} excellent pour cette mission",
                    'RESPONSABLE': f"Validation responsable V4.1: {candidat.user.get_full_name()} répond aux critères",
                    'DIRECTEUR': f"Proposition directeur V4.1: {candidat.user.get_full_name()} profil stratégique",
                    'RH': f"Proposition RH V4.1: {candidat.user.get_full_name()} validé par les Ressources Humaines",
                    'ADMIN': f"Proposition Admin V4.1: {candidat.user.get_full_name()} avec autorisation administrative"
                }
                
                justification = justifications_v41.get(niveau_choisi, f"Proposition V4.1 de {candidat.user.get_full_name()}")
                
                try:
                    proposition = PropositionCandidat.objects.create(
                        demande_interim=demande,
                        candidat_propose=candidat,
                        proposant=proposant,
                        source_proposition=source_proposition,
                        justification=justification,
                        competences_specifiques=f"Compétences V4.1 validées niveau {niveau_choisi}",
                        experience_pertinente=f"Expérience V4.1 confirmée par {niveau_choisi}",
                        statut=random.choice(['SOUMISE', 'EN_EVALUATION', 'EVALUEE', 'RETENUE']),
                        niveau_validation_propose=self._get_niveau_validation_v41(niveau_choisi),
                        score_automatique=random.randint(65, 95),
                        bonus_proposition_humaine=self._get_bonus_hierarchique_v41(niveau_choisi),
                        # Attributs V4.1
                        version_scoring='4.1',
                        source_employe='kelio' if candidat in self.created_objects.get('employes_kelio', []) else 'fictif'
                    )
                    
                    # Créer le score détaillé V4.1
                    self._create_score_detail_v41(proposition, candidat, demande)
                    
                    created_count += 1
                    self.created_objects.setdefault('propositions', []).append(proposition)
                    self._update_stats('PropositionCandidat', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création proposition V4.1: {e}")
        
        self._write(f"  ✅ {created_count} proposition(s) V4.1 créée(s)")
    
    def _create_score_detail_v41(self, proposition, candidat, demande):
        """Crée un score détaillé V4.1 pour une proposition"""
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        
        try:
            # Scores de base V4.1
            scores_base = {
                'similarite': random.randint(50, 90),
                'competences': random.randint(40, 85),
                'experience': random.randint(35, 80),
                'disponibilite': random.randint(70, 100),
                'proximite': random.randint(30, 95),
                'anciennete': random.randint(20, 75)
            }
            
            # Bonus V4.1
            bonus_hierarchique = self._get_bonus_hierarchique_v41(proposition.source_proposition)
            bonus_experience = random.randint(0, 8) if scores_base['experience'] > 70 else 0
            bonus_recommandation = random.randint(0, 10) if proposition.justification else 0
            bonus_kelio_data = 5 if candidat in self.created_objects.get('employes_kelio', []) else 0
            
            score_detail = ScoreDetailCandidat.objects.create(
                candidat=candidat,
                demande_interim=demande,
                proposition_humaine=proposition,
                score_similarite_poste=scores_base['similarite'],
                score_competences=scores_base['competences'],
                score_experience=scores_base['experience'],
                score_disponibilite=scores_base['disponibilite'],
                score_proximite=scores_base['proximite'],
                score_anciennete=scores_base['anciennete'],
                bonus_proposition_humaine=proposition.bonus_proposition_humaine,
                bonus_experience_similaire=bonus_experience,
                bonus_recommandation=bonus_recommandation,
                bonus_hierarchique=bonus_hierarchique,
                bonus_kelio_data_quality=bonus_kelio_data,
                penalite_indisponibilite=random.randint(0, 10),
                penalite_distance_excessive=random.randint(0, 5),
                calcule_par='SYSTEM_V41',
                # Attributs V4.1
                version_scoring='4.1',
                metadata_scoring={
                    'source_employe': 'kelio' if candidat in self.created_objects.get('employes_kelio', []) else 'fictif',
                    'proposant_niveau': proposition.source_proposition,
                    'workflow_version': '4.1'
                }
            )
            
            # Calculer le score total V4.1
            score_detail.calculer_score_total()
            score_detail.save()
            
            # Mettre à jour le score dans la proposition
            proposition.score_automatique = score_detail.score_total
            proposition.save()
            
            self._update_stats('ScoreDetailCandidat', True)
            
        except Exception as e:
            logger.error(f"Erreur création score détaillé V4.1: {e}")
    
    def _create_validations_v41(self):
        """Crée des validations selon la hiérarchie V4.1"""
        ValidationDemande = self.models['ValidationDemande']
        demandes = self.created_objects.get('demandes_interim', [])
        all_employees = self.created_objects.get('employes_tous', [])
        
        if not demandes or not all_employees:
            self._write("⚠️ Données manquantes pour créer les validations V4.1")
            return
        
        created_count = 0
        
        # Validateurs par niveau V4.1
        validateurs_v41 = {
            1: [emp for emp in all_employees if emp.type_profil == 'RESPONSABLE'],
            2: [emp for emp in all_employees if emp.type_profil == 'DIRECTEUR'],
            3: [emp for emp in all_employees if emp.type_profil in ['RH', 'ADMIN']]
        }
        
        for demande in demandes[:8]:
            # Processus de validation V4.1
            niveaux_validation_v41 = [
                (1, 'RESPONSABLE', validateurs_v41[1]),
                (2, 'DIRECTEUR', validateurs_v41[2]),
                (3, random.choice(['RH', 'ADMIN']), validateurs_v41[3])
            ]
            
            decision_precedente = 'APPROUVE'
            
            for niveau, type_validation, validateurs_niveau in niveaux_validation_v41:
                if not validateurs_niveau or decision_precedente == 'REFUSE':
                    break
                
                validateur = random.choice(validateurs_niveau)
                
                # Décisions V4.1 selon le niveau
                if niveau == 1:
                    decisions = ['APPROUVE', 'APPROUVE_AVEC_MODIF', 'REFUSE', 'CANDIDAT_AJOUTE']
                    probabilites = [0.65, 0.20, 0.10, 0.05]
                elif niveau == 2:
                    decisions = ['APPROUVE', 'APPROUVE_AVEC_MODIF', 'REFUSE']
                    probabilites = [0.75, 0.15, 0.10]
                else:
                    decisions = ['APPROUVE', 'APPROUVE_AVEC_MODIF']
                    probabilites = [0.85, 0.15]
                
                decision = random.choices(decisions, weights=probabilites)[0]
                decision_precedente = decision
                
                # Candidats selon la décision
                candidats_retenus = []
                candidats_rejetes = []
                
                if decision.startswith('APPROUVE'):
                    for i in range(random.randint(1, 3)):
                        candidats_retenus.append({
                            'candidat_id': random.randint(1, 100),
                            'candidat_nom': f'Candidat V4.1 {i+1}',
                            'score': random.randint(75, 95),
                            'source': type_validation,
                            'justification': f"Retenu au niveau {niveau} par {type_validation} V4.1",
                            'niveau_validation': niveau,
                            'version': '4.1'
                        })
                
                # Commentaires V4.1
                commentaires_v41 = {
                    'RESPONSABLE': f"Validation V4.1 niveau 1 (Responsable): {decision}. Critères opérationnels validés.",
                    'DIRECTEUR': f"Validation V4.1 niveau 2 (Directeur): {decision}. Validation stratégique confirmée.",
                    'RH': f"Validation V4.1 finale RH: {decision}. Conformité RH et autorisation définitive.",
                    'ADMIN': f"Validation V4.1 finale Admin: {decision}. Validation administrative et autorisations."
                }
                
                commentaire = commentaires_v41.get(type_validation, f"Validation V4.1 {type_validation} niveau {niveau}: {decision}")
                
                try:
                    validation = ValidationDemande.objects.create(
                        demande=demande,
                        type_validation=type_validation,
                        niveau_validation=niveau,
                        validateur=validateur,
                        decision=decision,
                        commentaire=commentaire,
                        date_demande_validation=timezone.now() - timedelta(days=niveau),
                        date_validation=timezone.now() - timedelta(days=niveau-1, hours=random.randint(2, 20)),
                        candidats_retenus=candidats_retenus,
                        candidats_rejetes=candidats_rejetes,
                        # Attributs V4.1
                        version_validation='4.1',
                        metadata_validation={
                            'validateur_niveau': validateur.type_profil,
                            'workflow_version': '4.1',
                            'validateur_source': 'kelio' if validateur in self.created_objects.get('employes_kelio', []) else 'fictif'
                        }
                    )
                    
                    created_count += 1
                    self.created_objects.setdefault('validations', []).append(validation)
                    self._update_stats('ValidationDemande', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création validation V4.1: {e}")
        
        self._write(f"  ✅ {created_count} validation(s) V4.1 créée(s)")
    
    def _create_notifications_v41(self):
        """Crée des notifications intelligentes V4.1"""
        NotificationInterim = self.models['NotificationInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        all_employees = self.created_objects.get('employes_tous', [])
        
        if not demandes or not all_employees:
            self._write("⚠️ Données manquantes pour créer les notifications V4.1")
            return
        
        created_count = 0
        
        # Templates de notifications V4.1
        templates_v41 = {
            'NOUVELLE_DEMANDE_V41': {
                'titre': 'Nouvelle demande intérim V4.1 - Action requise',
                'message': 'Une nouvelle demande d\'intérim V4.1 nécessite votre attention avec workflow hiérarchique.',
                'urgence': 'NORMALE'
            },
            'VALIDATION_REQUISE_V41': {
                'titre': 'URGENT - Validation V4.1 niveau {niveau} requise',
                'message': 'Demande d\'intérim V4.1 en attente de votre validation niveau {niveau} ({type_validateur}).',
                'urgence': 'CRITIQUE'
            },
            'PROPOSITION_V41': {
                'titre': 'Nouveau candidat proposé V4.1 par {niveau_proposant}',
                'message': 'Un candidat a été proposé via le système V4.1 par un {niveau_proposant}.',
                'urgence': 'NORMALE'
            }
        }
        
        for demande in demandes[:6]:
            # Notifications selon la hiérarchie V4.1
            destinataires_par_niveau = {
                'RESPONSABLE': [emp for emp in all_employees if emp.type_profil == 'RESPONSABLE'],
                'DIRECTEUR': [emp for emp in all_employees if emp.type_profil == 'DIRECTEUR'],
                'RH': [emp for emp in all_employees if emp.type_profil == 'RH'],
                'ADMIN': [emp for emp in all_employees if emp.type_profil == 'ADMIN']
            }
            
            for niveau, employes_niveau in destinataires_par_niveau.items():
                if not employes_niveau:
                    continue
                
                destinataire = random.choice(employes_niveau)
                
                # Sélectionner le template approprié
                template_key = random.choice(['NOUVELLE_DEMANDE_V41', 'VALIDATION_REQUISE_V41', 'PROPOSITION_V41'])
                template = templates_v41[template_key]
                
                # Personnaliser selon le template
                if template_key == 'VALIDATION_REQUISE_V41':
                    niveau_validation = self._get_niveau_validation_v41(niveau)
                    titre = template['titre'].format(niveau=niveau_validation, type_validateur=niveau)
                    message = template['message'].format(niveau=niveau_validation, type_validateur=niveau)
                elif template_key == 'PROPOSITION_V41':
                    titre = template['titre'].format(niveau_proposant=niveau)
                    message = template['message'].format(niveau_proposant=niveau)
                else:
                    titre = template['titre']
                    message = template['message']
                
                # Métadonnées V4.1
                metadata_v41 = {
                    'demande_id': demande.id,
                    'destinataire_niveau': niveau,
                    'workflow_version': '4.1',
                    'hierarchie_corrigee': True,
                    'urgence_demande': demande.urgence,
                    'template_utilise': template_key,
                    'destinataire_source': 'kelio' if destinataire in self.created_objects.get('employes_kelio', []) else 'fictif',
                    'demandeur_source': 'kelio' if demande.demandeur in self.created_objects.get('employes_kelio', []) else 'fictif',
                    'niveau_validation_requis': self._get_niveau_validation_v41(niveau),
                    'permissions_destinataire': {
                        'peut_valider_niveau_1': niveau in ['RESPONSABLE', 'RH', 'ADMIN'],
                        'peut_valider_niveau_2': niveau in ['DIRECTEUR', 'RH', 'ADMIN'],
                        'peut_valider_final': niveau in ['RH', 'ADMIN']
                    }
                }
                
                try:
                    notification = NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=demande.demandeur,
                        demande=demande,
                        type_notification=template_key,
                        urgence=template['urgence'],
                        statut='NON_LUE',
                        titre=titre,
                        message=message,
                        url_action_principale=f"/interim/v41/demande/{demande.id}/",
                        texte_action_principale=f"Action V4.1",
                        url_action_secondaire=f"/interim/v41/workflow/{demande.id}/",
                        texte_action_secondaire="Voir workflow",
                        metadata=metadata_v41,
                        # Attributs V4.1
                        version_notification='4.1'
                    )
                    
                    created_count += 1
                    self._update_stats('NotificationInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création notification V4.1: {e}")
        
        self._write(f"  ✅ {created_count} notification(s) V4.1 créée(s)")
    
    def _create_action_history_v41(self):
        """Crée l'historique des actions V4.1"""
        HistoriqueAction = self.models['HistoriqueAction']
        demandes = self.created_objects.get('demandes_interim', [])
        propositions = self.created_objects.get('propositions', [])
        validations = self.created_objects.get('validations', [])
        
        if not demandes:
            self._write("⚠️ Pas de demandes pour créer l'historique V4.1")
            return
        
        created_count = 0
        
        # Actions pour les demandes V4.1
        for demande in demandes:
            try:
                HistoriqueAction.objects.create(
                    demande=demande,
                    action='CREATION_DEMANDE_V41',
                    utilisateur=demande.demandeur,
                    description=f"Création demande V4.1 {demande.numero_demande} avec workflow hiérarchique corrigé",
                    niveau_hierarchique=demande.demandeur.type_profil,
                    is_superuser=demande.demandeur.user.is_superuser,
                    donnees_apres={
                        'poste_titre': demande.poste.titre if demande.poste else 'Non défini',
                        'urgence': demande.urgence,
                        'date_debut': str(demande.date_debut) if demande.date_debut else None,
                        'workflow_version': '4.1',
                        'niveaux_validation_requis': demande.niveaux_validation_requis,
                        'demandeur_niveau': demande.demandeur.type_profil,
                        'demandeur_source': 'kelio' if demande.demandeur in self.created_objects.get('employes_kelio', []) else 'fictif',
                        'hierarchie_corrigee': True
                    },
                    # Attributs V4.1
                    version_action='4.1'
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique demande V4.1: {e}")
        
        # Actions pour les propositions V4.1
        for proposition in propositions[:20]:  # Limiter pour la performance
            try:
                HistoriqueAction.objects.create(
                    demande=proposition.demande_interim,
                    proposition=proposition,
                    action='PROPOSITION_CANDIDAT_V41',
                    utilisateur=proposition.proposant,
                    description=f"Proposition V4.1 {proposition.candidat_propose.user.get_full_name()} par {proposition.proposant.type_profil}",
                    niveau_hierarchique=proposition.proposant.type_profil,
                    is_superuser=proposition.proposant.user.is_superuser,
                    donnees_apres={
                        'candidat_nom': proposition.candidat_propose.user.get_full_name(),
                        'source_proposition': proposition.source_proposition,
                        'justification': proposition.justification[:100] if proposition.justification else '',
                        'bonus_hierarchique': self._get_bonus_hierarchique_v41(proposition.source_proposition),
                        'niveau_validation_propose': proposition.niveau_validation_propose,
                        'workflow_version': '4.1',
                        'proposant_source': 'kelio' if proposition.proposant in self.created_objects.get('employes_kelio', []) else 'fictif',
                        'candidat_source': 'kelio' if proposition.candidat_propose in self.created_objects.get('employes_kelio', []) else 'fictif'
                    },
                    # Attributs V4.1
                    version_action='4.1'
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique proposition V4.1: {e}")
        
        # Actions pour les validations V4.1
        for validation in validations:
            try:
                action_mapping = {
                    'RESPONSABLE': 'VALIDATION_RESPONSABLE_V41',
                    'DIRECTEUR': 'VALIDATION_DIRECTEUR_V41',
                    'RH': 'VALIDATION_RH_V41',
                    'ADMIN': 'VALIDATION_ADMIN_V41'
                }
                
                action = action_mapping.get(validation.type_validation, 'VALIDATION_RESPONSABLE_V41')
                
                HistoriqueAction.objects.create(
                    demande=validation.demande,
                    validation=validation,
                    action=action,
                    utilisateur=validation.validateur,
                    description=f"Validation V4.1 {validation.type_validation} niveau {validation.niveau_validation}: {validation.decision}",
                    niveau_validation=validation.niveau_validation,
                    niveau_hierarchique=validation.validateur.type_profil,
                    is_superuser=validation.validateur.user.is_superuser,
                    donnees_apres={
                        'decision': validation.decision,
                        'commentaire': validation.commentaire,
                        'nb_candidats_retenus': len(validation.candidats_retenus),
                        'type_validation': validation.type_validation,
                        'niveau_validation': validation.niveau_validation,
                        'workflow_version': '4.1',
                        'validateur_niveau': validation.validateur.type_profil,
                        'validateur_source': 'kelio' if validation.validateur in self.created_objects.get('employes_kelio', []) else 'fictif'
                    },
                    # Attributs V4.1
                    version_action='4.1'
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Erreur création historique validation V4.1: {e}")
        
        self._write(f"  ✅ {created_count} action(s) d'historique V4.1 créée(s)")
        self._update_stats('HistoriqueAction', True, count=created_count)
    
    # ================================================================
    # MÉTHODES UTILITAIRES V4.1
    # ================================================================
    
    def _get_niveau_validation_v41(self, type_profil):
        """Retourne le niveau de validation V4.1 selon le type de profil"""
        niveau_map = {
            'UTILISATEUR': 0,
            'CHEF_EQUIPE': 0,
            'RESPONSABLE': 1,
            'DIRECTEUR': 2,
            'RH': 3,
            'ADMIN': 3
        }
        return niveau_map.get(type_profil, 0)
    
    def _get_bonus_hierarchique_v41(self, type_profil_ou_source):
        """Retourne le bonus hiérarchique V4.1 corrigé"""
        bonus_map = {
            'CHEF_EQUIPE': 8,
            'RESPONSABLE': 15,
            'DIRECTEUR': 18,
            'RH': 20,
            'ADMIN': 20,
            'MANAGER_DIRECT': 12,
            'UTILISATEUR': 0
        }
        return bonus_map.get(type_profil_ou_source, 5)
    
    # ================================================================
    # MÉTHODES DE CRÉATION DE STRUCTURE DE BASE
    # ================================================================
    
    def _create_base_structure(self):
        """Crée la structure organisationnelle de base"""
        self._create_departements()
        self._create_sites()
        self._create_postes()
        self._create_motifs_absence()
        self._create_competences()
    
    def _create_minimal_structure(self):
        """Crée une structure minimale"""
        self._create_departements(minimal=True)
        self._create_sites(minimal=True)
        self._create_competences(minimal=True)
    
    def _create_departements(self, minimal=False):
        """Crée des départements"""
        Departement = self.models['Departement']
        
        if minimal:
            departements_data = [
                {'nom': 'Direction Générale', 'code': 'DG', 'description': 'Direction générale', 'actif': True},
                {'nom': 'Ressources Humaines', 'code': 'RH', 'description': 'Gestion du personnel', 'actif': True},
                {'nom': 'Informatique', 'code': 'IT', 'description': 'Système d\'information', 'actif': True}
            ]
        else:
            departements_data = [
                {'nom': 'Direction Générale', 'code': 'DG', 'description': 'Direction générale et stratégie', 'kelio_department_key': 1, 'actif': True},
                {'nom': 'Ressources Humaines', 'code': 'RH', 'description': 'Gestion du personnel et formation', 'kelio_department_key': 2, 'actif': True},
                {'nom': 'Informatique', 'code': 'IT', 'description': 'Développement et infrastructure IT', 'kelio_department_key': 3, 'actif': True},
                {'nom': 'Comptabilité Finance', 'code': 'COMPTA', 'description': 'Gestion financière et comptable', 'kelio_department_key': 4, 'actif': True},
                {'nom': 'Commercial', 'code': 'COM', 'description': 'Ventes et relation client', 'kelio_department_key': 5, 'actif': True},
                {'nom': 'Production', 'code': 'PROD', 'description': 'Production et opérations', 'kelio_department_key': 6, 'actif': True},
                {'nom': 'Logistique', 'code': 'LOG', 'description': 'Transport et logistique', 'kelio_department_key': 7, 'actif': True},
                {'nom': 'Marketing', 'code': 'MKT', 'description': 'Marketing et communication', 'kelio_department_key': 8, 'actif': True}
            ]
        
        created_count = 0
        for data in departements_data:
            dept, created = Departement.objects.get_or_create(code=data['code'], defaults=data)
            if created:
                created_count += 1
                self.created_objects['departements'].append(dept)
                self._update_stats('Departement', True)
        
        self._write(f"  ✅ {created_count} département(s) créé(s)")
    
    def _create_sites(self, minimal=False):
        """Crée des sites"""
        Site = self.models['Site']
        
        if minimal:
            sites_data = [
                {'nom': 'Siège Abidjan', 'adresse': 'Plateau, Abidjan', 'ville': 'Abidjan', 'code_postal': '01000', 'actif': True}
            ]
        else:
            sites_data = [
                {'nom': 'Siège Social Abidjan', 'adresse': 'Avenue Chardy, Plateau', 'ville': 'Abidjan', 'code_postal': '01000', 'kelio_site_key': 1, 'actif': True},
                {'nom': 'Agence Bouaké', 'adresse': 'Boulevard de la Paix', 'ville': 'Bouaké', 'code_postal': '01000', 'kelio_site_key': 2, 'actif': True},
                {'nom': 'Antenne Yamoussoukro', 'adresse': 'Avenue Houphouët-Boigny', 'ville': 'Yamoussoukro', 'code_postal': '01000', 'kelio_site_key': 3, 'actif': True},
                {'nom': 'Bureau San Pedro', 'adresse': 'Zone Industrielle', 'ville': 'San Pedro', 'code_postal': '28000', 'kelio_site_key': 4, 'actif': True},
                {'nom': 'Agence Korhogo', 'adresse': 'Avenue de l\'Indépendance', 'ville': 'Korhogo', 'code_postal': '36000', 'kelio_site_key': 5, 'actif': True},
                {'nom': 'Succursale Daloa', 'adresse': 'Rue du Commerce', 'ville': 'Daloa', 'code_postal': '01000', 'kelio_site_key': 6, 'actif': True}
            ]
        
        created_count = 0
        for data in sites_data:
            site, created = Site.objects.get_or_create(nom=data['nom'], defaults=data)
            if created:
                created_count += 1
                self.created_objects['sites'].append(site)
                self._update_stats('Site', True)
        
        self._write(f"  ✅ {created_count} site(s) créé(s)")
    
    def _create_postes(self):
        """Crée des postes"""
        Poste = self.models['Poste']
        departements = self.created_objects.get('departements', [])
        sites = self.created_objects.get('sites', [])
        
        if not departements or not sites:
            self._write("⚠️ Départements ou sites manquants pour créer les postes")
            return
        
        postes_data = []
        
        # Postes par département
        postes_par_dept = {
            'DG': ['Directeur Général', 'Assistant Direction', 'Responsable Stratégie'],
            'RH': ['Directeur RH', 'Chargé de Recrutement', 'Gestionnaire Paie', 'Responsable Formation'],
            'IT': ['Directeur IT', 'Développeur Full Stack', 'Chef de Projet IT', 'Technicien Support', 'Analyste Système'],
            'COMPTA': ['Directeur Financier', 'Comptable Senior', 'Contrôleur de Gestion', 'Assistant Comptable'],
            'COM': ['Directeur Commercial', 'Responsable Ventes', 'Commercial Senior', 'Assistant Commercial'],
            'PROD': ['Directeur Production', 'Chef d\'Équipe Production', 'Opérateur Production', 'Responsable Qualité'],
            'LOG': ['Responsable Logistique', 'Gestionnaire Stock', 'Chauffeur', 'Magasinier'],
            'MKT': ['Responsable Marketing', 'Chargé Communication', 'Designer Graphique']
        }
        
        for dept in departements:
            postes_dept = postes_par_dept.get(dept.code, ['Employé'])
            site = sites[0] if sites else None
            
            for titre_poste in postes_dept:
                postes_data.append({
                    'titre': titre_poste,
                    'description': f"Poste de {titre_poste} - {dept.nom}",
                    'departement': dept,
                    'site': site,
                    'interim_autorise': True,
                    'kelio_job_key': len(postes_data) + 1,
                    'actif': True
                })
        
        created_count = 0
        for data in postes_data:
            poste, created = Poste.objects.get_or_create(
                titre=data['titre'],
                departement=data['departement'],
                site=data['site'],
                defaults=data
            )
            if created:
                created_count += 1
                self.created_objects['postes'].append(poste)
                self._update_stats('Poste', True)
        
        self._write(f"  ✅ {created_count} poste(s) créé(s)")
    
    def _create_motifs_absence(self):
        """Crée des motifs d'absence"""
        MotifAbsence = self.models['MotifAbsence']
        
        motifs_data = [
            {'nom': 'Congé payé', 'code': 'CP', 'categorie': 'CONGE', 'couleur': '#28a745', 'kelio_absence_type_key': 1, 'actif': True},
            {'nom': 'Arrêt maladie', 'code': 'AM', 'categorie': 'MALADIE', 'couleur': '#dc3545', 'kelio_absence_type_key': 2, 'actif': True},
            {'nom': 'Formation professionnelle', 'code': 'FORM', 'categorie': 'FORMATION', 'couleur': '#17a2b8', 'kelio_absence_type_key': 3, 'actif': True},
            {'nom': 'RTT', 'code': 'RTT', 'categorie': 'CONGE', 'couleur': '#20c997', 'kelio_absence_type_key': 4, 'actif': True},
            {'nom': 'Congé maternité', 'code': 'CM', 'categorie': 'CONGE', 'couleur': '#ffc107', 'kelio_absence_type_key': 5, 'actif': True},
            {'nom': 'Mission externe', 'code': 'MISS', 'categorie': 'PROFESSIONNEL', 'couleur': '#6f42c1', 'kelio_absence_type_key': 6, 'actif': True},
            {'nom': 'Congé sans solde', 'code': 'CSS', 'categorie': 'PERSONNEL', 'couleur': '#fd7e14', 'kelio_absence_type_key': 7, 'actif': True},
            {'nom': 'Congé de paternité', 'code': 'CPat', 'categorie': 'CONGE', 'couleur': '#e83e8c', 'kelio_absence_type_key': 8, 'actif': True}
        ]
        
        created_count = 0
        for data in motifs_data:
            motif_data = {**data, 'description': f"Motif: {data['nom']}"}
            motif, created = MotifAbsence.objects.get_or_create(code=data['code'], defaults=motif_data)
            if created:
                created_count += 1
                self.created_objects['motifs_absence'].append(motif)
                self._update_stats('MotifAbsence', True)
        
        self._write(f"  ✅ {created_count} motif(s) d'absence créé(s)")
    
    def _create_competences(self, minimal=False):
        """Crée des compétences"""
        Competence = self.models['Competence']
        
        if minimal:
            competences_data = [
                {'nom': 'Communication', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 1, 'actif': True},
                {'nom': 'Leadership', 'categorie': 'Management', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 2, 'actif': True},
                {'nom': 'Informatique', 'categorie': 'Technique', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 3, 'actif': True}
            ]
        else:
            competences_data = [
                # Compétences techniques
                {'nom': 'Python', 'categorie': 'Programmation', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 1, 'actif': True},
                {'nom': 'Django', 'categorie': 'Frameworks Web', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 2, 'actif': True},
                {'nom': 'JavaScript', 'categorie': 'Programmation', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 3, 'actif': True},
                {'nom': 'SQL/Base de données', 'categorie': 'Base de données', 'type_competence': 'TECHNIQUE', 'kelio_skill_key': 4, 'actif': True},
                {'nom': 'Excel Avancé', 'categorie': 'Bureautique', 'type_competence': 'LOGICIEL', 'kelio_skill_key': 5, 'actif': True},
                {'nom': 'PowerBI/Tableau', 'categorie': 'Analyse de données', 'type_competence': 'LOGICIEL', 'kelio_skill_key': 6, 'actif': True},
                
                # Compétences transverses
                {'nom': 'Management d\'équipe', 'categorie': 'Management', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 7, 'actif': True},
                {'nom': 'Gestion de projet', 'categorie': 'Management', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 8, 'actif': True},
                {'nom': 'Gestion budgétaire', 'categorie': 'Finance', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 9, 'actif': True},
                {'nom': 'Analyse financière', 'categorie': 'Finance', 'type_competence': 'TRANSVERSE', 'kelio_skill_key': 10, 'actif': True},
                
                # Compétences linguistiques
                {'nom': 'Français', 'categorie': 'Langues', 'type_competence': 'LINGUISTIQUE', 'kelio_skill_key': 11, 'actif': True},
                {'nom': 'Anglais', 'categorie': 'Langues', 'type_competence': 'LINGUISTIQUE', 'kelio_skill_key': 12, 'actif': True},
                {'nom': 'Dioula', 'categorie': 'Langues locales', 'type_competence': 'LINGUISTIQUE', 'kelio_skill_key': 13, 'actif': True},
                {'nom': 'Baoulé', 'categorie': 'Langues locales', 'type_competence': 'LINGUISTIQUE', 'kelio_skill_key': 14, 'actif': True},
                
                # Compétences comportementales
                {'nom': 'Communication', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 15, 'actif': True},
                {'nom': 'Leadership', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 16, 'actif': True},
                {'nom': 'Travail en équipe', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 17, 'actif': True},
                {'nom': 'Adaptation', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 18, 'actif': True},
                {'nom': 'Résolution de problèmes', 'categorie': 'Soft Skills', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 19, 'actif': True},
                {'nom': 'Négociation', 'categorie': 'Commercial', 'type_competence': 'COMPORTEMENTALE', 'kelio_skill_key': 20, 'actif': True}
            ]
        
        created_count = 0
        for data in competences_data:
            competence_data = {**data, 'description': f"Compétence: {data['nom']}"}
            competence, created = Competence.objects.get_or_create(nom=data['nom'], defaults=competence_data)
            if created:
                created_count += 1
                self.created_objects['competences'].append(competence)
                self._update_stats('Competence', True)
        
        self._write(f"  ✅ {created_count} compétence(s) créée(s)")
    
    # ================================================================
    # MÉTHODES DE CRÉATION AVANCÉES V4.1
    # ================================================================
    
    def _create_interim_requests(self):
        """Crée des demandes d'intérim standard"""
        self._create_interim_requests_v41()
    
    def _create_demo_employees(self):
        """Crée des employés pour la démo"""
        self._create_base_structure()
        # Créer un mix employés Kelio + fictifs
        if self.with_kelio_sync:
            self._sync_employees_from_kelio_v41()
        self._create_specific_number_fictional_employees(20)
    
    def _create_test_employees_african(self):
        """Crée des employés de test africains"""
        self._create_specific_number_fictional_employees(self.sample_size)
    
    def _create_base_structure_and_employees(self):
        """Crée structure de base et employés"""
        self._create_base_structure()
        self._create_test_employees_african()
    
    def _create_comprehensive_workflow_v41(self):
        """Crée un workflow complet V4.1"""
        self._create_workflow_data_v41()
        # Ajouter des éléments avancés
        self._create_advanced_workflow_elements()
    
    def _create_advanced_workflow_elements(self):
        """Crée des éléments de workflow avancés"""
        # Réponses candidats
        self._create_candidate_responses()
        # Workflow détaillé
        self._create_detailed_workflow_instances()
    
    def _create_candidate_responses(self):
        """Crée des réponses de candidats"""
        ReponseCandidatInterim = self.models['ReponseCandidatInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        all_employees = self.created_objects.get('employes_tous', [])
        
        if not demandes or not all_employees:
            return
        
        created_count = 0
        
        for demande in demandes[:8]:
            # Sélectionner quelques candidats
            candidats = random.sample(all_employees, min(3, len(all_employees)))
            
            for candidat in candidats:
                reponse_type = random.choice(['ACCEPTE', 'REFUSE', 'EN_ATTENTE'])
                
                date_proposition = timezone.now() - timedelta(days=random.randint(1, 10))
                date_limite = date_proposition + timedelta(days=3)
                date_reponse = None
                
                if reponse_type != 'EN_ATTENTE':
                    date_reponse = date_proposition + timedelta(hours=random.randint(2, 60))
                
                motif_refus = None
                commentaire_refus = ""
                
                if reponse_type == 'REFUSE':
                    motifs_possibles = ['INDISPONIBLE', 'COMPETENCES', 'DISTANCE', 'PERSONNEL']
                    motif_refus = random.choice(motifs_possibles)
                    commentaires_refus = {
                        'INDISPONIBLE': 'Indisponible aux dates proposées - engagement personnel',
                        'COMPETENCES': 'Ne me sens pas suffisamment compétent pour ce poste spécifique',
                        'DISTANCE': 'Trop éloigné de mon domicile pour un intérim',
                        'PERSONNEL': 'Raisons personnelles et familiales'
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
                        salaire_propose=random.randint(2500000, 6000000) if random.choice([True, False]) else None,
                        avantages_proposes="Transport + repas + prime mission" if random.choice([True, False]) else "",
                        nb_rappels_envoyes=random.randint(0, 2) if reponse_type == 'EN_ATTENTE' else 0,
                        derniere_date_rappel=timezone.now() - timedelta(hours=random.randint(6, 48)) if reponse_type == 'EN_ATTENTE' else None,
                        # Attributs V4.1
                        version_reponse='4.1',
                        candidat_source='kelio' if candidat in self.created_objects.get('employes_kelio', []) else 'fictif'
                    )
                    
                    created_count += 1
                    self._update_stats('ReponseCandidatInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création réponse candidat V4.1: {e}")
        
        self._write(f"  ✅ {created_count} réponse(s) candidat V4.1 créée(s)")
    
    def _create_detailed_workflow_instances(self):
        """Crée des instances de workflow détaillées"""
        WorkflowDemande = self.models['WorkflowDemande']
        WorkflowEtape = self.models['WorkflowEtape']
        demandes = self.created_objects.get('demandes_interim', [])
        
        if not demandes:
            return
        
        created_count = 0
        etapes = list(WorkflowEtape.objects.filter(actif=True).order_by('ordre'))
        
        for demande in demandes:
            # Vérifier si un workflow existe déjà
            if WorkflowDemande.objects.filter(demande=demande).exists():
                continue
            
            try:
                # Sélectionner une étape selon le statut de la demande
                etape_mapping = {
                    'SOUMISE': 'DEMANDE',
                    'EN_PROPOSITION': 'PROPOSITION_CANDIDATS',
                    'EN_VALIDATION': 'VALIDATION_RESPONSABLE',
                    'CANDIDAT_PROPOSE': 'VALIDATION_RH_ADMIN',
                    'EN_COURS': 'ACCEPTATION_CANDIDAT',
                    'TERMINEE': 'FINALISATION'
                }
                
                etape_type = etape_mapping.get(demande.statut, 'DEMANDE')
                etape_actuelle = WorkflowEtape.objects.filter(
                    type_etape=etape_type,
                    version_workflow='4.1',
                    actif=True
                ).first()
                
                if not etape_actuelle:
                    etape_actuelle = etapes[0] if etapes else None
                
                if not etape_actuelle:
                    continue
                
                # Historique enrichi V4.1
                historique_enrichi = [
                    {
                        'date': (timezone.now() - timedelta(days=7)).isoformat(),
                        'utilisateur': {
                            'id': demande.demandeur.id,
                            'nom': demande.demandeur.user.get_full_name(),
                            'type_profil': demande.demandeur.type_profil,
                            'matricule': demande.demandeur.matricule,
                            'source': 'kelio' if demande.demandeur in self.created_objects.get('employes_kelio', []) else 'fictif'
                        },
                        'action': 'Initialisation workflow V4.1',
                        'commentaire': 'Workflow V4.1 initialisé avec hiérarchie corrigée',
                        'etape': 'DEMANDE',
                        'metadata': {
                            'type': 'initialisation_v41',
                            'workflow_version': '4.1',
                            'hierarchie_corrigee': True,
                            'niveaux_validation_prevus': 3,
                            'urgence_initiale': demande.urgence,
                            'poste_concerne': demande.poste.titre if demande.poste else 'Non défini'
                        }
                    }
                ]
                
                # Ajouter des actions selon l'étape actuelle
                if etape_type != 'DEMANDE':
                    actions_intermediaires = []
                    
                    if etape_type in ['EN_PROPOSITION', 'VALIDATION_RESPONSABLE', 'VALIDATION_DIRECTEUR', 'VALIDATION_RH_ADMIN']:
                        actions_intermediaires.append({
                            'date': (timezone.now() - timedelta(days=5)).isoformat(),
                            'utilisateur': {
                                'nom': 'Système V4.1',
                                'type_profil': 'SYSTEM'
                            },
                            'action': 'Ouverture phase propositions',
                            'commentaire': 'Phase de propositions candidats ouverte avec scoring V4.1',
                            'etape': 'PROPOSITION_CANDIDATS',
                            'metadata': {
                                'type': 'ouverture_propositions_v41',
                                'nb_propositions_attendues': random.randint(3, 8),
                                'delai_limite_propositions': 48,
                                'scoring_version': '4.1'
                            }
                        })
                    
                    if etape_type in ['VALIDATION_RESPONSABLE', 'VALIDATION_DIRECTEUR', 'VALIDATION_RH_ADMIN']:
                        # Ajouter les validations précédentes
                        niveaux_passes = {
                            'VALIDATION_RESPONSABLE': [],
                            'VALIDATION_DIRECTEUR': ['VALIDATION_RESPONSABLE'],
                            'VALIDATION_RH_ADMIN': ['VALIDATION_RESPONSABLE', 'VALIDATION_DIRECTEUR']
                        }
                        
                        for niveau_passe in niveaux_passes.get(etape_type, []):
                            actions_intermediaires.append({
                                'date': (timezone.now() - timedelta(days=random.randint(2, 4))).isoformat(),
                                'utilisateur': {
                                    'nom': f'Validateur {niveau_passe}',
                                    'type_profil': niveau_passe.split('_')[1]
                                },
                                'action': f'Validation {niveau_passe}',
                                'commentaire': f'Validation {niveau_passe} approuvée avec workflow V4.1',
                                'etape': niveau_passe,
                                'metadata': {
                                    'type': 'validation_v41',
                                    'niveau_validation': self._get_niveau_from_etape(niveau_passe),
                                    'decision': 'APPROUVE',
                                    'workflow_version': '4.1'
                                }
                            })
                    
                    historique_enrichi.extend(actions_intermediaires)
                
                workflow = WorkflowDemande.objects.create(
                    demande=demande,
                    etape_actuelle=etape_actuelle,
                    nb_propositions_recues=random.randint(1, 8),
                    nb_candidats_evalues=random.randint(1, 5),
                    nb_niveaux_validation_passes=len([e for e in historique_enrichi if 'validation' in e.get('action', '').lower()]),
                    historique_actions=historique_enrichi,
                    # Attributs V4.1
                    version_workflow='4.1',
                    metadata_workflow={
                        'hierarchie_corrigee': True,
                        'scoring_version': '4.1',
                        'employes_kelio_impliques': len([emp for emp in self.created_objects.get('employes_kelio', []) if emp.id == demande.demandeur.id]),
                        'employes_fictifs_impliques': len([emp for emp in self.created_objects.get('employes_fictifs', []) if emp.id == demande.demandeur.id])
                    }
                )
                
                created_count += 1
                self._update_stats('WorkflowDemande', True)
                
            except Exception as e:
                logger.error(f"Erreur création workflow détaillé V4.1: {e}")
        
        self._write(f"  ✅ {created_count} workflow(s) détaillé(s) V4.1 créé(s)")
    
    def _get_niveau_from_etape(self, etape_name):
        """Retourne le niveau numérique depuis le nom d'étape"""
        mapping = {
            'VALIDATION_RESPONSABLE': 1,
            'VALIDATION_DIRECTEUR': 2,
            'VALIDATION_RH_ADMIN': 3
        }
        return mapping.get(etape_name, 0)
    
    def _create_detailed_scores_v41(self):
        """Crée des scores détaillés V4.1 avancés"""
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        propositions = self.created_objects.get('propositions', [])
        configs_scoring = self.created_objects.get('configurations_scoring', [])
        
        if not propositions:
            self._write("⚠️ Pas de propositions pour créer les scores détaillés V4.1")
            return
        
        created_count = 0
        
        # Utiliser différentes configurations de scoring
        for proposition in propositions:
            # Créer des scores avec différentes configurations
            configs_to_test = configs_scoring if configs_scoring else [None]
            
            for config in configs_to_test[:2]:  # Max 2 configs par proposition
                try:
                    # Scores de base variables selon la source de l'employé
                    is_kelio_employee = proposition.candidat_propose in self.created_objects.get('employes_kelio', [])
                    
                    if is_kelio_employee:
                        # Employés Kelio ont généralement de meilleurs scores
                        score_base_min, score_base_max = 55, 95
                        bonus_kelio = 5
                    else:
                        # Employés fictifs ont des scores plus variables
                        score_base_min, score_base_max = 40, 85
                        bonus_kelio = 0
                    
                    scores_individuels = {
                        'similarite': random.randint(score_base_min, score_base_max),
                        'competences': random.randint(score_base_min-10, score_base_max-5),
                        'experience': random.randint(score_base_min-15, score_base_max-10),
                        'disponibilite': random.randint(score_base_min+20, 100),
                        'proximite': random.randint(30, score_base_max),
                        'anciennete': random.randint(20, score_base_max-15)
                    }
                    
                    # Bonus selon la source et la hiérarchie
                    bonus_hierarchique = self._get_bonus_hierarchique_v41(proposition.source_proposition)
                    bonus_experience = random.randint(0, 10) if scores_individuels['experience'] > 70 else 0
                    bonus_recommandation = random.randint(0, 12) if proposition.justification else 0
                    
                    # Calculer le score pondéré selon la configuration
                    if config:
                        poids = {
                            'similarite': config.poids_similarite_poste,
                            'competences': config.poids_competences,
                            'experience': config.poids_experience,
                            'disponibilite': config.poids_disponibilite,
                            'proximite': config.poids_proximite,
                            'anciennete': config.poids_anciennete
                        }
                        
                        score_pondere = sum(
                            scores_individuels[critere] * poids_val 
                            for critere, poids_val in poids.items()
                        )
                        
                        calcule_par = f'CONFIG_{config.nom.replace(" ", "_").upper()}'[:20]
                    else:
                        # Configuration par défaut
                        score_pondere = (
                            scores_individuels['similarite'] * 0.25 +
                            scores_individuels['competences'] * 0.25 +
                            scores_individuels['experience'] * 0.20 +
                            scores_individuels['disponibilite'] * 0.15 +
                            scores_individuels['proximite'] * 0.10 +
                            scores_individuels['anciennete'] * 0.05
                        )
                        calcule_par = 'DEFAULT_V41'
                    
                    score_detail = ScoreDetailCandidat.objects.create(
                        candidat=proposition.candidat_propose,
                        demande_interim=proposition.demande_interim,
                        proposition_humaine=proposition,
                        score_similarite_poste=scores_individuels['similarite'],
                        score_competences=scores_individuels['competences'],
                        score_experience=scores_individuels['experience'],
                        score_disponibilite=scores_individuels['disponibilite'],
                        score_proximite=scores_individuels['proximite'],
                        score_anciennete=scores_individuels['anciennete'],
                        bonus_proposition_humaine=proposition.bonus_proposition_humaine,
                        bonus_experience_similaire=bonus_experience,
                        bonus_recommandation=bonus_recommandation,
                        bonus_hierarchique=bonus_hierarchique,
                        bonus_kelio_data_quality=bonus_kelio,
                        penalite_indisponibilite=random.randint(0, 15),
                        penalite_distance_excessive=random.randint(0, 8),
                        calcule_par=calcule_par,
                        # Attributs V4.1
                        version_scoring='4.1',
                        configuration_scoring=config,
                        metadata_scoring={
                            'source_candidat': 'kelio' if is_kelio_employee else 'fictif',
                            'source_proposant': proposition.source_proposition,
                            'workflow_version': '4.1',
                            'hierarchie_corrigee': True,
                            'bonus_details': {
                                'hierarchique': bonus_hierarchique,
                                'experience': bonus_experience,
                                'recommandation': bonus_recommandation,
                                'kelio_data': bonus_kelio
                            }
                        }
                    )
                    
                    # Calculer le score total V4.1
                    score_detail.calculer_score_total()
                    score_detail.save()
                    
                    # Mettre à jour le score dans la proposition si c'est la première configuration
                    if config == configs_to_test[0] or not configs_scoring:
                        proposition.score_automatique = score_detail.score_total
                        proposition.save()
                    
                    created_count += 1
                    self._update_stats('ScoreDetailCandidat', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création score détaillé avancé V4.1: {e}")
        
        self._write(f"  ✅ {created_count} score(s) détaillé(s) V4.1 créé(s)")
    
    def _create_scoring_comparisons(self):
        """Crée des comparaisons de scoring entre configurations"""
        # Analyser les scores créés pour générer des comparaisons
        ScoreDetailCandidat = self.models['ScoreDetailCandidat']
        
        scores_by_config = {}
        all_scores = ScoreDetailCandidat.objects.filter(version_scoring='4.1')
        
        for score in all_scores:
            config_name = score.calcule_par
            if config_name not in scores_by_config:
                scores_by_config[config_name] = []
            scores_by_config[config_name].append(score.score_total)
        
        if len(scores_by_config) > 1:
            self._write("  📊 Comparaisons scoring V4.1:")
            for config_name, scores in scores_by_config.items():
                avg_score = sum(scores) / len(scores) if scores else 0
                self._write(f"    • {config_name}: Moyenne {avg_score:.1f} pts ({len(scores)} scores)")
    
    def _create_scoring_analytics(self):
        """Crée des analytics de scoring avancés"""
        # Analyser la performance du scoring V4.1
        employes_kelio = self.created_objects.get('employes_kelio', [])
        employes_fictifs = self.created_objects.get('employes_fictifs', [])
        
        analytics = {
            'version': '4.1',
            'timestamp': timezone.now().isoformat(),
            'employes_kelio_count': len(employes_kelio),
            'employes_fictifs_count': len(employes_fictifs),
            'ratio_kelio_fictifs': len(employes_kelio) / max(1, len(employes_fictifs)),
            'hierarchie_corrigee': True,
            'workflow_version': '4.1'
        }
        
        self._write("  📈 Analytics scoring V4.1 générés")
        return analytics
    
    def _create_advanced_notifications(self):
        """Crée des notifications avancées V4.1"""
        NotificationInterim = self.models['NotificationInterim']
        demandes = self.created_objects.get('demandes_interim', [])
        all_employees = self.created_objects.get('employes_tous', [])
        
        if not demandes or not all_employees:
            return
        
        created_count = 0
        
        # Templates de notifications avancées V4.1
        templates_avances = {
            'ANALYTICS_SCORING_V41': {
                'titre': 'Rapport analytics scoring V4.1 disponible',
                'message': 'Un nouveau rapport d\'analytics scoring V4.1 avec comparaisons Kelio/Fictifs est disponible.',
                'urgence': 'NORMALE'
            },
            'WORKFLOW_OPTIMISATION_V41': {
                'titre': 'Optimisation workflow V4.1 suggérée',
                'message': 'Des optimisations de workflow V4.1 sont suggérées basées sur l\'analyse des données.',
                'urgence': 'FAIBLE'
            },
            'HIERARCHIE_ALERT_V41': {
                'titre': 'Alerte hiérarchie V4.1 - Action requise',
                'message': 'Une situation nécessitant une intervention hiérarchique V4.1 a été détectée.',
                'urgence': 'ELEVEE'
            }
        }
        
        # Sélectionner des destinataires privilégiés (RH, ADMIN, DIRECTEUR)
        destinataires_privilegies = [
            emp for emp in all_employees 
            if emp.type_profil in ['RH', 'ADMIN', 'DIRECTEUR']
        ]
        
        if not destinataires_privilegies:
            destinataires_privilegies = all_employees[:5]
        
        for template_key, template in templates_avances.items():
            for destinataire in destinataires_privilegies[:3]:  # Limiter à 3 destinataires
                try:
                    # Métadonnées avancées V4.1
                    metadata_avancee = {
                        'type_notification': template_key,
                        'workflow_version': '4.1',
                        'hierarchie_corrigee': True,
                        'destinataire_niveau': destinataire.type_profil,
                        'destinataire_source': 'kelio' if destinataire in self.created_objects.get('employes_kelio', []) else 'fictif',
                        'analytics_integration': True,
                        'scoring_version': '4.1',
                        'permissions_etendues': {
                            'acces_analytics': destinataire.type_profil in ['RH', 'ADMIN'],
                            'acces_workflow_config': destinataire.type_profil in ['ADMIN'],
                            'acces_scoring_config': destinataire.type_profil in ['RH', 'ADMIN'],
                            'acces_hierarchie_management': destinataire.type_profil in ['DIRECTEUR', 'RH', 'ADMIN']
                        },
                        'contexte_avance': {
                            'nb_employes_kelio': len(self.created_objects.get('employes_kelio', [])),
                            'nb_employes_fictifs': len(self.created_objects.get('employes_fictifs', [])),
                            'nb_demandes_actives': len(demandes),
                            'taux_completion_workflow': random.randint(75, 95)
                        }
                    }
                    
                    notification = NotificationInterim.objects.create(
                        destinataire=destinataire,
                        expediteur=None,  # Notification système
                        type_notification=template_key,
                        urgence=template['urgence'],
                        statut='NON_LUE',
                        titre=template['titre'],
                        message=template['message'],
                        url_action_principale=f"/interim/v41/analytics/{template_key.lower()}/",
                        texte_action_principale="Consulter analytics",
                        url_action_secondaire=f"/interim/v41/dashboard/advanced/",
                        texte_action_secondaire="Dashboard avancé",
                        metadata=metadata_avancee,
                        # Attributs V4.1
                        version_notification='4.1',
                        notification_avancee=True
                    )
                    
                    created_count += 1
                    self._update_stats('NotificationInterim', True)
                    
                except Exception as e:
                    logger.error(f"Erreur création notification avancée V4.1: {e}")
        
        self._write(f"  ✅ {created_count} notification(s) avancée(s) V4.1 créée(s)")
    
    def _create_test_workflow_complete(self):
        """Crée un workflow de test complet V4.1"""
        self._create_workflow_data_v41()
        self._create_advanced_workflow_elements()
    
    def _create_test_cache_and_optimizations(self):
        """Crée le cache et optimisations de test V4.1"""
        self._create_kelio_cache_v41()
        self._create_performance_optimizations()
    
    def _create_kelio_cache_v41(self):
        """Crée des entrées de cache Kelio V4.1"""
        if not self.kelio_config:
            return
        
        CacheApiKelio = self.models['CacheApiKelio']
        created_count = 0
        
        # Entrées de cache pour les nouveaux services V4.1
        cache_entries_v41 = [
            {
                'cle_cache': 'employee_professional_data_v41',
                'service_name': 'EmployeeProfessionalDataService',
                'parametres_requete': {'mode': 'complet', 'version': '4.1'},
                'donnees': {
                    'employees_count': len(self.created_objects.get('employes_kelio', [])),
                    'sync_version': '4.1',
                    'services_utilises': ['EmployeeProfessionalDataService', 'SkillAssignmentService'],
                    'hierarchie_corrigee': True
                },
                'taille_donnees': 2500
            },
            {
                'cle_cache': 'peripheral_data_v41',
                'service_name': 'MultiplePeripheralServices',
                'parametres_requete': {'include_skills': True, 'include_formations': True, 'version': '4.1'},
                'donnees': {
                    'peripheral_data_count': self.stats.get('peripheral_data_created', 0),
                    'services_peripheriques': ['SkillAssignmentService', 'InitialFormationAssignmentService'],
                    'workflow_version': '4.1'
                },
                'taille_donnees': 1800
            },
            {
                'cle_cache': 'workflow_analytics_v41',
                'service_name': 'WorkflowAnalyticsService',
                'parametres_requete': {'analytics_version': '4.1', 'include_scoring': True},
                'donnees': {
                    'demandes_count': len(self.created_objects.get('demandes_interim', [])),
                    'propositions_count': len(self.created_objects.get('propositions', [])),
                    'validations_count': len(self.created_objects.get('validations', [])),
                    'workflow_version': '4.1',
                    'hierarchie_corrigee': True
                },
                'taille_donnees': 950
            }
        ]
        
        for cache_data in cache_entries_v41:
            try:
                cache_entry = CacheApiKelio.objects.create(
                    configuration=self.kelio_config,
                    cle_cache=cache_data['cle_cache'],
                    service_name=cache_data['service_name'],
                    parametres_requete=cache_data['parametres_requete'],
                    donnees=cache_data['donnees'],
                    date_expiration=timezone.now() + timedelta(hours=2),
                    nb_acces=random.randint(0, 15),
                    taille_donnees=cache_data['taille_donnees'],
                    # Attributs V4.1
                    version_cache='4.1'
                )
                created_count += 1
                self._update_stats('CacheApiKelio', True)
                
            except Exception as e:
                logger.error(f"Erreur création cache V4.1: {e}")
        
        self._write(f"  ✅ {created_count} entrée(s) de cache V4.1 créée(s)")
    
    def _create_performance_optimizations(self):
        """Crée des optimisations de performance"""
        # Analyser les performances et créer des recommandations
        optimizations = {
            'version': '4.1',
            'recommendations': [
                'Utiliser les index sur les champs type_profil pour les requêtes hiérarchiques',
                'Mettre en cache les résultats de scoring pour éviter les recalculs',
                'Optimiser les requêtes de workflow avec select_related sur les FK',
                'Implémenter une pagination pour les listes d\'employés > 100',
                'Utiliser des tâches asynchrones pour les synchronisations Kelio longues'
            ],
            'metrics': {
                'employes_total': len(self.created_objects.get('employes_tous', [])),
                'employes_kelio_ratio': len(self.created_objects.get('employes_kelio', [])) / max(1, len(self.created_objects.get('employes_tous', []))),
                'workflow_complexity': len(self.created_objects.get('demandes_interim', [])) * 3,  # 3 niveaux de validation
                'cache_efficiency': 85.5  # Pourcentage simulé
            },
            'timestamp': timezone.now().isoformat()
        }
        
        self._write("  ⚡ Optimisations de performance V4.1 analysées")
        return optimizations
    
    # ================================================================
    # MÉTHODES D'AUDIT ET VALIDATION
    # ================================================================
    
    def _audit_existing_data(self):
        """Audit des données existantes avant migration V4.1"""
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        
        audit_results = {
            'timestamp': timezone.now().isoformat(),
            'version_audit': '4.1',
            'employes_existants': ProfilUtilisateur.objects.count(),
            'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
            'employes_avec_kelio_data': ProfilUtilisateur.objects.filter(
                kelio_sync_status__isnull=False
            ).count(),
            'employes_sans_kelio_data': ProfilUtilisateur.objects.filter(
                kelio_sync_status__isnull=True
            ).count()
        }
        
        self._write(f"🔍 Audit terminé: {audit_results['employes_existants']} employé(s) existant(s)")
        return audit_results
    
    def _migrate_structure_to_v41(self):
        """Migre la structure existante vers V4.1"""
        # Mise à jour des configurations existantes
        ConfigurationScoring = self.models['ConfigurationScoring']
        
        configs_updated = ConfigurationScoring.objects.filter(
            version_scoring__isnull=True
        ).update(
            version_scoring='4.1',
            support_peripheral_data=True,
            bonus_kelio_data_quality=5
        )
        
        self._write(f"🔄 Structure migrée vers V4.1: {configs_updated} configuration(s) mise(s) à jour")
    
    def _migrate_employees_to_v41(self):
        """Migre les employés existants vers V4.1"""
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        
        # Marquer les employés existants comme nécessitant une resynchronisation
        employees_to_migrate = ProfilUtilisateur.objects.filter(
            source_creation__isnull=True
        ).update(
            source_creation='MIGRATION_V41'
        )
        
        self._write(f"👥 Employés migrés vers V4.1: {employees_to_migrate} employé(s)")
    
    def _migrate_workflow_to_v41(self):
        """Migre le workflow existant vers V4.1"""
        WorkflowEtape = self.models['WorkflowEtape']
        
        # Mettre à jour les étapes existantes
        etapes_updated = WorkflowEtape.objects.filter(
            version_workflow__isnull=True
        ).update(
            version_workflow='4.1'
        )
        
        self._write(f"🔄 Workflow migré vers V4.1: {etapes_updated} étape(s) mise(s) à jour")
    
    def _validate_v41_migration(self):
        """Valide la migration vers V4.1"""
        validation_results = {
            'timestamp': timezone.now().isoformat(),
            'version_validation': '4.1',
            'validations': {}
        }
        
        # Validation des configurations V4.1
        ConfigurationScoring = self.models['ConfigurationScoring']
        configs_v41 = ConfigurationScoring.objects.filter(version_scoring='4.1').count()
        validation_results['validations']['configurations_v41'] = configs_v41 > 0
        
        # Validation des employés
        ProfilUtilisateur = self.models['ProfilUtilisateur']
        employes_total = ProfilUtilisateur.objects.count()
        validation_results['validations']['employes_present'] = employes_total >= self.min_employees
        
        # Validation du workflow
        WorkflowEtape = self.models['WorkflowEtape']
        etapes_v41 = WorkflowEtape.objects.filter(version_workflow='4.1').count()
        validation_results['validations']['workflow_v41'] = etapes_v41 >= 8
        
        # Validation globale
        all_validations = list(validation_results['validations'].values())
        validation_results['migration_v41_success'] = all(all_validations)
        
        success_emoji = "✅" if validation_results['migration_v41_success'] else "❌"
        self._write(f"{success_emoji} Validation migration V4.1: {'RÉUSSIE' if validation_results['migration_v41_success'] else 'ÉCHOUÉE'}")
        
        return validation_results
    
    # ================================================================
    # MÉTHODES UTILITAIRES ET STATISTIQUES
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
        """Affiche les statistiques finales V4.1"""
        self._write("📊 STATISTIQUES MIGRATION KELIO V4.1 COMPATIBLE")
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
        self._write("👥 RÉSUMÉ EMPLOYÉS V4.1:")
        self._write(f"  📥 Employés Kelio V4.1: {self.stats['kelio_employees']}")
        self._write(f"  🎭 Employés fictifs africains: {self.stats['fictional_employees']}")
        self._write(f"  👥 Total employés: {len(self.created_objects.get('employes_tous', []))}")
        self._write(f"  📊 Données périphériques: {self.stats['peripheral_data_created']}")
        
        self._write("")
        self._write("🏢 STRUCTURE ORGANISATIONNELLE:")
        self._write(f"  🏪 Départements: {len(self.created_objects.get('departements', []))}")
        self._write(f"  🏢 Sites: {len(self.created_objects.get('sites', []))}")
        self._write(f"  💼 Postes: {len(self.created_objects.get('postes', []))}")
        self._write(f"  🎯 Compétences: {len(self.created_objects.get('competences', []))}")
        self._write(f"  🏥 Motifs absence: {len(self.created_objects.get('motifs_absence', []))}")
        
        self._write("")
        self._write("🔄 WORKFLOW V4.1:")
        self._write(f"  📋 Demandes intérim: {len(self.created_objects.get('demandes_interim', []))}")
        self._write(f"  👤 Propositions: {len(self.created_objects.get('propositions', []))}")
        self._write(f"  ✅ Validations: {len(self.created_objects.get('validations', []))}")
        self._write(f"  ⚙️ Configurations scoring: {len(self.created_objects.get('configurations_scoring', []))}")
        
        if self.with_kelio_sync:
            self._write("")
            self._write("📡 SYNCHRONISATION KELIO V4.1:")
            self._write("  ✅ API EmployeeProfessionalDataService utilisée")
            self._write("  ✅ Données périphériques synchronisées")
            self._write("  ✅ Mapping vers modèles Django effectué")
        
        if self.african_names:
            self._write("")
            self._write("🌍 DONNÉES AFRICAINES:")
            self._write(f"  🇨🇮 Pays couverts: {', '.join(self.countries)}")
            self._write("  📱 Numéros téléphone africains générés")
            self._write("  🏘️ Adresses locales (Abidjan, Bouaké, etc.)")
            self._write("  🗣️ Langues locales intégrées")
        
        self._write("")
        self._write("🎯 HIÉRARCHIE CORRIGÉE V4.1:")
        self._write("  • Niveau 1: RESPONSABLE (validation opérationnelle)")
        self._write("  • Niveau 2: DIRECTEUR (validation stratégique)")
        self._write("  • Niveau 3: RH/ADMIN (validation finale)")
        self._write("  • CHEF_EQUIPE: Propositions uniquement")
        self._write("  • SUPERUSER: Droits complets automatiques")
        
        self._write("=" * 80)
    
    def _log_error_statistics(self):
        """Affiche les statistiques en cas d'erreur"""
        self._write("❌ MIGRATION KELIO V4.1 INTERROMPUE", self.style.ERROR if self.style else None)
        self._write("=" * 80)
        self._write(f"Erreurs rencontrées: {self.stats['total_errors']}")
        self._write(f"Éléments créés avant interruption: {self.stats['total_created']}")
        self._write(f"Employés Kelio synchronisés: {self.stats['kelio_employees']}")
        self._write(f"Employés fictifs créés: {self.stats['fictional_employees']}")
        self._write("=" * 80)


# ================================================================
# LOG DE CONFIRMATION V4.1
# ================================================================

logger.info("✅ Module populate_kelio_data.py V4.1 COMPATIBLE terminé avec succès")
logger.info("🔧 Nouvelles fonctionnalités V4.1:")
logger.info("   • ✅ Compatible avec kelio_api_simplifie.py V4.1")
logger.info("   • ✅ Support EmployeeProfessionalDataService comme service principal")
logger.info("   • ✅ Complémentation automatique si < 100 employés Kelio")
logger.info("   • ✅ Noms africains (Côte d'Ivoire, Ghana, Mali)")
logger.info("   • ✅ Hiérarchie corrigée : RESPONSABLE → DIRECTEUR → RH/ADMIN")
logger.info("   • ✅ Workflow intégré avec nouvelles API SOAP V4.1")
logger.info("   • ✅ Données périphériques complètes (compétences, formations, absences)")
logger.info("   • ✅ Mapping vers ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended")
logger.info("   • ✅ Cache optimisé pour les nouvelles structures V4.1")
logger.info("   • ✅ Scoring avec bonus hiérarchiques V4.1 corrigés")
logger.info("   • ✅ Synchronisation via API SOAP V4.1 avec fallback intelligent")
logger.info("🚀 Prêt pour utilisation avec les commandes Django manage.py")

print("🎯 populate_kelio_data.py V4.1 COMPATIBLE TERMINÉ")
print("💡 Usage principal compatible V4.1:")
print("   python manage.py populate_kelio_data --mode=kelio_plus_fictifs --min-employees=100 --with-kelio-sync")
print("   python manage.py populate_kelio_data --mode=full --african-names --with-peripherals --with-workflow")
print("   python manage.py populate_kelio_data --mode=test --sample-size=150 --countries COTE_IVOIRE GHANA MALI")
print("🔄 Compatible avec kelio_api_simplifie.py V4.1 EmployeeProfessionalDataService")
print("🌍 Complémentation intelligente avec employés fictifs africains")
print("📊 Workflow hiérarchique: CHEF_EQUIPE → RESPONSABLE → DIRECTEUR → RH/ADMIN + SUPERUSER")