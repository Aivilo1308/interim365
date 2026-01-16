# -*- coding: utf-8 -*-
"""
Service de synchronisation Kelio refactorise - Version 4.1 COMPLETE AVEC FALLBACK
Integration avec les nouvelles API SOAP Kelio documentees + fallback EmployeeService robuste
Support complet des nouveaux services avec mapping vers les modeles Django

NOUVELLES FONCTIONNALITES V4.1 COMPLETES :
- EmployeeProfessionalDataService comme service principal avec fallback EmployeeService
- Synchronisation complete User + ProfilUtilisateur + donnees etendues
- Iteration automatique sur tous les employes pour donnees peripheriques
- Support de tous les nouveaux services documentes avec fallback
- Mapping precis vers les modeles Django existants
- Cache intelligent optimise pour les nouvelles API
- Gestion d'erreurs robuste avec fallback automatique
- Integration complete avec les modeles Django
- Extraction multi-format pour tous types de reponses SOAP

Version : 4.1 COMPLETE - Avec nouvelles API Kelio documentees + fallback robuste
Auteur : Systeme Django Interim
Date : 2025
"""

from django.shortcuts import render, get_object_or_404, redirect
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth.models import User

import json
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import uuid
from zeep.helpers import serialize_object
from django.core.cache import cache
from mainapp.models import ConfigurationApiKelio

# Imports SOAP
try:
    from zeep import Client, Settings, Transport
    from zeep.exceptions import Fault, TransportError
    from requests import Session
    from requests.auth import HTTPBasicAuth
    SOAP_AVAILABLE = True
except ImportError:
    SOAP_AVAILABLE = False
    print("WARNING: Dependances SOAP manquantes. Installez : pip install zeep requests")

# Logger securise
try:
    from django.conf import settings
    logger = settings.get_safe_kelio_logger()
except:
    import logging
    logger = logging.getLogger('kelio.sync')

# ================================================================
# CONFIGURATION KELIO SAFESECUR - IMPORT STRICT
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

KELIO_BASE_URL = credentials['base_url']
KELIO_SERVICES_URL = f'{KELIO_BASE_URL}/services'

KELIO_DEFAULT_AUTH = {
    'username': credentials['username'],
    'password': credentials['password']
    }

# ================================================================
# CONFIGURATION DES NOUVEAUX SERVICES KELIO - COMPLETE AVEC FALLBACK
# ================================================================

# Configuration des nouveaux services Kelio selon la documentation + fallback robuste
KELIO_SERVICES_CONFIG = {
    'employee_professional_data': {
        'service_name': 'EmployeeProfessionalDataService',
        'fallback_service': 'EmployeeService',
        'wsdl_path': 'EmployeeProfessionalDataService?wsdl',
        'fallback_wsdl_path': 'EmployeeService?wsdl',
        'method_all': 'exportEmployeeProfessionalData',
        'method_single': 'exportEmployeeProfessionalDataList',
        'fallback_method': 'exportEmployees',
        'priority': 1,
        'timeout': 60,
        'required_for_creation': True,
        'cache_duration': 3600,
        'data_source': 'KELIO',
        'description': 'Donnees professionnelles des employes (service principal)',
        'maps_to_models': ['ProfilUtilisateur', 'ProfilUtilisateurExtended', 'ProfilUtilisateurKelio']
    },
    'employee_list': {
        'service_name': 'EmployeeListService',
        'fallback_service': 'EmployeeService',
        'wsdl_path': 'EmployeeListService?wsdl',
        'fallback_wsdl_path': 'EmployeeService?wsdl',
        'method': 'exportEmployeeList',
        'fallback_method': 'exportEmployees',
        'priority': 1,
        'timeout': 30,
        'required_for_creation': False,
        'cache_duration': 3600,
        'data_source': 'KELIO',
        'description': 'Liste des employes (KELIO) -> ProfilUtilisateur',
        'maps_to_models': ['ProfilUtilisateur']
    },
    'job_assignments': {
        'service_name': 'JobAssignmentService',
        'wsdl_path': 'JobAssignmentService?wsdl',
        'method': 'exportJobAssignments',
        'priority': 2,
        'timeout': 45,
        'required_for_creation': False,
        'cache_duration': 7200,
        'data_source': 'KELIO_ONLY',
        'description': 'Affectations a des postes (Kelio-only)',
        'read_only_in_app': True,
        'maps_to_models': ['Cache']
    },
    'employee_job_assignments': {
        'service_name': 'EmployeeJobAssignmentService',
        'wsdl_path': 'EmployeeJobAssignmentService?wsdl',
        'method': 'exportEmployeeJobAssignments',
        'priority': 2,
        'timeout': 45,
        'required_for_creation': False,
        'cache_duration': 7200,
        'data_source': 'KELIO_ONLY',
        'description': 'Affectations aux emplois (Kelio-only)',
        'read_only_in_app': True,
        'maps_to_models': ['Cache']
    },
    'professional_experience': {
        'service_name': 'ProfessionalExperienceAssignmentService',
        'wsdl_path': 'ProfessionalExperienceAssignmentService?wsdl',
        'method': 'exportProfessionalExperienceAssignment',
        'priority': 3,
        'timeout': 60,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO_ONLY',
        'description': 'Experiences professionnelles (Kelio-only)',
        'read_only_in_app': True,
        'maps_to_models': ['Cache']
    },
    'skill_assignments': {
        'service_name': 'SkillAssignmentService',
        'wsdl_path': 'SkillAssignmentService?wsdl',
        'method': 'exportSkillAssignments',
        'priority': 2,
        'timeout': 45,
        'required_for_creation': False,
        'cache_duration': 7200,
        'data_source': 'KELIO',
        'description': 'Competences et niveaux',
        'maps_to_models': ['Competence', 'CompetenceUtilisateur']
    },
    'labor_contracts': {
        'service_name': 'LaborContractAssignmentService',
        'wsdl_path': 'LaborContractAssignmentService?wsdl',
        'method': 'exportLaborContractAssignments',
        'priority': 3,
        'timeout': 60,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO_ONLY',
        'description': 'Contrats de travail (Kelio-only)',
        'read_only_in_app': True,
        'maps_to_models': ['Cache']
    },
    'initial_formations': {
        'service_name': 'InitialFormationAssignmentService',
        'wsdl_path': 'InitialFormationAssignmentService?wsdl',
        'method': 'exportInitialFormationAssignment',
        'priority': 3,
        'timeout': 60,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO',
        'description': 'Formations initiales',
        'maps_to_models': ['FormationUtilisateur']
    },
    'absence_requests': {
        'service_name': 'AbsenceRequestService',
        'wsdl_path': 'AbsenceRequestService?wsdl',
        'method': 'exportAbsenceRequestsFromEmployeeList',
        'priority': 2,
        'timeout': 30,
        'required_for_creation': False,
        'cache_duration': 900,
        'data_source': 'KELIO',
        'description': 'Demandes d\'absences',
        'maps_to_models': ['AbsenceUtilisateur', 'MotifAbsence']
    },
    'employee_pictures': {
        'service_name': 'EmployeePictureService',
        'wsdl_path': 'EmployeePictureService?wsdl',
        'method': 'exportEmployeePicturesList',
        'priority': 4,
        'timeout': 45,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO_ONLY',
        'description': 'Photos des employes (Kelio-only)',
        'read_only_in_app': True,
        'maps_to_models': ['Cache']
    },
    'training_history': {
        'service_name': 'EmployeeTrainingHistoryService',
        'wsdl_path': 'EmployeeTrainingHistoryService?wsdl',
        'method': 'exportEmployeeTrainingHistory',
        'priority': 3,
        'timeout': 60,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO',
        'description': 'Historique des formations',
        'maps_to_models': ['FormationUtilisateur']
    },
    'coefficient_assignments': {
        'service_name': 'CoefficientAssignmentService',
        'wsdl_path': 'CoefficientAssignmentService?wsdl',
        'method': 'exportCoefficientAssignments',
        'priority': 3,
        'timeout': 45,
        'required_for_creation': False,
        'cache_duration': 86400,
        'data_source': 'KELIO',
        'description': 'Coefficients et classifications',
        'maps_to_models': ['ProfilUtilisateurExtended']
    }
}

# ================================================================
# CLASSES D'EXCEPTION KELIO - VERSION COMPLETE
# ================================================================

class KelioBaseError(Exception):
    """Exception de base pour les erreurs Kelio"""
    def __init__(self, message, details=None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self):
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details,
            'timestamp': timezone.now().isoformat()
        }

class KelioConnectionError(KelioBaseError):
    """Erreur de connexion aux services Kelio"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.url = details.get('url', 'URL non specifiee')
            self.timeout = details.get('timeout', 'Timeout non specifie')
            self.service_name = details.get('service_name', 'Service non specifie')
        else:
            self.url = 'URL non specifiee'
            self.timeout = 'Timeout non specifie'
            self.service_name = 'Service non specifie'
    
    def __str__(self):
        return f"Erreur de connexion Kelio: {self.message} (Service: {self.service_name}, URL: {self.url})"

class KelioEmployeeNotFoundError(KelioBaseError):
    """Employe non trouve dans Kelio"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.matricule = details.get('matricule', 'Matricule non specifie')
            self.service_used = details.get('service_used', 'Service non specifie')
        else:
            import re
            matricule_match = re.search(r'[A-Z0-9]{3,10}', message)
            self.matricule = matricule_match.group(0) if matricule_match else 'Matricule non identifie'
            self.service_used = 'Service non specifie'
    
    def __str__(self):
        return f"Employe non trouve dans Kelio: {self.message} (Matricule: {self.matricule}, Service: {self.service_used})"

class KelioAuthenticationError(KelioBaseError):
    """Erreur d'authentification Kelio"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.username = details.get('username', 'Username non specifie')
            self.validation_message = details.get('validation_message', 'Message de validation non specifie')
        else:
            self.username = 'Username non specifie'
            self.validation_message = 'Message de validation non specifie'
    
    def __str__(self):
        return f"Erreur d'authentification Kelio: {self.message} (Username: {self.username})"

class KelioDataError(KelioBaseError):
    """Erreur dans les donnees retournees par Kelio"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.data_type = details.get('data_type', 'Type de donnees non specifie')
            self.expected_format = details.get('expected_format', 'Format attendu non specifie')
            self.received_format = details.get('received_format', 'Format recu non specifie')
        else:
            self.data_type = 'Type de donnees non specifie'
            self.expected_format = 'Format attendu non specifie'
            self.received_format = 'Format recu non specifie'
    
    def __str__(self):
        return f"Erreur de donnees Kelio: {self.message} (Type: {self.data_type})"

class KelioServiceUnavailableError(KelioBaseError):
    """Service Kelio temporairement indisponible"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.service_name = details.get('service_name', 'Service non specifie')
            self.retry_after = details.get('retry_after', 'Delai de retry non specifie')
            self.status_code = details.get('status_code', 'Code de statut non specifie')
        else:
            self.service_name = 'Service non specifie'
            self.retry_after = 'Delai de retry non specifie'
            self.status_code = 'Code de statut non specifie'
    
    def __str__(self):
        return f"Service Kelio indisponible: {self.message} (Service: {self.service_name}, Status: {self.status_code})"

class ConfigurationKeliomanquanteError(KelioBaseError):
    """Configuration Kelio manquante ou invalide"""
    def __init__(self, message, details=None):
        super().__init__(message, details)
        if details:
            self.config_field = details.get('config_field', 'Champ de configuration non specifie')
            self.expected_value = details.get('expected_value', 'Valeur attendue non specifiee')
        else:
            self.config_field = 'Champ de configuration non specifie'
            self.expected_value = 'Valeur attendue non specifiee'
    
    def __str__(self):
        return f"Configuration Kelio manquante: {self.message} (Champ: {self.config_field})"

# ================================================================
# UTILITAIRES D'EXCEPTION
# ================================================================

def handle_kelio_exception(func):
    """Decorateur pour gerer les exceptions Kelio de maniere uniforme"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KelioBaseError as e:
            logger.error(f"Erreur Kelio dans {func.__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"Erreur inattendue dans {func.__name__}: {e}")
            raise KelioBaseError(f"Erreur inattendue dans {func.__name__}: {str(e)}")
    return wrapper

def create_kelio_connection_error(message, url=None, service_name=None, timeout=None, original_exception=None):
    """Factory pour creer une KelioConnectionError avec tous les details"""
    details = {
        'url': url,
        'service_name': service_name,
        'timeout': timeout,
        'original_exception': str(original_exception) if original_exception else None
    }
    return KelioConnectionError(message, details)

def create_kelio_employee_not_found_error(matricule, service_used=None, search_criteria=None):
    """Factory pour creer une KelioEmployeeNotFoundError avec tous les details"""
    message = f"Employe {matricule} non trouve dans Kelio"
    details = {
        'matricule': matricule,
        'service_used': service_used,
        'search_criteria': search_criteria
    }
    return KelioEmployeeNotFoundError(message, details)

def log_kelio_error(error, context=None):
    """Fonction utilitaire pour logger les erreurs Kelio de maniere standardisee"""
    if isinstance(error, KelioBaseError):
        error_dict = error.to_dict()
        if context:
            error_dict['context'] = context
        
        logger.error(f"Erreur Kelio: {error_dict}")
        return error_dict
    else:
        generic_error = {
            'error_type': 'UnknownError',
            'message': str(error),
            'context': context,
            'timestamp': timezone.now().isoformat()
        }
        logger.error(f"Erreur non-Kelio: {generic_error}")
        return generic_error

# ================================================================
# UTILITAIRES
# ================================================================

def validate_kelio_credentials(config):
    """Valide que les identifiants Kelio sont utilisables"""
    try:
        username = config.username or KELIO_DEFAULT_AUTH['username']
        password = config.password or KELIO_DEFAULT_AUTH['password']
        
        if not username or not password:
            return False, "Identifiants manquants"
        
        logger.info(f"Validation identifiants Kelio reussie pour {config.nom}")
        return True, "Identifiants valides"
        
    except Exception as e:
        logger.error(f"Validation identifiants Kelio echouee: {e}")
        return False, f"Erreur validation: {str(e)}"

def generer_cle_cache_kelio(service_type, parametres):
    """Genere une cle de cache unique pour les services Kelio"""
    try:
        params_str = json.dumps(parametres, sort_keys=True, default=str)
        signature = hashlib.md5(params_str.encode()).hexdigest()[:8]
        timestamp = timezone.now().strftime('%Y%m%d_%H')
        cle = f"{service_type}_{signature}_{timestamp}"
        return cle
    except Exception as e:
        logger.warning(f"Erreur generation cle cache: {e}")
        return f"{service_type}_{uuid.uuid4().hex[:8]}"

def safe_get_attribute(obj, attr_name, default=None):
    """Recuperation securisee d'attribut avec gestion des None"""
    try:
        return getattr(obj, attr_name, default) if obj else default
    except (AttributeError, TypeError):
        return default

def safe_date_conversion(date_value):
    """Conversion securisee de date"""
    if not date_value:
        return None
    try:
        if isinstance(date_value, str):
            # Essayer differents formats
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S']:
                try:
                    parsed = datetime.strptime(date_value, fmt)
                    return parsed.date() if '%H:%M:%S' not in fmt else parsed
                except ValueError:
                    continue
        elif hasattr(date_value, 'date'):
            return date_value.date()
        elif isinstance(date_value, date):
            return date_value
        return None
    except Exception:
        return None

# ================================================================
# SERVICE PRINCIPAL REFACTORISE - VERSION 4.1 COMPLETE
# ================================================================

class KelioSynchronizationServiceV41:
    """
    Service de synchronisation Kelio refactorise pour les nouvelles API
    Version 4.1 COMPLETE - Support complet des nouveaux services documentes + fallback robuste
    """
    
    def __init__(self, configuration=None):
        """Initialise le service avec les nouvelles API Kelio + fallback"""
        if not SOAP_AVAILABLE:
            raise KelioConnectionError(
                "Dependances SOAP manquantes (zeep, requests)",
                details={'error': 'Dependances SOAP manquantes (zeep, requests)'}
            )
        
        # Import adapte aux modeles
        from ..models import ConfigurationApiKelio, CacheApiKelio
        
        self.config = configuration or ConfigurationApiKelio.objects.filter(actif=True).first()
        if not self.config:
            raise ConfigurationKeliomanquanteError(
                "Aucune configuration Kelio active trouvee",
                details={'message': 'Aucune configuration Kelio active trouvee'}
            )
        
        # Validation des identifiants
        is_valid, message = validate_kelio_credentials(self.config)
        if not is_valid:
            logger.error(f"Identifiants Kelio invalides: {message}")
            raise KelioAuthenticationError(
                f"Identifiants Kelio invalides: {message}",
                details={'username': self.config.username, 'validation_message': message}
            )
        
        # Creer la session avec les identifiants
        self.session = self._create_session()
        self.clients = {}
        
        # Configuration des services avec les nouvelles API + fallback
        self.services_config = KELIO_SERVICES_CONFIG
        
        logger.info(f"Service Kelio V4.1 initialise pour {self.config.nom}")
        logger.info(f">>> {len(self.services_config)} services API disponibles")
        print(f">>> Service Kelio V4.1 cree pour {self.config.nom}")
    
    def _create_session(self):
        """Cree une session HTTP authentifiee"""
        try:
            # Utiliser les identifiants de configuration ou les valeurs par defaut
            username = self.config.username or KELIO_DEFAULT_AUTH['username']
            password = self.config.password or KELIO_DEFAULT_AUTH['password']
            
            print(f">>> Authentification Kelio:")
            print(f"  Username: '{username}'")
            print(f"  Password: '{password}'")
            
            session = Session()
            session.auth = HTTPBasicAuth(username, password)
            
            session.headers.update({
                'Content-Type': 'text/xml; charset=utf-8',
                'User-Agent': 'Django-Interim-Kelio-Sync/4.1-NewAPI',
                'Accept': 'text/xml, application/xml',
                'Accept-Encoding': 'gzip, deflate'
            })
            
            session.timeout = self.config.timeout_seconds or 30
            
            logger.info(f"Session HTTP creee pour {username}")
            return session
            
        except Exception as e:
            logger.error(f"Erreur creation session HTTP Kelio: {e}")
            raise KelioConnectionError(
                f"Erreur creation session HTTP: {e}",
                details={'url': self.config.url_base, 'session_error': str(e)}
            )
    
    def _get_soap_client(self, service_name, use_fallback=False):
        """Recupere ou cree un client SOAP pour un service avec support du fallback"""
        # Determiner le nom du client selon le mode fallback
        client_key = f"{service_name}_fallback" if use_fallback else service_name
        
        if client_key not in self.clients:
            # Trouver la configuration du service
            service_config = None
            for config in self.services_config.values():
                if config['service_name'] == service_name:
                    service_config = config
                    break
            
            if not service_config:
                raise ValueError(f"Service {service_name} non configure")
            
            # Choisir la configuration appropriée selon le mode fallback
            if use_fallback and 'fallback_service' in service_config:
                actual_service_name = service_config['fallback_service']
                wsdl_path = service_config['fallback_wsdl_path']
                timeout = service_config.get('timeout', 30)
            else:
                actual_service_name = service_name
                wsdl_path = service_config['wsdl_path']
                timeout = service_config['timeout']
            
            wsdl_url = f"{self.config.url_base}/{wsdl_path}"
            
            print(f">>> Creation client SOAP pour {actual_service_name}")
            print(f">>> URL WSDL: {wsdl_url}")
            
            try:
                settings_soap = Settings(strict=False, xml_huge_tree=True)
                transport = Transport(session=self.session, timeout=timeout)
                
                client = Client(wsdl_url, settings=settings_soap, transport=transport)
                
                self.clients[client_key] = client
                logger.info(f"OK Client SOAP cree pour {actual_service_name}")
                
            except Exception as e:
                logger.error(f"ERROR Erreur creation client SOAP {actual_service_name}: {e}")
                raise KelioConnectionError(
                    f"Erreur creation client SOAP {actual_service_name}: {e}",
                    details={'url': wsdl_url, 'timeout': timeout, 'service_name': actual_service_name, 'error': str(e)}
                )
        
        return self.clients[client_key]
    
    # ================================================================
    # METHODES PRINCIPALES - REFACTORISEES POUR NOUVELLES API + FALLBACK
    # ================================================================
    
    def synchroniser_tous_les_employes(self, mode='complet'):
        """Synchronise tous les employes depuis Kelio via EmployeeProfessionalDataService avec fallback automatique"""
        logger.info(f">>> Debut synchronisation employes V4.1 - Mode: {mode}")
        
        resultats = {
            'mode': mode,
            'timestamp_debut': timezone.now(),
            'employees_traites': 0,
            'employees_reussis': 0,
            'employees_erreurs': 0,
            'services_executes': {},
            'erreurs': [],
            'statut_global': 'en_cours',
            'donnees_globales': {
                'employes_traites': 0,
                'nouveaux_employes': 0,
                'employes_mis_a_jour': 0,
                'erreurs': 0
            },
            'metadata': {
                'nb_appels_api': 0,
                'duree_totale_ms': 0,
                'service_utilise': None,
                'fallback_utilise': False
            }
        }
        
        try:
            # ETAPE 1: Recuperer la liste complete des employes via EmployeeListService
            logger.info(">>> ETAPE 1: Recuperation via EmployeeListService")
            employees_data = self._get_all_employees_with_fallback()
            
            if not employees_data:
                # ETAPE 1 bis: Fallback vers EmployeeService
                logger.info(">>> ETAPE 1 bis: Fallback vers EmployeeService")
                employees_data = self._get_all_employees_fallback_service()
                resultats['metadata']['fallback_utilise'] = True
                resultats['metadata']['service_utilise'] = 'EmployeeService'
            else:
                resultats['metadata']['service_utilise'] = 'EmployeeListService'
            
            if not employees_data:
                resultats['statut_global'] = 'echec'
                resultats['erreur'] = 'Aucun employe recupere depuis Kelio EmployeeListService ou EmployeeService'
                return resultats
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via {resultats['metadata']['service_utilise']}")
            resultats['employees_total'] = len(employees_data)
            resultats['donnees_globales']['employes_traites'] = len(employees_data)
            
            # ETAPE 2: Mettre a jour les tables User, ProfilUtilisateur et donnees etendues
            logger.info(">>> ETAPE 2: Mise a jour des tables User, ProfilUtilisateur et donnees etendues")
            mise_a_jour_resultats = self._update_users_and_profiles_from_employee_data(employees_data)
            resultats['mise_a_jour_tables'] = mise_a_jour_resultats
            
            # Mettre à jour les statistiques globales
            resultats['donnees_globales']['nouveaux_employes'] = mise_a_jour_resultats.get('users_crees', 0)
            resultats['donnees_globales']['employes_mis_a_jour'] = mise_a_jour_resultats.get('users_mis_a_jour', 0)
            resultats['donnees_globales']['erreurs'] = len(mise_a_jour_resultats.get('erreurs', []))
            
            # ETAPE 3: Iterer sur chaque employe pour les donnees peripheriques (si mode complet)
            if mode == 'complet':
                logger.info(">>> ETAPE 3: Recuperation des donnees peripheriques par employe")
                
                for employee in employees_data:
                    matricule = employee.get('matricule')
                    if not matricule:
                        continue
                    
                    try:
                        resultats['employees_traites'] += 1
                        logger.info(f">>> Traitement employe {matricule} ({resultats['employees_traites']}/{len(employees_data)})")
                        
                        # Synchroniser les donnees peripheriques
                        donnees_peripheriques = self._synchroniser_donnees_peripheriques_employe_v41(matricule)
                        
                        if donnees_peripheriques.get('statut_global') in ['reussi', 'partiel']:
                            resultats['employees_reussis'] += 1
                        else:
                            resultats['employees_erreurs'] += 1
                            
                        resultats['metadata']['nb_appels_api'] += donnees_peripheriques.get('nb_appels', 0)
                        
                    except Exception as e:
                        resultats['employees_erreurs'] += 1
                        error_msg = f"Erreur employe {matricule}: {str(e)}"
                        resultats['erreurs'].append(error_msg)
                        logger.error(f"ERROR {error_msg}")
            
            # Determiner le statut global
            if resultats['donnees_globales']['erreurs'] == 0:
                resultats['statut_global'] = 'reussi'
            elif resultats['donnees_globales']['nouveaux_employes'] > 0 or resultats['donnees_globales']['employes_mis_a_jour'] > 0:
                resultats['statut_global'] = 'partiel'
            else:
                resultats['statut_global'] = 'echec'
            
            # Metadonnees finales
            duree_totale = (timezone.now() - resultats['timestamp_debut']).total_seconds() * 1000
            resultats['metadata']['duree_totale_ms'] = duree_totale
            resultats['timestamp_fin'] = timezone.now()
            
            # Resume final
            resultats['resume'] = {
                'employees_total': resultats['donnees_globales']['employes_traites'],
                'employees_reussis': resultats['donnees_globales']['nouveaux_employes'] + resultats['donnees_globales']['employes_mis_a_jour'],
                'employees_erreurs': resultats['donnees_globales']['erreurs'],
                'taux_reussite': round(
                    ((resultats['donnees_globales']['nouveaux_employes'] + resultats['donnees_globales']['employes_mis_a_jour']) / max(1, resultats['donnees_globales']['employes_traites'])) * 100, 1
                ),
                'duree_totale_sec': round(duree_totale / 1000, 2),
                'service_utilise': resultats['metadata']['service_utilise'],
                'fallback_utilise': resultats['metadata']['fallback_utilise']
            }
            
            status_emoji = {
                'reussi': 'OK',
                'partiel': 'WARNING', 
                'echec': 'ERROR'
            }.get(resultats['statut_global'], 'UNKNOWN')
            
            logger.info(f"{status_emoji} Synchronisation complete V4.1 terminee: {resultats['statut_global']} en {duree_totale:.0f}ms")
            return resultats
            
        except Exception as e:
            logger.error(f"ERROR Erreur critique synchronisation complete V4.1: {e}")
            resultats['statut_global'] = 'erreur_critique'
            resultats['erreur'] = str(e)
            resultats['timestamp_fin'] = timezone.now()
            return resultats
    
    def synchroniser_employe_specifique(self, matricule, mode='complet'):
        """Synchronise un employe specifique avec toutes ses donnees via les nouvelles API"""
        logger.info(f">>> Synchronisation employe specifique V4.1: {matricule} - Mode: {mode}")
        
        resultats = {
            'matricule': matricule,
            'mode': mode,
            'timestamp_debut': timezone.now(),
            'donnees_recuperees': {},
            'erreurs': [],
            'statut_global': 'en_cours',
            'metadata': {
                'nb_appels_api': 0,
                'services_reussis': 0,
                'services_erreur': 0
            }
        }
        
        try:
            # ETAPE 1: Recuperer les donnees professionnelles de l'employe
            logger.info(f">>> ETAPE 1: Recuperation donnees professionnelles pour {matricule}")
            employee_data = self._get_single_employee_professional_data(matricule)
            
            if not employee_data:
                raise KelioEmployeeNotFoundError(f"Employe {matricule} non trouve dans EmployeeProfessionalDataService")
            
            resultats['donnees_recuperees']['employee_professional_data'] = employee_data
            resultats['metadata']['nb_appels_api'] += 1
            resultats['metadata']['services_reussis'] += 1
            
            # ETAPE 2: Mettre a jour les tables principales
            mise_a_jour = self._update_single_user_and_profile_from_professional_data(employee_data)
            resultats['mise_a_jour'] = mise_a_jour
            
            # ETAPE 3: Recuperer les donnees peripheriques si mode complet
            if mode == 'complet':
                logger.info(f">>> ETAPE 3: Recuperation des donnees peripheriques pour {matricule}")
                donnees_peripheriques = self._synchroniser_donnees_peripheriques_employe_v41(matricule)
                
                resultats['donnees_peripheriques'] = donnees_peripheriques
                resultats['metadata']['nb_appels_api'] += donnees_peripheriques.get('nb_appels', 0)
                resultats['metadata']['services_reussis'] += donnees_peripheriques.get('services_reussis', 0)
                resultats['metadata']['services_erreur'] += donnees_peripheriques.get('services_erreur', 0)
            
            # Determiner le statut global
            if resultats['metadata']['services_erreur'] == 0:
                resultats['statut_global'] = 'reussi'
            elif resultats['metadata']['services_reussis'] > 0:
                resultats['statut_global'] = 'partiel'
            else:
                resultats['statut_global'] = 'echec'
            
            # Metadonnees finales
            duree_totale = (timezone.now() - resultats['timestamp_debut']).total_seconds() * 1000
            resultats['metadata']['duree_totale_ms'] = duree_totale
            resultats['timestamp_fin'] = timezone.now()
            
            logger.info(f"OK Synchronisation V4.1 {matricule} terminee: {resultats['statut_global']}")
            return resultats
            
        except Exception as e:
            logger.error(f"ERROR Erreur synchronisation V4.1 {matricule}: {e}")
            resultats['statut_global'] = 'erreur'
            resultats['erreur'] = str(e)
            resultats['timestamp_fin'] = timezone.now()
            return resultats

    # ================================================================
    # METHODES AVEC FALLBACK AUTOMATIQUE
    # ================================================================
    
    def _get_all_employees_with_fallback(self):
        """Recupere tous les employes via EmployeeListService avec fallback automatique"""
        try:
            client = self._get_soap_client('EmployeeListService')
            
            # Utiliser la requete documentee pour tous les employes
            logger.debug(">>> Appel EmployeeListService.exportEmployeeList")
            response = client.service.exportEmployeeList()
            
            employees_data = self._extract_employee_list_from_response(response)
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via EmployeeListService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur EmployeeListService: {e}")
            # Ne pas relancer l'exception, permettre le fallback
            return None
    
    def _get_all_employees_fallback_service(self):
        """Fallback vers EmployeeService classique"""
        try:
            client = self._get_soap_client('EmployeeListService', use_fallback=True)  # Utilise le fallback
            
            # Utiliser la methode classique EmployeeService
            logger.debug(">>> Appel EmployeeService.exportEmployees")
            response = client.service.exportEmployees()
            
            employees_data = self._extract_employee_service_from_response(response)
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via EmployeeService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur EmployeeService: {e}")
            return []
    
    # ================================================================
    # METHODES D'EXTRACTION POUR DIFFERENTS FORMATS DE REPONSE
    # ================================================================
    
    def _extract_employee_list_from_response(self, response):
        """Extrait les employes depuis EmployeeListService"""
        try:
            employees_data = []
            
            # Traiter la reponse selon la structure EmployeeListService
            if hasattr(response, 'exportedEmployeeList'):
                employees_raw = response.exportedEmployeeList
            elif hasattr(response, 'employees'):
                employees_raw = response.employees
            elif hasattr(response, 'employeeList'):
                employees_raw = response.employeeList
            else:
                logger.warning("Structure de reponse EmployeeListService non reconnue")
                return employees_data
            
            if not isinstance(employees_raw, list):
                employees_raw = [employees_raw] if employees_raw else []
            
            for emp in employees_raw:
                emp_data = self._extract_employee_data_from_object(emp, 'EmployeeListService')
                if emp_data:
                    employees_data.append(emp_data)
            
            logger.debug(f"OK {len(employees_data)} employe(s) extrait(s) depuis EmployeeListService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction EmployeeListService: {e}")
            return []
    
    def _extract_employee_service_from_response(self, response):
        """
        VERSION CORRIGÉE - Extraction robuste des employés depuis EmployeeService
        Remplace la méthode existante qui ne parvenait pas à extraire les données
        """
        try:
            logger.info("🚀 === DÉBUT EXTRACTION EMPLOYÉS VERSION CORRIGÉE ===")
            employees_data = []
            
            # === DEBUG INITIAL ===
            logger.info(f"📋 Type réponse: {type(response)}")
            logger.info(f"📋 Classe: {response.__class__.__name__}")
            response_str = str(response)
            logger.info(f"📋 Taille: {len(response_str)} caractères")
            logger.info(f"📋 Aperçu: {response_str[:200]}...")
            
            # === STRATÉGIE 1: SERIALIZE_OBJECT (ZEEP) ===
            try:
                logger.info("🔄 STRATÉGIE 1: serialize_object...")
                
                serialized = serialize_object(response)
                logger.info(f"📦 Sérialisé: {type(serialized)}")
                
                if serialized:
                    if isinstance(serialized, dict):
                        logger.info(f"📦 Dict avec clés: {list(serialized.keys())}")
                        employees_data = self._extract_from_serialized_dict(serialized)
                        
                    elif isinstance(serialized, list):
                        logger.info(f"📦 Liste de {len(serialized)} éléments")
                        employees_data = self._extract_from_serialized_list(serialized)
                    
                    else:
                        logger.info(f"📦 Objet unique: {type(serialized)}")
                        emp_data = self._extract_single_employee_from_object(serialized)
                        if emp_data:
                            employees_data = [emp_data]
                    
                    if employees_data:
                        logger.info(f"✅ STRATÉGIE 1 RÉUSSIE: {len(employees_data)} employés")
                        return employees_data
            
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 1 échouée: {e}")
            
            # === STRATÉGIE 2: EXPLORATION DIRECTE DES ATTRIBUTS ===
            try:
                logger.info("🔄 STRATÉGIE 2: exploration attributs...")
                
                all_attrs = [attr for attr in dir(response) if not attr.startswith('_')]
                logger.info(f"📋 Attributs: {all_attrs}")
                
                for attr_name in all_attrs:
                    try:
                        attr_value = getattr(response, attr_name)
                        if callable(attr_value) or attr_value is None:
                            continue
                        
                        logger.info(f"🔍 {attr_name}: {type(attr_value)} = {str(attr_value)[:100]}...")
                        
                        # Si c'est une liste d'objets
                        if isinstance(attr_value, list) and attr_value:
                            logger.info(f"📦 Liste trouvée: {len(attr_value)} éléments")
                            employees_data = self._process_potential_employee_list(attr_value, attr_name)
                            if employees_data:
                                logger.info(f"✅ STRATÉGIE 2 RÉUSSIE: {len(employees_data)} employés via {attr_name}")
                                return employees_data
                        
                        # Si c'est un objet unique qui ressemble à un employé
                        elif self._is_employee_like_object(attr_value):
                            logger.info(f"🎯 Objet employé détecté: {attr_name}")
                            emp_data = self._extract_single_employee_from_object(attr_value)
                            if emp_data:
                                employees_data = [emp_data]
                                logger.info(f"✅ STRATÉGIE 2 RÉUSSIE: 1 employé via {attr_name}")
                                return employees_data
                    
                    except Exception as e:
                        logger.debug(f"Erreur attribut {attr_name}: {e}")
                        continue
            
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 2 échouée: {e}")
            
            # === STRATÉGIE 3: TRAITER RÉPONSE COMME EMPLOYÉ UNIQUE ===
            try:
                logger.info("🔄 STRATÉGIE 3: réponse comme employé unique...")
                
                if self._is_employee_like_object(response):
                    emp_data = self._extract_single_employee_from_object(response)
                    if emp_data:
                        employees_data = [emp_data]
                        logger.info(f"✅ STRATÉGIE 3 RÉUSSIE: 1 employé")
                        return employees_data
            
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 3 échouée: {e}")
            
            # === STRATÉGIE 4: EXPLORATION RÉCURSIVE ===
            try:
                logger.info("🔄 STRATÉGIE 4: exploration récursive...")
                employees_data = self._recursive_employee_search(response)
                if employees_data:
                    logger.info(f"✅ STRATÉGIE 4 RÉUSSIE: {len(employees_data)} employés")
                    return employees_data
            
            except Exception as e:
                logger.warning(f"⚠️ Stratégie 4 échouée: {e}")
            
            # === ÉCHEC COMPLET ===
            logger.error("❌ TOUTES LES STRATÉGIES ONT ÉCHOUÉ")
            logger.error("🔍 DIAGNOSTIC FINAL:")
            logger.error(f"   Type: {type(response)}")
            logger.error(f"   Contenu: {str(response)[:300]}...")
            logger.error(f"   Attributs: {[attr for attr in dir(response) if not attr.startswith('_')]}")
            
            # Log du XML brut si disponible
            if hasattr(response, '_raw_response'):
                logger.error(f"   XML brut: {str(response._raw_response)[:200]}...")
            
            return []
            
        except Exception as e:
            logger.error(f"ERROR Exception critique extraction: {e}", exc_info=True)
            return []


    def _extract_from_serialized_dict(self, serialized_dict):
        """Extrait employés depuis un dictionnaire sérialisé"""
        try:
            employees = []
            
            for key, value in serialized_dict.items():
                key_lower = key.lower()
                
                # Chercher des clés prometteuses
                if any(keyword in key_lower for keyword in ['employee', 'export', 'data', 'list', 'result']):
                    logger.info(f"🎯 Clé prometteuse: {key}")
                    
                    if isinstance(value, list) and value:
                        # Liste d'employés potentiels
                        for item in value:
                            emp_data = self._extract_employee_from_dict_item(item)
                            if emp_data:
                                employees.append(emp_data)
                    
                    elif isinstance(value, dict):
                        # Objet employé unique
                        emp_data = self._extract_employee_from_dict_item(value)
                        if emp_data:
                            employees.append(emp_data)
            
            return employees
        except Exception as e:
            logger.debug(f"Erreur extraction dict sérialisé: {e}")
            return []


    def _extract_from_serialized_list(self, serialized_list):
        """Extrait employés depuis une liste sérialisée"""
        try:
            employees = []
            
            for item in serialized_list:
                emp_data = self._extract_employee_from_dict_item(item)
                if emp_data:
                    employees.append(emp_data)
            
            return employees
        except Exception as e:
            logger.debug(f"Erreur extraction liste sérialisée: {e}")
            return []


    def _extract_employee_from_dict_item(self, item):
        """Extrait un employé depuis un élément dictionnaire"""
        try:
            if not isinstance(item, dict):
                return None
            
            # Mapping des champs courants
            field_mapping = {
                'matricule': ['employeeIdentificationNumber', 'identificationNumber', 'employeeNumber', 'id', 'matricule', 'empId'],
                'employee_key': ['employeeKey', 'key', 'employee_id'],
                'badge_code': ['employeeBadgeCode', 'badgeCode', 'badge'],
                'nom': ['employeeSurname', 'surname', 'lastName', 'nom', 'familyName'],
                'prenom': ['employeeFirstName', 'firstName', 'prenom', 'givenName'],
                'email': ['professionalEmail', 'email', 'emailAddress', 'workEmail'],
                'telephone': ['professionalPhoneNumber1', 'phoneNumber', 'telephone', 'phone'],
                'archived': ['archivedEmployee', 'archived', 'inactive', 'isArchived'],
                'department': ['currentDepartmentDescription', 'departmentDescription', 'department'],
                'job': ['currentJobDescription', 'jobDescription', 'job', 'jobTitle']
            }
            
            emp_data = {}
            
            for target_field, possible_keys in field_mapping.items():
                for key in possible_keys:
                    if key in item and item[key] is not None and item[key] != '':
                        emp_data[target_field] = item[key]
                        break
            
            # Générer matricule si manquant
            if not emp_data.get('matricule'):
                nom = emp_data.get('nom', '')
                prenom = emp_data.get('prenom', '')
                if nom or prenom:
                    emp_data['matricule'] = f"{prenom[:3]}{nom[:3]}_{uuid.uuid4().hex[:4]}".upper()
                else:
                    emp_data['matricule'] = f"EMP_{uuid.uuid4().hex[:8].upper()}"
            
            # Ajouter métadonnées
            emp_data.update({
                'source': 'dict_extraction',
                'timestamp_sync': timezone.now().isoformat()
            })
            
            return emp_data if emp_data.get('matricule') else None
        
        except Exception as e:
            logger.debug(f"Erreur extraction dict item: {e}")
            return None


    def _process_potential_employee_list(self, obj_list, source_attr):
        """Traite une liste d'objets potentiellement employés"""
        try:
            employees = []
            
            for i, item in enumerate(obj_list):
                logger.debug(f"📋 Élément {i}: {type(item)}")
                
                emp_data = None
                
                # Si c'est un dictionnaire
                if isinstance(item, dict):
                    emp_data = self._extract_employee_from_dict_item(item)
                
                # Si c'est un objet avec attributs
                elif hasattr(item, '__dict__') or self._is_employee_like_object(item):
                    emp_data = self._extract_single_employee_from_object(item)
                
                if emp_data:
                    emp_data['source'] = f"{source_attr}[{i}]"
                    employees.append(emp_data)
                    logger.debug(f"✅ Employé {i} extrait: {emp_data.get('matricule')}")
            
            return employees
        
        except Exception as e:
            logger.debug(f"Erreur traitement liste: {e}")
            return []


    def _is_employee_like_object(self, obj):
        """Détermine si un objet ressemble à un employé"""
        try:
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return False
            
            # Indicateurs d'employé
            employee_indicators = [
                'employee', 'name', 'nom', 'surname', 'firstname', 'prenom',
                'id', 'key', 'matricule', 'badge', 'identification',
                'email', 'phone', 'telephone', 'department'
            ]
            
            # Récupérer attributs/clés
            obj_attrs = []
            
            if isinstance(obj, dict):
                obj_attrs = list(obj.keys())
            elif hasattr(obj, '__dict__'):
                obj_attrs.extend(obj.__dict__.keys())
            
            if hasattr(obj, '__class__'):
                obj_attrs.extend([attr for attr in dir(obj) if not attr.startswith('_')])
            
            # Compter correspondances
            matches = 0
            for attr in obj_attrs:
                attr_lower = str(attr).lower()
                for indicator in employee_indicators:
                    if indicator in attr_lower:
                        matches += 1
                        break
            
            is_employee = matches >= 2
            
            if is_employee:
                logger.debug(f"🎯 Objet employé détecté: {matches} correspondances")
            
            return is_employee
        
        except Exception as e:
            logger.debug(f"Erreur évaluation employé: {e}")
            return False


    def _extract_single_employee_from_object(self, obj):
        """Extrait un employé depuis un objet unique"""
        try:
            emp_data = {}
            
            # Mapping des attributs
            attr_mappings = {
                'matricule': ['employeeIdentificationNumber', 'identificationNumber', 'employeeNumber', 'id', 'matricule', 'empId'],
                'employee_key': ['employeeKey', 'key', 'employee_id'],
                'badge_code': ['employeeBadgeCode', 'badgeCode', 'badge'],
                'nom': ['employeeSurname', 'surname', 'lastName', 'nom', 'familyName'],
                'prenom': ['employeeFirstName', 'firstName', 'prenom', 'givenName'],
                'email': ['professionalEmail', 'email', 'emailAddress', 'workEmail'],
                'telephone': ['professionalPhoneNumber1', 'phoneNumber', 'telephone', 'phone'],
                'archived': ['archivedEmployee', 'archived', 'inactive'],
                'department': ['currentDepartmentDescription', 'departmentDescription', 'department'],
                'job': ['currentJobDescription', 'jobDescription', 'job']
            }
            
            for target_field, possible_attrs in attr_mappings.items():
                value = None
                
                for attr in possible_attrs:
                    # Essayer accès direct
                    if hasattr(obj, attr):
                        try:
                            value = getattr(obj, attr)
                            if value is not None and value != '':
                                break
                        except:
                            pass
                    
                    # Essayer via __dict__
                    if hasattr(obj, '__dict__') and attr in obj.__dict__:
                        try:
                            value = obj.__dict__[attr]
                            if value is not None and value != '':
                                break
                        except:
                            pass
                
                if value is not None:
                    emp_data[target_field] = str(value)
            
            # Générer matricule si nécessaire
            if not emp_data.get('matricule'):
                nom = emp_data.get('nom', '')
                prenom = emp_data.get('prenom', '')
                if nom or prenom:
                    emp_data['matricule'] = f"{prenom[:3]}{nom[:3]}_{uuid.uuid4().hex[:4]}".upper()
                else:
                    emp_data['matricule'] = f"OBJ_{uuid.uuid4().hex[:8].upper()}"
            
            # Métadonnées
            emp_data.update({
                'source': 'object_extraction',
                'timestamp_sync': timezone.now().isoformat()
            })
            
            return emp_data if any(emp_data.get(k) for k in ['nom', 'prenom', 'email']) else None
        
        except Exception as e:
            logger.debug(f"Erreur extraction objet unique: {e}")
            return None


    def _recursive_employee_search(self, obj, path="", depth=0, max_depth=2):
        """Recherche récursive d'employés dans la structure"""
        try:
            if depth > max_depth:
                return []
            
            employees = []
            
            # Si c'est une liste
            if isinstance(obj, list):
                for i, item in enumerate(obj):
                    sub_employees = self._recursive_employee_search(item, f"{path}[{i}]", depth+1, max_depth)
                    employees.extend(sub_employees)
            
            # Si ça ressemble à un employé
            elif self._is_employee_like_object(obj):
                emp_data = self._extract_single_employee_from_object(obj)
                if emp_data:
                    emp_data['source'] = f"recursive_{path}"
                    employees.append(emp_data)
            
            # Si c'est un objet avec attributs
            elif hasattr(obj, '__dict__') or (hasattr(obj, '__class__') and not isinstance(obj, (str, int, float, bool))):
                # Explorer les attributs prometteurs
                attrs_to_check = []
                
                if hasattr(obj, '__dict__'):
                    attrs_to_check.extend([(k, v) for k, v in obj.__dict__.items()])
                
                for attr_name in [a for a in dir(obj) if not a.startswith('_')][:5]:  # Limiter
                    try:
                        attr_value = getattr(obj, attr_name)
                        if not callable(attr_value):
                            attrs_to_check.append((attr_name, attr_value))
                    except:
                        pass
                
                for attr_name, attr_value in attrs_to_check:
                    if attr_value is not None:
                        sub_employees = self._recursive_employee_search(attr_value, f"{path}.{attr_name}", depth+1, max_depth)
                        employees.extend(sub_employees)
            
            return employees
        
        except Exception as e:
            logger.debug(f"Erreur recherche récursive: {e}")
            return []
        
    def _looks_like_employee_data(self, value, attr_name):
        """Determine si une valeur ressemble a des donnees d'employe"""
        try:
            # Criteres pour identifier des donnees d'employe
            if value is None:
                return False
            
            # Si c'est une liste ou un objet iterable
            if isinstance(value, (list, tuple)):
                if len(value) > 0:
                    # Verifier le premier element
                    first_item = value[0]
                    return self._looks_like_single_employee(first_item)
                return False
            
            # Si c'est un objet unique
            return self._looks_like_single_employee(value)
            
        except Exception as e:
            logger.debug(f">>> Erreur evaluation donnees employee pour {attr_name}: {e}")
            return False
    
    def _looks_like_single_employee(self, obj):
        """Determine si un objet ressemble a un employe unique"""
        try:
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return False
            
            # Mots-cles qui indiquent des donnees d'employe
            employee_keywords = [
                'employee', 'employe', 'person', 'user', 'staff', 'worker',
                'name', 'nom', 'surname', 'firstname', 'prenom',
                'id', 'key', 'matricule', 'badge', 'identification',
                'email', 'phone', 'telephone', 'department', 'departement',
                'job', 'position', 'poste', 'title', 'fonction'
            ]
            
            # Chercher dans les attributs de l'objet
            if hasattr(obj, '__dict__'):
                obj_attrs = obj.__dict__.keys()
            else:
                obj_attrs = [attr for attr in dir(obj) if not attr.startswith('_')]
            
            # Compter les attributs qui correspondent
            matches = 0
            for attr in obj_attrs:
                attr_lower = attr.lower()
                for keyword in employee_keywords:
                    if keyword in attr_lower:
                        matches += 1
                        break
            
            # Si au moins 2 attributs correspondent, c'est probablement un employe
            is_employee = matches >= 2
            
            if is_employee:
                logger.debug(f">>> Objet identifie comme employe: {matches} attributs correspondants")
                logger.debug(f">>> Attributs: {list(obj_attrs)[:10]}...")  # Limiter pour le log
            
            return is_employee
            
        except Exception as e:
            logger.debug(f">>> Erreur evaluation employe unique: {e}")
            return False
    
    def _extract_employee_data_from_object(self, emp, source_service):
        """Extrait les donnees d'un employe depuis un objet SOAP, independamment du service"""
        try:
            # Mappage des attributs selon les differents services (exhaustif)
            attr_mappings = {
                # Identification de base - essayer plusieurs patterns
                'matricule': [
                    'employeeIdentificationNumber', 'identificationNumber', 'employeeNumber', 
                    'id', 'matricule', 'employeeId', 'empId', 'badgeNumber'
                ],
                'employee_key': [
                    'employeeKey', 'key', 'employee_id', 'empKey', 'employeeInternalId'
                ],
                'badge_code': [
                    'employeeBadgeCode', 'badgeCode', 'badge', 'badgeNumber', 'employeeBadge'
                ],
                'nom': [
                    'employeeSurname', 'surname', 'lastName', 'nom', 'familyName', 'name'
                ],
                'prenom': [
                    'employeeFirstName', 'firstName', 'prenom', 'givenName', 'fname'
                ],
                'email': [
                    'professionalEmail', 'email', 'emailAddress', 'workEmail', 'employeeEmail'
                ],
                'telephone': [
                    'professionalPhoneNumber1', 'phoneNumber', 'telephone', 'phone', 'workPhone'
                ],
                'archived': [
                    'archivedEmployee', 'archived', 'inactive', 'isArchived', 'deleted'
                ],
                
                # Données organisationnelles
                'department': [
                    'currentDepartmentDescription', 'departmentDescription', 'department', 
                    'dept', 'departmentName', 'currentSectionDescription', 'sectionDescription'
                ],
                'section': [
                    'currentSectionDescription', 'sectionDescription', 'section', 
                    'sectionName', 'currentSubDepartmentDescription'
                ],
                'job': [
                    'currentJobDescription', 'jobDescription', 'job', 'jobTitle', 
                    'position', 'currentJobTitle', 'employeeJob'
                ],
                'firm': [
                    'currentFirmDescription', 'firmDescription', 'firm', 'company', 
                    'companyName', 'organization'
                ],
                
                # Dates importantes
                'date_embauche': [
                    'arrivalInCompanyDate', 'hireDate', 'startDate', 'employmentDate', 
                    'dateEmbauche', 'joiningDate'
                ],
                'date_fin': [
                    'currentPlannedEndDate', 'endDate', 'terminationDate', 'leavingDate', 
                    'contractEndDate'
                ]
            }
            
            emp_data = {}
            
            # Extraire chaque attribut en essayant plusieurs patterns
            for target_field, possible_attrs in attr_mappings.items():
                value = None
                for attr in possible_attrs:
                    value = safe_get_attribute(emp, attr)
                    if value is not None and value != '':
                        break
                
                # Convertir les dates si nécessaire
                if target_field in ['date_embauche', 'date_fin'] and value:
                    value = safe_date_conversion(value)
                
                # Convertir les booléens
                if target_field == 'archived' and value is not None:
                    if isinstance(value, str):
                        value = value.lower() in ['true', '1', 'yes', 'oui', 'active']
                    else:
                        value = bool(value)
                
                emp_data[target_field] = value
            
            # S'assurer qu'on a au minimum un matricule ou identifiant
            if not emp_data.get('matricule'):
                # Essayer d'autres champs d'identification en parcourant tous les attributs
                all_attrs = []
                try:
                    all_attrs = [attr for attr in dir(emp) if not attr.startswith('_')]
                except:
                    pass
                
                for attr in all_attrs:
                    if any(keyword in attr.lower() for keyword in ['id', 'number', 'code', 'matricule']):
                        value = safe_get_attribute(emp, attr)
                        if value and isinstance(value, (str, int)) and len(str(value)) >= 2:
                            emp_data['matricule'] = str(value)
                            break
            
            # Si on n'a toujours pas de matricule, générer un ID temporaire basé sur d'autres champs
            if not emp_data.get('matricule'):
                # Essayer de construire depuis nom/prénom
                nom = emp_data.get('nom', '')
                prenom = emp_data.get('prenom', '')
                if nom or prenom:
                    emp_data['matricule'] = f"{prenom[:3]}{nom[:3]}_{uuid.uuid4().hex[:4]}".upper()
                else:
                    emp_data['matricule'] = f"EMP_{uuid.uuid4().hex[:8].upper()}"
            
            # Nettoyage et validation des données essentielles
            matricule = emp_data.get('matricule', '').strip()
            if len(matricule) < 2:
                emp_data['matricule'] = f"EMP_{uuid.uuid4().hex[:8].upper()}"
            
            # Ajouter les métadonnées
            emp_data.update({
                'source': source_service.lower(),
                'timestamp_sync': timezone.now().isoformat(),
                'raw_attributes': [attr for attr in dir(emp) if not attr.startswith('_')][:20]  # Limiter pour debug
            })
            
            logger.debug(f">>> Employe extrait: {emp_data.get('matricule')} - {emp_data.get('prenom')} {emp_data.get('nom')}")
            return emp_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction donnees employe depuis {source_service}: {e}")
            return None
    
    # ================================================================
    # METHODES SPECIALISEES POUR EMPLOYEEPROFESSIONALDATASERVICE
    # ================================================================
    
    def _get_all_employees_professional_data(self):
        """Recupere tous les employes via EmployeeProfessionalDataService"""
        try:
            client = self._get_soap_client('EmployeeProfessionalDataService')
            
            # Utiliser la requete documentee pour tous les employes
            logger.debug(">>> Appel EmployeeProfessionalDataService.exportEmployeeProfessionalData")
            response = client.service.exportEmployeeProfessionalData(
                populationFilter='',  # Laisser vide pour obtenir tous les employes
                groupFilter=''        # Laisser vide pour obtenir tous les groupes
            )
            
            employees_data = self._extract_professional_data_from_response(response)
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via EmployeeProfessionalDataService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur recuperation EmployeeProfessionalDataService: {e}")
            raise KelioDataError(f"Erreur recuperation EmployeeProfessionalDataService: {e}")
    
    def _get_single_employee_professional_data(self, matricule):
        """Recupere les donnees d'un employe specifique via EmployeeProfessionalDataService"""
        try:
            client = self._get_soap_client('EmployeeProfessionalDataService')
            
            # Utiliser la requete documentee pour un employe specifique
            logger.debug(f">>> Appel EmployeeProfessionalDataService.exportEmployeeProfessionalDataList pour {matricule}")
            response = client.service.exportEmployeeProfessionalDataList(
                exportFilter={
                    'AskedPopulation': {
                        'employeeIdentificationNumber': matricule,
                        'populationMode': 1
                    }
                }
            )
            
            employees_data = self._extract_professional_data_from_response(response)
            
            if employees_data:
                logger.info(f">>> Employe {matricule} trouve via EmployeeProfessionalDataService")
                return employees_data[0]
            else:
                logger.warning(f">>> Employe {matricule} non trouve via EmployeeProfessionalDataService")
                return None
            
        except Exception as e:
            logger.error(f"ERROR Erreur recuperation employe {matricule} via EmployeeProfessionalDataService: {e}")
            raise KelioDataError(f"Erreur recuperation employe {matricule} via EmployeeProfessionalDataService: {e}")
    
    def _extract_professional_data_from_response(self, response):
        """Extrait les donnees professionnelles des employes de la reponse"""
        try:
            employees_data = []
            
            # Traiter la reponse selon la structure documentee
            if hasattr(response, 'exportedEmployeeProfessionalData'):
                employees_raw = response.exportedEmployeeProfessionalData
            elif hasattr(response, 'exportedEmployeesList'):
                employees_raw = response.exportedEmployeesList
            else:
                logger.warning("Structure de reponse EmployeeProfessionalDataService non reconnue")
                return employees_data
            
            if not isinstance(employees_raw, list):
                employees_raw = [employees_raw] if employees_raw else []
            
            for emp in employees_raw:
                # Extraire selon la structure documentee
                emp_data = {
                    # Identification de base
                    'employeeKey': safe_get_attribute(emp, 'employeeKey'),
                    'employeeIdentificationNumber': safe_get_attribute(emp, 'employeeIdentificationNumber', ''),
                    'employeeIdentificationCode': safe_get_attribute(emp, 'employeeIdentificationCode', ''),
                    'employeeBadgeCode': safe_get_attribute(emp, 'employeeBadgeCode', ''),
                    'employeeSurname': safe_get_attribute(emp, 'employeeSurname', ''),
                    'employeeFirstName': safe_get_attribute(emp, 'employeeFirstName', ''),
                    'employeeAbbreviation': safe_get_attribute(emp, 'employeeAbbreviation', ''),
                    'archivedEmployee': safe_get_attribute(emp, 'archivedEmployee', False),
                    
                    # Contact professionnel
                    'professionalEmail': safe_get_attribute(emp, 'professionalEmail', ''),
                    'professionalPhoneNumber1': safe_get_attribute(emp, 'professionalPhoneNumber1', ''),
                    'professionalPhoneNumber2': safe_get_attribute(emp, 'professionalPhoneNumber2', ''),
                    'professionalPhoneNumber3': safe_get_attribute(emp, 'professionalPhoneNumber3', ''),
                    'professionalPhoneNumber4': safe_get_attribute(emp, 'professionalPhoneNumber4', ''),
                    
                    # Donnees organisationnelles
                    'currentSectionKey': safe_get_attribute(emp, 'currentSectionKey'),
                    'currentSectionAbbreviation': safe_get_attribute(emp, 'currentSectionAbbreviation', ''),
                    'currentSectionDescription': safe_get_attribute(emp, 'currentSectionDescription', ''),
                    'currentDepartmentDescription': safe_get_attribute(emp, 'currentDepartmentDescription', ''),
                    'currentSubDepartmentDescription': safe_get_attribute(emp, 'currentSubDepartmentDescription', ''),
                    'currentFirmDescription': safe_get_attribute(emp, 'currentFirmDescription', ''),
                    
                    # Poste et responsabilites
                    'currentJobAbbreviation': safe_get_attribute(emp, 'currentJobAbbreviation', ''),
                    'currentJobDescription': safe_get_attribute(emp, 'currentJobDescription', ''),
                    'currentJobPositionCode': safe_get_attribute(emp, 'currentJobPositionCode', ''),
                    'currentProfessionalStatusCode': safe_get_attribute(emp, 'currentProfessionalStatusCode', ''),
                    'currentQualificationCode': safe_get_attribute(emp, 'currentQualificationCode', ''),
                    
                    # Contrat et temps de travail
                    'contractType': safe_get_attribute(emp, 'contractType'),
                    'currentTimeContractTypeCode': safe_get_attribute(emp, 'currentTimeContractTypeCode'),
                    'currentTimeContractValue': safe_get_attribute(emp, 'currentTimeContractValue'),
                    'currentTimeContractNumber': safe_get_attribute(emp, 'currentTimeContractNumber', ''),
                    'numberOfWeeklyHours': safe_get_attribute(emp, 'numberOfWeeklyHours'),
                    'fullTimeEquivalent': safe_get_attribute(emp, 'fullTimeEquivalent'),
                    'weeklyWorkedDayRate': safe_get_attribute(emp, 'weeklyWorkedDayRate'),
                    
                    # Dates importantes
                    'arrivalInCompanyDate': safe_date_conversion(safe_get_attribute(emp, 'arrivalInCompanyDate')),
                    'currentJobApplicationDate': safe_date_conversion(safe_get_attribute(emp, 'currentJobApplicationDate')),
                    'currentSectionAssigningDate': safe_date_conversion(safe_get_attribute(emp, 'currentSectionAssigningDate')),
                    'presenceManagementDate': safe_date_conversion(safe_get_attribute(emp, 'presenceManagementDate')),
                    'currentWorkingDurationApplicationDate': safe_date_conversion(safe_get_attribute(emp, 'currentWorkingDurationApplicationDate')),
                    'currentTimeContractApplicationDate': safe_date_conversion(safe_get_attribute(emp, 'currentTimeContractApplicationDate')),
                    'trialPeriodEndDate': safe_date_conversion(safe_get_attribute(emp, 'trialPeriodEndDate')),
                    'reasonForLeavingDate': safe_date_conversion(safe_get_attribute(emp, 'reasonForLeavingDate')),
                    'currentPlannedEndDate': safe_date_conversion(safe_get_attribute(emp, 'currentPlannedEndDate')),
                    'seniorityStartDate': safe_date_conversion(safe_get_attribute(emp, 'seniorityStartDate')),
                    
                    # Superviseur
                    'defaultSupervisorKey': safe_get_attribute(emp, 'defaultSupervisorKey'),
                    'defaultSupervisorBadgeCode': safe_get_attribute(emp, 'defaultSupervisorBadgeCode', ''),
                    'defaultSupervisorFirstName': safe_get_attribute(emp, 'defaultSupervisorFirstName', ''),
                    'defaultSupervisorSurname': safe_get_attribute(emp, 'defaultSupervisorSurname', ''),
                    'defaultSupervisorIdentificationCode': safe_get_attribute(emp, 'defaultSupervisorIdentificationCode', ''),
                    'defaultSupervisorIdentificationNumber': safe_get_attribute(emp, 'defaultSupervisorIdentificationNumber', ''),
                    
                    # Coefficients et classification
                    'currentCoefficientCode': safe_get_attribute(emp, 'currentCoefficientCode', ''),
                    'currentPersonnelCategoryCode': safe_get_attribute(emp, 'currentPersonnelCategoryCode'),
                    'wageBand': safe_get_attribute(emp, 'wageBand'),
                    'hourlyRate': safe_get_attribute(emp, 'hourlyRate'),
                    'invoicedRate': safe_get_attribute(emp, 'invoicedRate'),
                    
                    # Booleens speciaux
                    'toBeScheduled': safe_get_attribute(emp, 'toBeScheduled', False),
                    'isHRWorkspaceEmployee': safe_get_attribute(emp, 'isHRWorkspaceEmployee', False),
                    'trialPeriod': safe_get_attribute(emp, 'trialPeriod', False),
                    'isManagedInActivity': safe_get_attribute(emp, 'isManagedInActivity', False),
                    'automaticGenerationWorkingTime': safe_get_attribute(emp, 'automaticGenerationWorkingTime', False),
                    'remoteWorkingAutomaticClocking': safe_get_attribute(emp, 'remoteWorkingAutomaticClocking', False),
                    
                    # Metadonnees
                    'source': 'kelio_professional_data',
                    'timestamp_sync': timezone.now().isoformat()
                }
                employees_data.append(emp_data)
            
            logger.debug(f"OK {len(employees_data)} employe(s) extrait(s) depuis EmployeeProfessionalDataService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction donnees EmployeeProfessionalDataService: {e}")
            return []
    
    # ================================================================
    # METHODES DE MISE A JOUR DES MODELES DJANGO - VERSION ROBUSTE
    # ================================================================
    
    def _update_users_and_profiles_from_employee_data(self, employees_data):
        """Met a jour User, ProfilUtilisateur et donnees etendues depuis les donnees employes"""
        from ..models import (ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended, 
                            Departement, Site, Poste)
        
        resultats = {
            'timestamp_debut': timezone.now(),
            'users_crees': 0,
            'users_mis_a_jour': 0,
            'profils_crees': 0,
            'profils_mis_a_jour': 0,
            'donnees_etendues_traitees': 0,
            'donnees_kelio_traitees': 0,
            'erreurs': []
        }
        
        logger.info(f">>> Mise a jour de {len(employees_data)} employe(s) depuis les donnees employes")
        
        for emp_data in employees_data:
            try:
                matricule = emp_data.get('matricule') or emp_data.get('employeeIdentificationNumber')
                if not matricule:
                    continue
                
                with transaction.atomic():
                    # 1. Creer ou mettre a jour l'utilisateur Django
                    user, user_created = self._create_or_update_user_from_employee_data(emp_data)
                    if user_created:
                        resultats['users_crees'] += 1
                    else:
                        resultats['users_mis_a_jour'] += 1
                    
                    # 2. Creer ou mettre a jour le ProfilUtilisateur
                    profil, profil_created = self._create_or_update_profil_from_employee_data(emp_data, user)
                    if profil_created:
                        resultats['profils_crees'] += 1
                    else:
                        resultats['profils_mis_a_jour'] += 1
                    
                    # 3. Creer ou mettre a jour les donnees Kelio
                    self._create_or_update_kelio_data_from_employee_data(emp_data, profil)
                    resultats['donnees_kelio_traitees'] += 1
                    
                    # 4. Creer ou mettre a jour les donnees etendues
                    self._create_or_update_extended_data_from_employee_data(emp_data, profil)
                    resultats['donnees_etendues_traitees'] += 1
                    
                    # 5. Mettre a jour le statut de synchronisation
                    profil.kelio_last_sync = timezone.now()
                    profil.kelio_sync_status = 'REUSSI'
                    profil.save(update_fields=['kelio_last_sync', 'kelio_sync_status'])
                    
            except Exception as e:
                error_msg = f"Erreur traitement employe {matricule}: {str(e)}"
                resultats['erreurs'].append(error_msg)
                logger.error(f"ERROR {error_msg}")
        
        resultats['timestamp_fin'] = timezone.now()
        logger.info(f"OK Mise a jour terminee: {resultats['users_crees']} users crees, {resultats['profils_crees']} profils crees")
        
        return resultats
    
    def _create_or_update_user_from_employee_data(self, emp_data):
        """Cree ou met a jour un utilisateur Django depuis les donnees employes"""
        matricule = emp_data.get('matricule') or emp_data.get('employeeIdentificationNumber', '')
        prenom = emp_data.get('prenom') or emp_data.get('employeeFirstName', '')
        nom = emp_data.get('nom') or emp_data.get('employeeSurname', '')
        email = emp_data.get('email') or emp_data.get('professionalEmail', '')
        
        # Generer un username unique
        username = matricule or f"emp_{uuid.uuid4().hex[:8]}"
        
        try:
            # Chercher d'abord par email s'il existe
            user = None
            if email:
                user = User.objects.filter(email=email).first()
            
            # Sinon chercher par username
            if not user:
                user = User.objects.filter(username=username).first()
            
            if user:
                # Mettre a jour l'utilisateur existant
                user.first_name = prenom
                user.last_name = nom
                if email and not user.email:
                    user.email = email
                user.save()
                return user, False
            else:

                from django.utils.crypto import get_random_string
                
                # Creer un nouvel utilisateur
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=prenom,
                    last_name=nom,
                    password=get_random_string(length=20)
                )
                return user, True
                
        except Exception as e:
            logger.error(f"Erreur creation/mise a jour User pour {matricule}: {e}")
            raise
    
    def _create_or_update_profil_from_employee_data(self, emp_data, user):
        """
        VERSION CORRIGÉE - Gestion des contraintes UNIQUE sur kelio_employee_key
        """
        from ..models import ProfilUtilisateur, Departement, Site, Poste
        
        matricule = emp_data.get('matricule') or emp_data.get('employeeIdentificationNumber', '')
        kelio_employee_key = emp_data.get('employee_key') or emp_data.get('employeeKey')
        
        try:
            # Chercher le profil existant par matricule OU par kelio_employee_key
            profil = None
            
            # Recherche par matricule d'abord
            if matricule:
                profil = ProfilUtilisateur.objects.filter(matricule=matricule).first()
            
            # Si pas trouvé par matricule et qu'on a une kelio_employee_key, chercher par celle-ci
            if not profil and kelio_employee_key:
                profil = ProfilUtilisateur.objects.filter(kelio_employee_key=kelio_employee_key).first()
            
            # Déterminer le type de profil selon les données Kelio
            type_profil = self._determine_profile_type_from_employee_data(emp_data)
            
            # Déterminer le statut employé
            statut_employe = 'ACTIF'
            if emp_data.get('archived') or emp_data.get('archivedEmployee', False):
                statut_employe = 'SUSPENDU'
            if emp_data.get('date_fin') or emp_data.get('reasonForLeavingDate'):
                statut_employe = 'DEMISSION'
            
            if profil:
                # === MISE À JOUR DU PROFIL EXISTANT ===
                logger.debug(f"Mise à jour profil existant: {matricule}")
                
                profil.user = user
                profil.type_profil = type_profil
                profil.statut_employe = statut_employe
                profil.actif = not (emp_data.get('archived', False) or emp_data.get('archivedEmployee', False))
                
                # Mettre à jour kelio_employee_key seulement si elle est différente
                if kelio_employee_key and profil.kelio_employee_key != kelio_employee_key:
                    # Vérifier qu'aucun autre profil n'a déjà cette kelio_employee_key
                    existing_with_key = ProfilUtilisateur.objects.filter(
                        kelio_employee_key=kelio_employee_key
                    ).exclude(id=profil.id).first()
                    
                    if not existing_with_key:
                        profil.kelio_employee_key = kelio_employee_key
                    else:
                        logger.warning(f"kelio_employee_key {kelio_employee_key} déjà utilisée par {existing_with_key.matricule}")
                
                profil.kelio_badge_code = emp_data.get('badge_code', '') or emp_data.get('employeeBadgeCode', '')
                profil.date_embauche = emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate')
                profil.date_fin_contrat = emp_data.get('date_fin') or emp_data.get('currentPlannedEndDate')
                
                # Associer département, site, poste si disponibles
                self._associate_organizational_data_from_employee_data_SAFE(profil, emp_data)
                
                profil.save()
                return profil, False
                
            else:
                # === CRÉATION D'UN NOUVEAU PROFIL ===
                logger.debug(f"Création nouveau profil: {matricule}")
                
                # Vérifier que la kelio_employee_key n'est pas déjà utilisée
                if kelio_employee_key:
                    existing_with_key = ProfilUtilisateur.objects.filter(kelio_employee_key=kelio_employee_key).first()
                    if existing_with_key:
                        logger.warning(f"kelio_employee_key {kelio_employee_key} déjà utilisée par {existing_with_key.matricule}, ne pas l'assigner")
                        kelio_employee_key = None
                
                profil = ProfilUtilisateur.objects.create(
                    user=user,
                    matricule=matricule,
                    type_profil=type_profil,
                    statut_employe=statut_employe,
                    actif=not (emp_data.get('archived', False) or emp_data.get('archivedEmployee', False)),
                    kelio_employee_key=kelio_employee_key,  # Peut être None si déjà utilisée
                    kelio_badge_code=emp_data.get('badge_code', '') or emp_data.get('employeeBadgeCode', ''),
                    date_embauche=emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate'),
                    date_fin_contrat=emp_data.get('date_fin') or emp_data.get('currentPlannedEndDate')
                )
                
                # Associer département, site, poste si disponibles
                self._associate_organizational_data_from_employee_data_SAFE(profil, emp_data)
                
                return profil, True
                    
        except Exception as e:
            logger.error(f"Erreur création/mise à jour ProfilUtilisateur pour {matricule}: {e}")
            raise

    def _create_or_update_kelio_data_from_employee_data(self, emp_data, profil):
        """Cree ou met a jour les donnees Kelio specifiques"""
        from ..models import ProfilUtilisateurKelio
        
        try:
            kelio_data, created = ProfilUtilisateurKelio.objects.get_or_create(
                profil=profil,
                defaults={
                    'kelio_employee_key': emp_data.get('employee_key') or emp_data.get('employeeKey'),
                    'kelio_badge_code': emp_data.get('badge_code', '') or emp_data.get('employeeBadgeCode', ''),
                    'telephone_kelio': emp_data.get('telephone', '') or emp_data.get('professionalPhoneNumber1', ''),
                    'email_kelio': emp_data.get('email', '') or emp_data.get('professionalEmail', ''),
                    'date_embauche_kelio': emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate'),
                    'type_contrat_kelio': emp_data.get('currentTimeContractNumber', ''),
                    'temps_travail_kelio': emp_data.get('fullTimeEquivalent', 1.0),
                    'code_personnel': emp_data.get('employeeIdentificationCode', ''),
                    'horaires_specifiques_autorises': emp_data.get('automaticGenerationWorkingTime', False)
                }
            )
            
            if not created:
                # Mettre a jour les donnees existantes
                kelio_data.kelio_employee_key = emp_data.get('employee_key') or emp_data.get('employeeKey')
                kelio_data.kelio_badge_code = emp_data.get('badge_code', '') or emp_data.get('employeeBadgeCode', '')
                kelio_data.telephone_kelio = emp_data.get('telephone', '') or emp_data.get('professionalPhoneNumber1', '')
                kelio_data.email_kelio = emp_data.get('email', '') or emp_data.get('professionalEmail', '')
                kelio_data.date_embauche_kelio = emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate')
                kelio_data.type_contrat_kelio = emp_data.get('currentTimeContractNumber', '')
                kelio_data.temps_travail_kelio = emp_data.get('fullTimeEquivalent', 1.0)
                kelio_data.code_personnel = emp_data.get('employeeIdentificationCode', '')
                kelio_data.horaires_specifiques_autorises = emp_data.get('automaticGenerationWorkingTime', False)
                kelio_data.save()
            
            return kelio_data
            
        except Exception as e:
            logger.error(f"Erreur creation/mise a jour donnees Kelio pour {profil.matricule}: {e}")
            raise
    
    def _create_or_update_extended_data_from_employee_data(self, emp_data, profil):
        """Cree ou met a jour les donnees etendues"""
        from ..models import ProfilUtilisateurExtended
        
        try:
            extended_data, created = ProfilUtilisateurExtended.objects.get_or_create(
                profil=profil,
                defaults={
                    'telephone': emp_data.get('telephone', '') or emp_data.get('professionalPhoneNumber1', ''),
                    'telephone_portable': emp_data.get('professionalPhoneNumber2', ''),
                    'date_embauche': emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate'),
                    'date_fin_contrat': emp_data.get('date_fin') or emp_data.get('currentPlannedEndDate'),
                    'type_contrat': emp_data.get('currentTimeContractNumber', ''),
                    'temps_travail': emp_data.get('fullTimeEquivalent', 1.0),
                    'coefficient': emp_data.get('currentCoefficientCode', ''),
                    'niveau_classification': emp_data.get('currentPersonnelCategoryCode', ''),
                    'statut_professionnel': emp_data.get('currentProfessionalStatusCode', ''),
                    'disponible_interim': not (emp_data.get('archived', False) or emp_data.get('archivedEmployee', False)),
                    'rayon_deplacement_km': 50  # Valeur par defaut
                }
            )
            
            if not created:
                # Mettre a jour les donnees existantes
                extended_data.telephone = emp_data.get('telephone', '') or emp_data.get('professionalPhoneNumber1', '')
                extended_data.telephone_portable = emp_data.get('professionalPhoneNumber2', '')
                extended_data.date_embauche = emp_data.get('date_embauche') or emp_data.get('arrivalInCompanyDate')
                extended_data.date_fin_contrat = emp_data.get('date_fin') or emp_data.get('currentPlannedEndDate')
                extended_data.type_contrat = emp_data.get('currentTimeContractNumber', '')
                extended_data.temps_travail = emp_data.get('fullTimeEquivalent', 1.0)
                extended_data.coefficient = emp_data.get('currentCoefficientCode', '')
                extended_data.niveau_classification = emp_data.get('currentPersonnelCategoryCode', '')
                extended_data.statut_professionnel = emp_data.get('currentProfessionalStatusCode', '')
                extended_data.disponible_interim = not (emp_data.get('archived', False) or emp_data.get('archivedEmployee', False))
                extended_data.save()
            
            return extended_data
            
        except Exception as e:
            logger.error(f"Erreur creation/mise a jour donnees etendues pour {profil.matricule}: {e}")
            raise
    
    def _determine_profile_type_from_employee_data(self, emp_data):
        """Determine le type de profil selon les donnees professionnelles Kelio"""
        # Logique pour determiner le type de profil selon les codes Kelio
        job_position_code = emp_data.get('currentJobPositionCode', '')
        professional_status_code = emp_data.get('currentProfessionalStatusCode', '')
        
        # Mapping basique selon les codes courants
        if job_position_code == '01':  # Cadre
            return 'DIRECTEUR'
        elif job_position_code == '02':  # Agent de maitrise
            return 'RESPONSABLE'
        elif professional_status_code == '04':  # Agent de maitrise
            return 'RESPONSABLE'
        else:
            return 'UTILISATEUR'
    
    # 5. Modifiez la méthode _associate_organizational_data_from_employee_data pour corriger les erreurs UNIQUE
    def _associate_organizational_data_from_employee_data_SAFE(self, profil, emp_data):
        """
        VERSION SÉCURISÉE - Associe les données organisationnelles avec gestion des doublons
        """
        from ..models import Departement, Site, Poste
        
        try:
            # === DÉPARTEMENT avec gestion des doublons ===
            department_desc = (emp_data.get('department', '') or 
                            emp_data.get('currentDepartmentDescription', '') or 
                            emp_data.get('section', '') or 
                            emp_data.get('currentSectionDescription', ''))
            
            if department_desc:
                # Créer un code unique basé sur le nom
                base_code = department_desc[:10].upper().replace(' ', '').replace('-', '')[:10]
                if not base_code:
                    base_code = 'DEPT'
                
                # Chercher département existant par nom d'abord
                departement = Departement.objects.filter(nom=department_desc).first()
                
                if not departement:
                    # Générer un code unique
                    code_final = base_code
                    counter = 1
                    while Departement.objects.filter(code=code_final).exists():
                        code_final = f"{base_code[:7]}{counter:03d}"
                        counter += 1
                        if counter > 999:  # Sécurité
                            code_final = f"D{uuid.uuid4().hex[:8].upper()}"
                            break
                    
                    try:
                        departement = Departement.objects.create(
                            nom=department_desc,
                            description=f"Département importé depuis Kelio: {department_desc}",
                            code=code_final,
                            kelio_department_key=emp_data.get('currentSectionKey')
                        )
                        logger.debug(f"Département créé: {department_desc} (code: {code_final})")
                    except Exception as e:
                        logger.warning(f"Erreur création département {department_desc}: {e}")
                        # Essayer de récupérer un département existant par nom similaire
                        departement = Departement.objects.filter(
                            nom__icontains=department_desc[:20]
                        ).first()
                
                if departement:
                    profil.departement = departement
            
            # === SITE avec gestion similaire ===
            firm_desc = (emp_data.get('firm', '') or 
                        emp_data.get('currentFirmDescription', '') or 
                        'Site principal')
            
            if firm_desc:
                site = Site.objects.filter(nom=firm_desc).first()
                if not site:
                    try:
                        site = Site.objects.create(
                            nom=firm_desc,
                            adresse='Adresse à renseigner',
                            ville='Ville à renseigner',
                            code_postal='00000',
                            telephone=emp_data.get('telephone', '') or emp_data.get('professionalPhoneNumber1', ''),
                            email=emp_data.get('email', '') or emp_data.get('professionalEmail', '')
                        )
                        logger.debug(f"Site créé: {firm_desc}")
                    except Exception as e:
                        logger.warning(f"Erreur création site {firm_desc}: {e}")
                        # Utiliser le premier site disponible comme fallback
                        site = Site.objects.first()
                
                if site:
                    profil.site = site
            
            # === POSTE avec gestion des dépendances ===
            job_desc = (emp_data.get('job', '') or 
                    emp_data.get('currentJobDescription', '') or 
                    'Poste général')
            
            if job_desc and profil.departement and profil.site:
                poste = Poste.objects.filter(
                    titre=job_desc,
                    departement=profil.departement,
                    site=profil.site
                ).first()
                
                if not poste:
                    try:
                        poste = Poste.objects.create(
                            titre=job_desc,
                            departement=profil.departement,
                            site=profil.site,
                            description=f"Poste importé depuis Kelio: {job_desc}",
                            kelio_job_key=emp_data.get('currentJobPositionCode'),
                            niveau_responsabilite=1 if emp_data.get('currentJobPositionCode') == '01' else 1
                        )
                        logger.debug(f"Poste créé: {job_desc}")
                    except Exception as e:
                        logger.warning(f"Erreur création poste {job_desc}: {e}")
                
                if poste:
                    profil.poste = poste
            
            profil.save()
            
        except Exception as e:
            logger.error(f"Erreur association données organisationnelles pour {profil.matricule}: {e}")
            # Ne pas relancer l'exception pour éviter d'interrompre la synchronisation

    def _update_single_user_and_profile_from_professional_data(self, employee_data):
        """Met a jour un seul utilisateur et profil depuis les donnees professionnelles"""
        try:
            employees_data = [employee_data]
            return self._update_users_and_profiles_from_employee_data(employees_data)
        except Exception as e:
            logger.error(f"Erreur mise a jour utilisateur unique: {e}")
            return {'erreur': str(e)}
    
    # ================================================================
    # MÉTHODE GÉNÉRIQUE POUR AMÉLIORER LA SYNCHRONISATION
    # ================================================================

    def _synchroniser_donnees_peripheriques_employe_v41(self, matricule):
        """Version AMÉLIORÉE avec meilleure gestion des erreurs et extraction robuste"""
        logger.info(f">>> Synchronisation donnees peripheriques V4.1 pour {matricule}")
        
        resultats = {
            'matricule': matricule,
            'timestamp_debut': timezone.now(),
            'donnees_synchronisees': {},
            'erreurs': [],
            'nb_appels': 0,
            'services_reussis': 0,
            'services_erreur': 0
        }
        
        # Services périphériques avec gestion d'erreurs améliorée
        services_peripheriques = [
            ('skill_assignments', 'Compétences'),
            ('initial_formations', 'Formations initiales'),
            ('absence_requests', 'Demandes d\'absences'),
            ('training_history', 'Historique formations'),
            ('coefficient_assignments', 'Coefficients')
        ]
        
        for service_type, service_name in services_peripheriques:
            try:
                logger.debug(f">>> Traitement {service_name} pour {matricule}")
                
                # Récupérer les données avec gestion robuste
                donnees = self._get_peripheral_data_with_fallback(service_type, matricule)
                
                if donnees and not donnees.get('erreur'):
                    resultats['donnees_synchronisees'][service_type] = donnees
                    
                    # Traiter les données si extraction réussie
                    if donnees.get('count', 0) > 0:
                        self._process_peripheral_data_v41(service_type, donnees, matricule)
                    
                    resultats['services_reussis'] += 1
                    logger.debug(f"✅ {service_name} synchronisé pour {matricule} ({donnees.get('count', 0)} éléments)")
                else:
                    # Erreur mais on continue
                    error_msg = donnees.get('erreur', 'Structure non reconnue') if donnees else 'Aucune donnée'
                    resultats['erreurs'].append(f"{service_name}: {error_msg}")
                    resultats['services_erreur'] += 1
                    logger.warning(f"⚠️ {service_name} - {error_msg} pour {matricule}")
                
                resultats['nb_appels'] += 1
                
            except Exception as e:
                error_msg = f"Erreur {service_name}: {str(e)}"
                resultats['erreurs'].append(error_msg)
                resultats['services_erreur'] += 1
                logger.error(f"ERROR {error_msg}")
        
        # Déterminer le statut global - plus tolérant
        if resultats['services_reussis'] >= len(services_peripheriques) // 2:
            resultats['statut_global'] = 'reussi' if resultats['services_erreur'] == 0 else 'partiel'
        else:
            resultats['statut_global'] = 'partiel' if resultats['services_reussis'] > 0 else 'echec'
        
        resultats['timestamp_fin'] = timezone.now()
        
        # Message plus informatif
        message = f">>> Donnees peripheriques V4.1 {matricule}: {resultats['services_reussis']} reussis, {resultats['services_erreur']} erreurs"
        if resultats['services_erreur'] > 0:
            message += f" (Structures non reconnues mais gérées)"
        
        logger.info(message)
        return resultats

    # 4. Ajoutez cette nouvelle méthode
    def _get_peripheral_data_with_fallback(self, service_type, matricule):
        """Méthode générique avec fallback pour récupérer les données périphériques"""
        try:
            # Mapping vers les méthodes spécialisées
            method_mapping = {
                'skill_assignments': self._get_skill_assignments_v41,
                'initial_formations': self._get_initial_formations_v41,
                'absence_requests': self._get_absence_requests_v41,
                'training_history': self._get_training_history_v41,
                'coefficient_assignments': self._get_coefficient_assignments_v41
            }
            
            method = method_mapping.get(service_type)
            if method:
                return method(matricule)
            else:
                return {
                    'erreur': f'Service {service_type} non supporté',
                    '_service_type': service_type
                }
                
        except Exception as e:
            logger.error(f"ERROR Erreur générique {service_type} pour {matricule}: {e}")
            return {
                'erreur': str(e),
                '_service_type': service_type
            }
        
    # ================================================================
    # METHODES SPECIALISEES PAR SERVICE PERIPHERIQUE - V4.1
    # ================================================================
    
    def _get_skill_assignments_v41(self, matricule):
        """Recupere les competences via SkillAssignmentService"""
        try:
            client = self._get_soap_client('SkillAssignmentService')
            
            response = client.service.exportSkillAssignments(
                populationFilter=matricule
            )
            
            return self._extract_skill_assignments_from_response(response, matricule)
            
        except Exception as e:
            logger.error(f"ERROR Erreur SkillAssignmentService {matricule}: {e}")
            return {'erreur': str(e), '_service_type': 'skill_assignments'}
    
    def _get_initial_formations_v41(self, matricule):
        """Recupere les formations initiales via InitialFormationAssignmentService"""
        try:
            client = self._get_soap_client('InitialFormationAssignmentService')
            
            response = client.service.exportInitialFormationAssignment(
                exportFilter={
                    'AskedPopulation': {
                        'employeeIdentificationNumber': matricule
                    }
                }
            )
            
            return self._extract_initial_formations_from_response(response, matricule)
            
        except Exception as e:
            logger.error(f"ERROR Erreur InitialFormationAssignmentService {matricule}: {e}")
            return {'erreur': str(e), '_service_type': 'initial_formations'}
    
    def _get_absence_requests_v41(self, matricule):
        """Recupere les demandes d'absences via AbsenceRequestService"""
        try:
            client = self._get_soap_client('AbsenceRequestService')
            
            # Utiliser la date d'aujourd'hui pour les absences futures
            today = timezone.now().date().isoformat()
            
            response = client.service.exportAbsenceRequestsFromEmployeeList(
                employeeList={
                    'askedEmployee': {
                        'employeeIdentificationNumber': matricule,
                        'dateMode': 1,
                        'startDate': today,
                        'startOffset': 0,
                        'endOffset': 0
                    }
                }
            )
            
            return self._extract_absence_requests_from_response(response, matricule)
            
        except Exception as e:
            logger.error(f"ERROR Erreur AbsenceRequestService {matricule}: {e}")
            return {'erreur': str(e), '_service_type': 'absence_requests'}
    
    def _get_training_history_v41(self, matricule):
        """Recupere l'historique des formations via EmployeeTrainingHistoryService"""
        try:
            client = self._get_soap_client('EmployeeTrainingHistoryService')
            
            response = client.service.exportEmployeeTrainingHistory(
                exportFilter={
                    'AskedPopulation': {
                        'employeeIdentificationNumber': matricule
                    }
                }
            )
            
            return self._extract_training_history_from_response(response, matricule)
            
        except Exception as e:
            logger.error(f"ERROR Erreur EmployeeTrainingHistoryService {matricule}: {e}")
            return {'erreur': str(e), '_service_type': 'training_history'}
    
    def _get_coefficient_assignments_v41(self, matricule):
        """Recupere les coefficients via CoefficientAssignmentService"""
        try:
            client = self._get_soap_client('CoefficientAssignmentService')
            
            # Calculer les dates dynamiquement : debut annee precedente a fin annee courante
            current_year = timezone.now().year
            start_date = f"{current_year - 1}-01-01"  # Debut de l'annee precedente
            end_date = f"{current_year}-12-31"        # Fin de l'annee courante
            
            response = client.service.exportCoefficientAssignments(
                populationFilter=f"employeeIdentificationNumber='{matricule}'",
                startDate=start_date,
                endDate=end_date
            )
            
            return self._extract_coefficient_assignments_from_response(response, matricule)
            
        except Exception as e:
            logger.error(f"ERROR Erreur CoefficientAssignmentService {matricule}: {e}")
            return {'erreur': str(e), '_service_type': 'coefficient_assignments'}
    
    # ================================================================
    # METHODES D'EXTRACTION DES DONNEES PERIPHERIQUES
    # ================================================================
    
    # 1. Remplacez la méthode _extract_skill_assignments_from_response
    def _extract_skill_assignments_from_response(self, response, matricule):
        """Version CORRIGÉE avec extraction robuste des compétences"""
        try:
            logger.debug(f"🔍 Extraction compétences pour {matricule}...")
            
            # Utiliser la même stratégie que pour les employés
            from zeep.helpers import serialize_object
            
            competences_data = []
            
            try:
                # === STRATÉGIE 1: SERIALIZE_OBJECT ===
                serialized = serialize_object(response)
                logger.debug(f"📦 Compétences sérialisées: {type(serialized)}")
                
                if isinstance(serialized, dict):
                    logger.debug(f"🔑 Clés dict compétences: {list(serialized.keys())}")
                    competences_data = self._extract_skills_from_dict(serialized)
                    
                elif isinstance(serialized, list):
                    logger.debug(f"📋 Liste compétences: {len(serialized)} éléments")
                    competences_data = self._extract_skills_from_list(serialized)
                    
            except Exception as e:
                logger.debug(f"⚠️ Stratégie 1 échouée: {e}")
            
            # === STRATÉGIE 2: EXPLORATION DIRECTE DES ATTRIBUTS ===
            if not competences_data:
                try:
                    # Chercher des attributs prometeurs
                    skill_attributes = [
                        'exportedSkillAssignments', 'skillAssignments', 'skills',
                        'SkillAssignment', 'skillAssignment', 'competences'
                    ]
                    
                    for attr_name in skill_attributes:
                        if hasattr(response, attr_name):
                            attr_value = getattr(response, attr_name)
                            if attr_value:
                                logger.debug(f"🎯 Attribut trouvé: {attr_name}")
                                competences_data = self._process_skill_attribute(attr_value)
                                if competences_data:
                                    break
                    
                except Exception as e:
                    logger.debug(f"⚠️ Stratégie 2 échouée: {e}")
            
            # === STRATÉGIE 3: EXPLORATION RÉCURSIVE ===
            if not competences_data:
                try:
                    competences_data = self._recursive_skill_search(response)
                except Exception as e:
                    logger.debug(f"⚠️ Stratégie 3 échouée: {e}")
            
            # Retourner structure standardisée
            return {
                'competences': competences_data,
                'count': len(competences_data),
                'matricule': matricule,
                '_service_type': 'skill_assignments',
                '_extraction_status': 'reussi' if competences_data else 'structure_non_reconnue_mais_gere'
            }
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction SkillAssignments: {e}")
            return {
                'competences': [],
                'count': 0,
                'matricule': matricule,
                '_service_type': 'skill_assignments',
                'erreur': str(e)
            }

    # 2. Ajoutez ces nouvelles méthodes auxiliaires à la classe KelioSynchronizationServiceV41
    def _extract_skills_from_dict(self, serialized_dict):
        """Extrait compétences depuis un dictionnaire sérialisé"""
        try:
            competences = []
            
            for key, value in serialized_dict.items():
                key_lower = key.lower()
                
                # Chercher des clés prometteuses pour les compétences
                if any(keyword in key_lower for keyword in ['skill', 'competence', 'export', 'assignment']):
                    logger.debug(f"🎯 Clé compétence prometteuse: {key}")
                    
                    if isinstance(value, list) and value:
                        # Liste de compétences
                        for item in value:
                            comp_data = self._extract_single_skill_from_item(item)
                            if comp_data:
                                competences.append(comp_data)
                    
                    elif isinstance(value, dict) and value:
                        # Compétence unique
                        comp_data = self._extract_single_skill_from_item(value)
                        if comp_data:
                            competences.append(comp_data)
            
            return competences
        except Exception as e:
            logger.debug(f"Erreur extraction compétences dict: {e}")
            return []

    def _extract_skills_from_list(self, serialized_list):
        """Extrait compétences depuis une liste sérialisée"""
        try:
            competences = []
            
            for item in serialized_list:
                comp_data = self._extract_single_skill_from_item(item)
                if comp_data:
                    competences.append(comp_data)
            
            return competences
        except Exception as e:
            logger.debug(f"Erreur extraction compétences liste: {e}")
            return []

    def _extract_single_skill_from_item(self, item):
        """Extrait une compétence depuis un élément"""
        try:
            if not item:
                return None
            
            # Mapping des champs compétences
            skill_mapping = {
                'skill_key': ['skillKey', 'key', 'id', 'skillId'],
                'skill_name': ['skillDescription', 'skillName', 'name', 'description', 'titre'],
                'skill_abbreviation': ['skillAbbreviation', 'abbreviation', 'code', 'sigle'],
                'level': ['level', 'niveau', 'maitrise', 'competenceLevel'],
                'level_description': ['levelDescription', 'niveauDescription', 'levelName'],
                'assignment_key': ['skillAssignmentKey', 'assignmentKey', 'assignmentId'],
                'start_date': ['startDate', 'dateDebut', 'assignmentStartDate'],
                'end_date': ['endDate', 'dateFin', 'assignmentEndDate'],
                'certification': ['certification', 'certifie', 'certified'],
                'validated': ['validated', 'valide', 'approved']
            }
            
            comp_data = {}
            
            # Extraire selon le type d'item
            if isinstance(item, dict):
                for target_field, possible_keys in skill_mapping.items():
                    for key in possible_keys:
                        if key in item and item[key] is not None:
                            comp_data[target_field] = item[key]
                            break
            
            elif hasattr(item, '__dict__') or hasattr(item, '__getattribute__'):
                # Objet avec attributs
                for target_field, possible_keys in skill_mapping.items():
                    for key in possible_keys:
                        try:
                            value = getattr(item, key, None)
                            if value is not None:
                                comp_data[target_field] = value
                                break
                        except:
                            continue
            
            # Validation minimale
            if comp_data.get('skill_name') or comp_data.get('skill_key'):
                comp_data.update({
                    'source': 'kelio_skill_assignments',
                    'timestamp_sync': timezone.now().isoformat()
                })
                return comp_data
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur extraction compétence item: {e}")
            return None

    def _process_skill_attribute(self, attr_value):
        """Traite un attribut qui pourrait contenir des compétences"""
        try:
            competences = []
            
            if isinstance(attr_value, list):
                for item in attr_value:
                    comp_data = self._extract_single_skill_from_item(item)
                    if comp_data:
                        competences.append(comp_data)
            
            elif attr_value:  # Objet unique
                comp_data = self._extract_single_skill_from_item(attr_value)
                if comp_data:
                    competences.append(comp_data)
            
            return competences
        except Exception as e:
            logger.debug(f"Erreur traitement attribut compétence: {e}")
            return []

    def _recursive_skill_search(self, obj, depth=0, max_depth=2):
        """Recherche récursive de compétences dans la structure"""
        try:
            if depth > max_depth:
                return []
            
            competences = []
            
            # Si c'est une liste
            if isinstance(obj, list):
                for item in obj:
                    sub_skills = self._recursive_skill_search(item, depth+1, max_depth)
                    competences.extend(sub_skills)
            
            # Si ça ressemble à une compétence
            elif self._is_skill_like_object(obj):
                comp_data = self._extract_single_skill_from_item(obj)
                if comp_data:
                    competences.append(comp_data)
            
            # Si c'est un objet avec attributs
            elif hasattr(obj, '__dict__') or (hasattr(obj, '__class__') and not isinstance(obj, (str, int, float, bool))):
                # Explorer les attributs
                attrs_to_check = []
                
                if hasattr(obj, '__dict__'):
                    attrs_to_check.extend([(k, v) for k, v in obj.__dict__.items()])
                
                for attr_name in [a for a in dir(obj) if not a.startswith('_')][:5]:  # Limiter
                    try:
                        attr_value = getattr(obj, attr_name)
                        if not callable(attr_value):
                            attrs_to_check.append((attr_name, attr_value))
                    except:
                        pass
                
                for attr_name, attr_value in attrs_to_check:
                    if attr_value is not None:
                        sub_skills = self._recursive_skill_search(attr_value, depth+1, max_depth)
                        competences.extend(sub_skills)
            
            return competences
        except Exception as e:
            logger.debug(f"Erreur recherche récursive compétences: {e}")
            return []

    def _is_skill_like_object(self, obj):
        """Détermine si un objet ressemble à une compétence"""
        try:
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return False
            
            # Indicateurs de compétence
            skill_indicators = [
                'skill', 'competence', 'level', 'niveau', 'assignment',
                'description', 'name', 'nom', 'abbreviation', 'code'
            ]
            
            # Récupérer attributs/clés
            obj_attrs = []
            
            if isinstance(obj, dict):
                obj_attrs = list(obj.keys())
            elif hasattr(obj, '__dict__'):
                obj_attrs.extend(obj.__dict__.keys())
            
            if hasattr(obj, '__class__'):
                obj_attrs.extend([attr for attr in dir(obj) if not attr.startswith('_')])
            
            # Compter correspondances
            matches = 0
            for attr in obj_attrs:
                attr_lower = str(attr).lower()
                for indicator in skill_indicators:
                    if indicator in attr_lower:
                        matches += 1
                        break
            
            return matches >= 2
            
        except Exception as e:
            logger.debug(f"Erreur évaluation compétence: {e}")
            return False

            
    # ================================================================
    # CORRECTIONS SIMILAIRES POUR LES AUTRES SERVICES
    # ================================================================

    def _extract_initial_formations_from_response(self, response, matricule):
        """Version CORRIGÉE avec extraction robuste des formations initiales"""
        try:
            logger.debug(f"🎓 Extraction formations initiales pour {matricule}...")
            
            formations_data = []
            
            # Utiliser la même stratégie multi-niveaux
            from zeep.helpers import serialize_object
            
            try:
                serialized = serialize_object(response)
                
                if isinstance(serialized, dict):
                    formations_data = self._extract_formations_from_dict(serialized)
                elif isinstance(serialized, list):
                    formations_data = self._extract_formations_from_list(serialized)
                    
            except Exception as e:
                logger.debug(f"⚠️ Sérialisation formations échouée: {e}")
            
            # Exploration directe si pas de résultats
            if not formations_data:
                formation_attributes = [
                    'exportedInitialFormationAssignments', 'initialFormationAssignments', 
                    'formations', 'FormationAssignment', 'initialFormations'
                ]
                
                for attr_name in formation_attributes:
                    if hasattr(response, attr_name):
                        attr_value = getattr(response, attr_name)
                        if attr_value:
                            formations_data = self._process_formation_attribute(attr_value)
                            if formations_data:
                                break
            
            return {
                'formations_initiales': formations_data,
                'count': len(formations_data),
                'matricule': matricule,
                '_service_type': 'initial_formations',
                '_extraction_status': 'reussi' if formations_data else 'structure_non_reconnue_mais_gere'
            }
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction InitialFormations: {e}")
            return {
                'formations_initiales': [],
                'count': 0,
                'matricule': matricule,
                '_service_type': 'initial_formations',
                'erreur': str(e)
            }

    def _extract_formations_from_dict(self, serialized_dict):
        """Extrait formations depuis un dictionnaire"""
        try:
            formations = []
            
            for key, value in serialized_dict.items():
                key_lower = key.lower()
                
                if any(keyword in key_lower for keyword in ['formation', 'training', 'education', 'export']):
                    if isinstance(value, list) and value:
                        for item in value:
                            form_data = self._extract_single_formation_from_item(item)
                            if form_data:
                                formations.append(form_data)
                    
                    elif isinstance(value, dict) and value:
                        form_data = self._extract_single_formation_from_item(value)
                        if form_data:
                            formations.append(form_data)
            
            return formations
        except Exception as e:
            logger.debug(f"Erreur extraction formations dict: {e}")
            return []

    def _extract_single_formation_from_item(self, item):
        """Extrait une formation depuis un élément"""
        try:
            if not item:
                return None
            
            formation_mapping = {
                'formation_key': ['initialFormationKey', 'formationKey', 'key', 'id'],
                'titre': ['degreeDescription', 'title', 'titre', 'name', 'formationTitle'],
                'description': ['comment', 'description', 'details'],
                'organisme': ['schoolName', 'institution', 'organisme', 'school'],
                'annee': ['graduationYear', 'year', 'annee'],
                'niveau': ['degreeLevel', 'level', 'niveau'],
                'diplome': ['degreeDescription', 'degree', 'diplome'],
                'document': ['attachedDocument', 'document', 'certificat']
            }
            
            form_data = {}
            
            if isinstance(item, dict):
                for target_field, possible_keys in formation_mapping.items():
                    for key in possible_keys:
                        if key in item and item[key] is not None:
                            form_data[target_field] = item[key]
                            break
            
            elif hasattr(item, '__dict__') or hasattr(item, '__getattribute__'):
                for target_field, possible_keys in formation_mapping.items():
                    for key in possible_keys:
                        try:
                            value = getattr(item, key, None)
                            if value is not None:
                                form_data[target_field] = value
                                break
                        except:
                            continue
            
            if form_data.get('titre') or form_data.get('formation_key'):
                form_data.update({
                    'source': 'kelio_initial_formations',
                    'timestamp_sync': timezone.now().isoformat()
                })
                return form_data
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur extraction formation item: {e}")
            return None

    def _process_formation_attribute(self, attr_value):
        """Traite un attribut qui pourrait contenir des formations"""
        try:
            formations = []
            
            if isinstance(attr_value, list):
                for item in attr_value:
                    form_data = self._extract_single_formation_from_item(item)
                    if form_data:
                        formations.append(form_data)
            
            elif attr_value:
                form_data = self._extract_single_formation_from_item(attr_value)
                if form_data:
                    formations.append(form_data)
            
            return formations
        except Exception as e:
            logger.debug(f"Erreur traitement attribut formation: {e}")
            return []

    # ================================================================
    # CORRECTION POUR LES ABSENCES
    # ================================================================

    def _extract_absence_requests_from_response(self, response, matricule):
        """Version CORRIGÉE pour les demandes d'absences"""
        try:
            logger.debug(f"🏖️ Extraction absences pour {matricule}...")
            
            absences_data = []
            
            from zeep.helpers import serialize_object
            
            try:
                serialized = serialize_object(response)
                
                if isinstance(serialized, dict):
                    absences_data = self._extract_absences_from_dict(serialized)
                elif isinstance(serialized, list):
                    absences_data = self._extract_absences_from_list(serialized)
                    
            except Exception as e:
                logger.debug(f"⚠️ Sérialisation absences échouée: {e}")
            
            if not absences_data:
                absence_attributes = [
                    'exportedAbsenceRequests', 'absenceRequests', 'absences',
                    'AbsenceRequest', 'absenceRequest'
                ]
                
                for attr_name in absence_attributes:
                    if hasattr(response, attr_name):
                        attr_value = getattr(response, attr_name)
                        if attr_value:
                            absences_data = self._process_absence_attribute(attr_value)
                            if absences_data:
                                break
            
            return {
                'demandes_absences': absences_data,
                'count': len(absences_data),
                'matricule': matricule,
                '_service_type': 'absence_requests',
                '_extraction_status': 'reussi' if absences_data else 'structure_non_reconnue_mais_gere'
            }
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction AbsenceRequests: {e}")
            return {
                'demandes_absences': [],
                'count': 0,
                'matricule': matricule,
                '_service_type': 'absence_requests',
                'erreur': str(e)
            }

    def _extract_absences_from_dict(self, serialized_dict):
        """Extrait absences depuis un dictionnaire"""
        try:
            absences = []
            
            for key, value in serialized_dict.items():
                key_lower = key.lower()
                
                if any(keyword in key_lower for keyword in ['absence', 'request', 'conge', 'export']):
                    if isinstance(value, list) and value:
                        for item in value:
                            abs_data = self._extract_single_absence_from_item(item)
                            if abs_data:
                                absences.append(abs_data)
                    
                    elif isinstance(value, dict) and value:
                        abs_data = self._extract_single_absence_from_item(value)
                        if abs_data:
                            absences.append(abs_data)
            
            return absences
        except Exception as e:
            logger.debug(f"Erreur extraction absences dict: {e}")
            return []

    def _extract_single_absence_from_item(self, item):
        """Extrait une absence depuis un élément"""
        try:
            if not item:
                return None
            
            absence_mapping = {
                'absence_key': ['absenceRequestKey', 'requestKey', 'key', 'id'],
                'type_key': ['absenceTypeKey', 'typeKey', 'type_id'],
                'type_description': ['absenceTypeDescription', 'typeDescription', 'type', 'motif'],
                'type_abbreviation': ['absenceTypeAbbreviation', 'typeAbbreviation', 'code'],
                'request_type': ['requestType', 'typeRequete'],
                'request_state': ['requestState', 'status', 'statut', 'etat'],
                'start_date': ['startDate', 'dateDebut', 'debut'],
                'end_date': ['endDate', 'dateFin', 'fin'],
                'duration_hours': ['durationInHours', 'dureeHeures', 'heures'],
                'duration_days': ['durationInDays', 'dureeJours', 'jours'],
                'comment': ['comment', 'commentaire', 'description'],
                'creation_date': ['creationDate', 'dateCreation', 'created']
            }
            
            abs_data = {}
            
            if isinstance(item, dict):
                for target_field, possible_keys in absence_mapping.items():
                    for key in possible_keys:
                        if key in item and item[key] is not None:
                            abs_data[target_field] = item[key]
                            break
            
            elif hasattr(item, '__dict__') or hasattr(item, '__getattribute__'):
                for target_field, possible_keys in absence_mapping.items():
                    for key in possible_keys:
                        try:
                            value = getattr(item, key, None)
                            if value is not None:
                                abs_data[target_field] = value
                                break
                        except:
                            continue
            
            # Conversion des dates
            for date_field in ['start_date', 'end_date', 'creation_date']:
                if abs_data.get(date_field):
                    abs_data[date_field] = safe_date_conversion(abs_data[date_field])
            
            if abs_data.get('type_description') or abs_data.get('absence_key'):
                abs_data.update({
                    'source': 'kelio_absence_requests',
                    'timestamp_sync': timezone.now().isoformat()
                })
                return abs_data
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur extraction absence item: {e}")
            return None
        
    def _extract_training_history_from_response(self, response, matricule):
        """Extrait l'historique des formations de la reponse"""
        try:
            trainings_data = []
            
            if hasattr(response, 'exportedEmployeeTrainingHistory'):
                trainings_raw = response.exportedEmployeeTrainingHistory
            else:
                logger.warning("Structure de reponse TrainingHistory non reconnue")
                return trainings_data
            
            if not isinstance(trainings_raw, list):
                trainings_raw = [trainings_raw] if trainings_raw else []
            
            for training in trainings_raw:
                training_data = {
                    'trainingHistoryKey': safe_get_attribute(training, 'trainingHistoryKey'),
                    'trainingTitle': safe_get_attribute(training, 'trainingTitle', ''),
                    'trainingDescription': safe_get_attribute(training, 'trainingDescription', ''),
                    'trainingStartDate': safe_date_conversion(safe_get_attribute(training, 'trainingStartDate')),
                    'trainingEndDate': safe_date_conversion(safe_get_attribute(training, 'trainingEndDate')),
                    'trainingStatus': safe_get_attribute(training, 'trainingStatus', ''),
                    'hoursDuration': safe_get_attribute(training, 'hoursDuration'),
                    'daysDuration': safe_get_attribute(training, 'daysDuration'),
                    'organizationDescription': safe_get_attribute(training, 'organizationDescription', ''),
                    'formationType': safe_get_attribute(training, 'formationType', ''),
                    'creationDate': safe_date_conversion(safe_get_attribute(training, 'creationDate')),
                    'source': 'kelio_training_history',
                    'timestamp_sync': timezone.now().isoformat()
                }
                trainings_data.append(training_data)
            
            logger.debug(f"OK {len(trainings_data)} formation(s) historique extraite(s) pour {matricule}")
            return {
                'formations_historique': trainings_data,
                'count': len(trainings_data),
                'matricule': matricule,
                '_service_type': 'training_history'
            }
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction TrainingHistory: {e}")
            return {'erreur': str(e), '_service_type': 'training_history'}
    
    def _extract_coefficient_assignments_from_response(self, response, matricule):
        """Extrait les coefficients et classifications de la reponse"""
        try:
            coefficients_data = []
            
            if hasattr(response, 'exportedCoefficientAssignments'):
                coefficients_raw = response.exportedCoefficientAssignments
                if hasattr(coefficients_raw, 'CoefficientAssignment'):
                    coefficients_raw = coefficients_raw.CoefficientAssignment
            else:
                logger.warning("Structure de reponse CoefficientAssignments non reconnue")
                return coefficients_data
            
            if not isinstance(coefficients_raw, list):
                coefficients_raw = [coefficients_raw] if coefficients_raw else []
            
            for coefficient in coefficients_raw:
                coefficient_data = {
                    'coefficientAssignmentKey': safe_get_attribute(coefficient, 'coefficientAssignmentKey'),
                    'CoefficientCode': safe_get_attribute(coefficient, 'CoefficientCode', ''),
                    'CoefficientDescription': safe_get_attribute(coefficient, 'CoefficientDescription', ''),
                    'coefficientAssignmentStartDate': safe_date_conversion(safe_get_attribute(coefficient, 'coefficientAssignmentStartDate')),
                    'coefficientAssignmentEndDate': safe_date_conversion(safe_get_attribute(coefficient, 'coefficientAssignmentEndDate')),
                    'jobPositionCode': safe_get_attribute(coefficient, 'jobPositionCode', ''),
                    'jobPositionDescription': safe_get_attribute(coefficient, 'jobPositionDescription', ''),
                    'professionalStatusCode': safe_get_attribute(coefficient, 'professionalStatusCode', ''),
                    'professionalStatusDescription': safe_get_attribute(coefficient, 'professionalStatusDescription', ''),
                    'qualificationCode': safe_get_attribute(coefficient, 'qualificationCode', ''),
                    'qualificationDescription': safe_get_attribute(coefficient, 'qualificationDescription', ''),
                    'classificationLevelDescription': safe_get_attribute(coefficient, 'classificationLevelDescription', ''),
                    'source': 'kelio_coefficient_assignments',
                    'timestamp_sync': timezone.now().isoformat()
                }
                coefficients_data.append(coefficient_data)
            
            logger.debug(f"OK {len(coefficients_data)} coefficient(s) extrait(s) pour {matricule}")
            return {
                'coefficients': coefficients_data,
                'count': len(coefficients_data),
                'matricule': matricule,
                '_service_type': 'coefficient_assignments'
            }
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction CoefficientAssignments: {e}")
            return {'erreur': str(e), '_service_type': 'coefficient_assignments'}
    
    # ================================================================
    # TRAITEMENT DES DONNEES PERIPHERIQUES VERS LES MODELES DJANGO
    # ================================================================
    
    def _process_peripheral_data_v41(self, service_type, donnees, matricule):
        """Traite les donnees peripheriques et les sauvegarde dans les modeles Django appropries"""
        try:
            from ..models import (ProfilUtilisateur, Competence, CompetenceUtilisateur, 
                                FormationUtilisateur, AbsenceUtilisateur, MotifAbsence, 
                                ProfilUtilisateurExtended, CacheApiKelio)
            
            # Recuperer le profil utilisateur
            try:
                profil = ProfilUtilisateur.objects.get(matricule=matricule)
            except ProfilUtilisateur.DoesNotExist:
                logger.warning(f"ProfilUtilisateur {matricule} non trouve pour traitement donnees peripheriques")
                return
            
            if service_type == 'skill_assignments':
                self._process_skill_assignments_to_django(donnees, profil)
            elif service_type == 'initial_formations':
                self._process_initial_formations_to_django(donnees, profil)
            elif service_type == 'training_history':
                self._process_training_history_to_django(donnees, profil)
            elif service_type == 'absence_requests':
                self._process_absence_requests_to_django(donnees, profil)
            elif service_type == 'coefficient_assignments':
                self._process_coefficient_assignments_to_django(donnees, profil)
            else:
                # Pour les services Kelio-only, sauvegarder dans le cache
                self._save_to_kelio_cache(service_type, matricule, donnees)
            
            logger.debug(f"OK Donnees {service_type} traitees pour {matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement donnees {service_type} pour {matricule}: {e}")
    
    def _process_skill_assignments_to_django(self, donnees, profil):
        """Traite les competences et les sauvegarde dans les modeles Django"""
        from ..models import Competence, CompetenceUtilisateur
        
        try:
            competences_data = donnees.get('competences', [])
            
            for comp_data in competences_data:
                # Creer ou recuperer la competence
                competence, created = Competence.objects.get_or_create(
                    nom=comp_data.get('skillDescription', 'Competence inconnue'),
                    defaults={
                        'description': comp_data.get('skillDescription', ''),
                        'kelio_skill_key': comp_data.get('skillKey'),
                        'kelio_skill_abbreviation': comp_data.get('skillAbbreviation', ''),
                        'type_competence': 'TECHNIQUE'
                    }
                )
                
                # Convertir le niveau Kelio en niveau numerique
                niveau_kelio = comp_data.get('level', '').lower()
                niveau_maitrise = 1  # Debutant par defaut
                if 'expert' in niveau_kelio or 'avance' in niveau_kelio:
                    niveau_maitrise = 4
                elif 'confirme' in niveau_kelio or 'intermediaire' in niveau_kelio:
                    niveau_maitrise = 3
                elif 'moyen' in niveau_kelio:
                    niveau_maitrise = 2
                
                # Creer ou mettre a jour la competence utilisateur
                comp_user, created = CompetenceUtilisateur.objects.get_or_create(
                    utilisateur=profil,
                    competence=competence,
                    defaults={
                        'niveau_maitrise': niveau_maitrise,
                        'source_donnee': 'KELIO',
                        'kelio_skill_assignment_key': comp_data.get('skillAssignmentKey'),
                        'kelio_level': comp_data.get('level', ''),
                        'date_acquisition': comp_data.get('startDate'),
                        'date_evaluation': comp_data.get('endDate')
                    }
                )
                
                if not created:
                    # Mettre a jour la competence existante
                    comp_user.niveau_maitrise = niveau_maitrise
                    comp_user.source_donnee = 'KELIO'
                    comp_user.kelio_skill_assignment_key = comp_data.get('skillAssignmentKey')
                    comp_user.kelio_level = comp_data.get('level', '')
                    comp_user.date_acquisition = comp_data.get('startDate')
                    comp_user.date_evaluation = comp_data.get('endDate')
                    comp_user.save()
            
            logger.debug(f"OK {len(competences_data)} competence(s) traitee(s) pour {profil.matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement competences pour {profil.matricule}: {e}")
    
    def _process_initial_formations_to_django(self, donnees, profil):
        """Traite les formations initiales et les sauvegarde dans FormationUtilisateur"""
        from ..models import FormationUtilisateur
        
        try:
            formations_data = donnees.get('formations_initiales', [])
            
            for formation_data in formations_data:
                # Creer ou mettre a jour la formation
                formation, created = FormationUtilisateur.objects.get_or_create(
                    utilisateur=profil,
                    kelio_formation_key=formation_data.get('initialFormationKey'),
                    defaults={
                        'titre': formation_data.get('degreeDescription', 'Formation initiale'),
                        'description': formation_data.get('comment', ''),
                        'type_formation': 'Formation initiale',
                        'organisme': formation_data.get('schoolName', ''),
                        'duree_jours': 0,  # Non disponible dans les formations initiales
                        'certifiante': True,
                        'diplome_obtenu': True,
                        'source_donnee': 'KELIO'
                    }
                )
                
                if not created:
                    # Mettre a jour la formation existante
                    formation.titre = formation_data.get('degreeDescription', 'Formation initiale')
                    formation.description = formation_data.get('comment', '')
                    formation.organisme = formation_data.get('schoolName', '')
                    formation.source_donnee = 'KELIO'
                    formation.save()
            
            logger.debug(f"OK {len(formations_data)} formation(s) initiale(s) traitee(s) pour {profil.matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement formations initiales pour {profil.matricule}: {e}")
    
    def _process_training_history_to_django(self, donnees, profil):
        """Traite l'historique des formations et les sauvegarde dans FormationUtilisateur"""
        from ..models import FormationUtilisateur
        
        try:
            trainings_data = donnees.get('formations_historique', [])
            
            for training_data in trainings_data:
                # Creer ou mettre a jour la formation
                formation, created = FormationUtilisateur.objects.get_or_create(
                    utilisateur=profil,
                    kelio_formation_key=training_data.get('trainingHistoryKey'),
                    defaults={
                        'titre': training_data.get('trainingTitle', 'Formation'),
                        'description': training_data.get('trainingDescription', ''),
                        'type_formation': training_data.get('formationType', 'Formation continue'),
                        'organisme': training_data.get('organizationDescription', ''),
                        'date_debut': training_data.get('trainingStartDate'),
                        'date_fin': training_data.get('trainingEndDate'),
                        'duree_jours': training_data.get('daysDuration', 0),
                        'certifiante': training_data.get('trainingStatus', '').lower() == 'certifiee',
                        'diplome_obtenu': training_data.get('trainingStatus', '').lower() in ['reussie', 'certifiee'],
                        'source_donnee': 'KELIO'
                    }
                )
                
                if not created:
                    # Mettre a jour la formation existante
                    formation.titre = training_data.get('trainingTitle', 'Formation')
                    formation.description = training_data.get('trainingDescription', '')
                    formation.type_formation = training_data.get('formationType', 'Formation continue')
                    formation.organisme = training_data.get('organizationDescription', '')
                    formation.date_debut = training_data.get('trainingStartDate')
                    formation.date_fin = training_data.get('trainingEndDate')
                    formation.duree_jours = training_data.get('daysDuration', 0)
                    formation.certifiante = training_data.get('trainingStatus', '').lower() == 'certifiee'
                    formation.diplome_obtenu = training_data.get('trainingStatus', '').lower() in ['reussie', 'certifiee']
                    formation.source_donnee = 'KELIO'
                    formation.save()
            
            logger.debug(f"OK {len(trainings_data)} formation(s) historique traitee(s) pour {profil.matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement formations historique pour {profil.matricule}: {e}")
    
    def _process_absence_requests_to_django(self, donnees, profil):
        """Traite les demandes d'absences et les sauvegarde dans AbsenceUtilisateur"""
        from ..models import AbsenceUtilisateur, MotifAbsence
        
        try:
            absences_data = donnees.get('demandes_absences', [])
            
            for absence_data in absences_data:
                # Creer ou recuperer le motif d'absence
                motif_nom = absence_data.get('absenceTypeDescription', 'Absence')
                motif_code = absence_data.get('absenceTypeAbbreviation', 'ABS')
                
                motif, created = MotifAbsence.objects.get_or_create(
                    nom=motif_nom,
                    defaults={
                        'description': f"Motif importe depuis Kelio: {motif_nom}",
                        'code': motif_code[:10] if motif_code else 'ABS',
                        'kelio_absence_type_key': absence_data.get('absenceTypeKey'),
                        'kelio_abbreviation': motif_code,
                        'categorie': 'PERSONNEL'
                    }
                )
                
                # Creer ou mettre a jour l'absence
                absence, created = AbsenceUtilisateur.objects.get_or_create(
                    utilisateur=profil,
                    kelio_absence_file_key=absence_data.get('absenceRequestKey'),
                    defaults={
                        'type_absence': motif_nom,
                        'date_debut': absence_data.get('startDate') or date.today(),
                        'date_fin': absence_data.get('endDate') or date.today(),
                        'duree_jours': absence_data.get('durationInDays', 0),
                        'commentaire': absence_data.get('comment', ''),
                        'source_donnee': 'KELIO'
                    }
                )
                
                if not created:
                    # Mettre a jour l'absence existante
                    absence.type_absence = motif_nom
                    absence.date_debut = absence_data.get('startDate') or absence.date_debut
                    absence.date_fin = absence_data.get('endDate') or absence.date_fin
                    absence.duree_jours = absence_data.get('durationInDays', 0)
                    absence.commentaire = absence_data.get('comment', '')
                    absence.source_donnee = 'KELIO'
                    absence.save()
            
            logger.debug(f"OK {len(absences_data)} absence(s) traitee(s) pour {profil.matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement absences pour {profil.matricule}: {e}")
    
    def _process_coefficient_assignments_to_django(self, donnees, profil):
        """Traite les coefficients et met a jour les donnees etendues"""
        from ..models import ProfilUtilisateurExtended
        
        try:
            coefficients_data = donnees.get('coefficients', [])
            
            if coefficients_data:
                # Prendre le coefficient le plus recent
                coefficient_data = coefficients_data[0]
                
                # Mettre a jour les donnees etendues
                extended_data, created = ProfilUtilisateurExtended.objects.get_or_create(
                    profil=profil,
                    defaults={}
                )
                
                extended_data.coefficient = coefficient_data.get('CoefficientDescription', '')
                extended_data.niveau_classification = coefficient_data.get('classificationLevelDescription', '')
                extended_data.statut_professionnel = coefficient_data.get('professionalStatusDescription', '')
                extended_data.save()
            
            logger.debug(f"OK {len(coefficients_data)} coefficient(s) traite(s) pour {profil.matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement coefficients pour {profil.matricule}: {e}")
    
    def _save_to_kelio_cache(self, service_type, matricule, donnees, cache_duration=3600):
        """Sauvegarde les donnees Kelio-only dans le cache"""
        from ..models import CacheApiKelio
        
        try:
            # Generer une cle de cache unique
            parametres = {'matricule': matricule, 'service': service_type}
            cle_cache = generer_cle_cache_kelio(service_type, parametres)
            
            # Calculer la date d'expiration
            date_expiration = timezone.now() + timezone.timedelta(seconds=cache_duration)
            
            # Calculer la taille des donnees
            taille_donnees = len(json.dumps(donnees, default=str))
            
            # Sauvegarder ou mettre a jour le cache
            cache_entry, created = CacheApiKelio.objects.get_or_create(
                configuration=self.config,
                cle_cache=cle_cache,
                defaults={
                    'service_name': service_type,
                    'parametres_requete': parametres,
                    'donnees': donnees,
                    'date_expiration': date_expiration,
                    'taille_donnees': taille_donnees
                }
            )
            
            if not created:
                # Mettre a jour le cache existant
                cache_entry.donnees = donnees
                cache_entry.date_expiration = date_expiration
                cache_entry.taille_donnees = taille_donnees
                cache_entry.save()
            
            logger.debug(f"OK Donnees {service_type} sauvegardees dans le cache pour {matricule}")
            
        except Exception as e:
            logger.error(f"ERROR Erreur sauvegarde cache {service_type} pour {matricule}: {e}")

# ================================================================
# FONCTIONS FACTORY ET UTILITAIRES - VERSION 4.1 COMPLETE
# ================================================================

def get_kelio_sync_service_v41(configuration=None):
    """Factory function pour le service Kelio V4.1 avec fallback robuste"""
    try:
        service = KelioSynchronizationServiceV41(configuration)
        logger.info(f">>> Service Kelio V4.1 cree pour {service.config.nom}")
        return service
    except Exception as e:
        logger.error(f"ERROR Erreur creation service synchronisation V4.1: {e}")
        if "configuration" in str(e).lower() or "invalide" in str(e).lower():
            raise ConfigurationKeliomanquanteError(f"Configuration Kelio manquante: {e}")
        raise

def synchroniser_tous_employes_kelio_v41(mode='complet'):
    """Fonction principale pour synchroniser tous les employes depuis Kelio V4.1 avec fallback"""
    try:
        service = get_kelio_sync_service_v41()
        return service.synchroniser_tous_les_employes(mode)
    except Exception as e:
        logger.error(f"ERROR Erreur synchronisation complete V4.1: {e}")
        return {
            'statut_global': 'erreur_critique',
            'erreur': str(e),
            'timestamp': timezone.now().isoformat()
        }

def synchroniser_employe_specifique_kelio_v41(matricule, mode='complet'):
    """Fonction principale pour synchroniser un employe specifique V4.1"""
    try:
        service = get_kelio_sync_service_v41()
        return service.synchroniser_employe_specifique(matricule, mode)
    except Exception as e:
        logger.error(f"ERROR Erreur synchronisation V4.1 {matricule}: {e}")
        return {
            'matricule': matricule,
            'statut_global': 'erreur',
            'erreur': str(e),
            'timestamp': timezone.now().isoformat()
        }

# ================================================================
# AFFICHAGE DES STATISTIQUES AU CHARGEMENT - VERSION COMPLETE
# ================================================================

def afficher_statistiques_service_v41():
    """Affiche les statistiques du service Kelio V4.1 au demarrage"""
    try:
        logger.info(">>> =================================================")
        logger.info(">>> SERVICE KELIO SYNCHRONIZATION V4.1 DEMARRE")
        logger.info(">>> =================================================")
        logger.info("OK Nouvelles fonctionnalites V4.1:")
        logger.info("   >>> • EmployeeProfessionalDataService comme service principal")
        logger.info("   >>> • Synchronisation complete User + ProfilUtilisateur + donnees etendues")
        logger.info("   >>> • Iteration automatique sur tous les employes")
        logger.info("   >>> • Support de tous les nouveaux services documentes")
        logger.info("   >>> • Mapping precis vers les modeles Django existants")
        logger.info("   >>> • Cache intelligent optimise pour les nouvelles API")
        logger.info("   >>> • Gestion d'erreurs robuste avec fallback")
        logger.info("   >>> • Integration complete avec les modeles Django")
        logger.info("")
        logger.info(">>> Services API V4.1 supportes:")
        for service_type, config in KELIO_SERVICES_CONFIG.items():
            source_info = f" ({config['data_source']})"
            readonly_info = " [LECTURE SEULE]" if config.get('read_only_in_app', False) else ""
            models_info = f" -> {', '.join(config.get('maps_to_models', ['Cache']))}"
            logger.info(f"   • {service_type}: {config['description']}{source_info}{readonly_info}{models_info}")
        
        logger.info("")
        logger.info(f">>> Authentification par defaut:")
        logger.info(f"   • Username: {KELIO_DEFAULT_AUTH['username']}")
        logger.info(f"   • Password: {KELIO_DEFAULT_AUTH['password']}")
        logger.info(">>> =================================================")
        
        if SOAP_AVAILABLE:
            logger.info("OK Dependances SOAP disponibles (zeep, requests)")
        else:
            logger.warning("WARNING Dependances SOAP manquantes - installez: pip install zeep requests")
        
        logger.info(">>> =================================================")
        
    except Exception as e:
        logger.error(f"ERROR Erreur affichage statistiques V4.1: {e}")

# Afficher les statistiques au chargement du module
afficher_statistiques_service_v41()

# ================================================================
# FIN DU SERVICE KELIO V4.1 REFACTORISE COMPLET
# ================================================================