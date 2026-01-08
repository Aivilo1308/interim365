# -*- coding: utf-8 -*-
"""
Service de synchronisation Kelio refactorise - Version 4.1 CORRIGEE
Integration avec les nouvelles API SOAP Kelio documentees
Support complet des nouveaux services avec mapping vers les modeles Django

Nouvelles fonctionnalites V4.1 :
- EmployeeProfessionalDataService comme service principal
- Synchronisation complete User + ProfilUtilisateur + donnees etendues
- Iteration automatique sur tous les employes pour donnees peripheriques
- Support de tous les nouveaux services documentes
- Mapping precis vers les modeles Django existants
- Gestion d'erreurs robuste avec fallback
- Cache intelligent optimise

Version : 4.1 - Avec nouvelles API Kelio documentees
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
# CONFIGURATION DES NOUVEAUX SERVICES KELIO - CORRIGEE
# ================================================================

# Configuration des nouveaux services Kelio selon la documentation
KELIO_SERVICES_CONFIG = {
    'employee_data': {
        'service_name': 'EmployeeService',
        'wsdl_path': 'EmployeeService?wsdl',
        'method_all': 'exportEmployees',
        'method_single': 'exportEmployee',
        'priority': 1,
        'timeout': 60,
        'required_for_creation': True,
        'cache_duration': 3600,
        'data_source': 'KELIO',
        'description': 'Donnees des employes (service de base)',
        'maps_to_models': ['ProfilUtilisateur', 'ProfilUtilisateurExtended', 'ProfilUtilisateurKelio']
    },
    'employee_list': {
        'service_name': 'EmployeeListService',
        'wsdl_path': 'EmployeeListService?wsdl',
        'method': 'exportEmployeesList',
        'priority': 1,
        'timeout': 45,
        'required_for_creation': True,
        'cache_duration': 3600,
        'data_source': 'KELIO',
        'description': 'Liste des employes',
        'maps_to_models': ['ProfilUtilisateur']
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
    }
}

# Authentification par defaut
KELIO_DEFAULT_AUTH = {
    'username': 'webservices',
    'password': '12345'
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
        # Ajouter des details specifiques a la connexion
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
        # Extraire le matricule du message si possible
        if details:
            self.matricule = details.get('matricule', 'Matricule non specifie')
            self.service_used = details.get('service_used', 'Service non specifie')
        else:
            # Essayer d'extraire le matricule du message
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
# EXEMPLES D'UTILISATION
# ================================================================

"""
Exemples d'utilisation des exceptions:

1. KelioConnectionError:
   raise create_kelio_connection_error(
       "Impossible de se connecter au service SOAP",
       url="http://kelio.company.com/services/EmployeeService?wsdl",
       service_name="EmployeeProfessionalDataService",
       timeout=30,
       original_exception=e
   )

2. KelioEmployeeNotFoundError:
   raise create_kelio_employee_not_found_error(
       matricule="EMP001",
       service_used="EmployeeProfessionalDataService",
       search_criteria={"employeeIdentificationNumber": "EMP001"}
   )

3. Avec le decorateur:
   @handle_kelio_exception
   def synchroniser_employe(matricule):
       # Code de synchronisation
       pass

4. Logging standardise:
   try:
       # Code Kelio
       pass
   except KelioBaseError as e:
       log_kelio_error(e, context={"operation": "sync_employee", "matricule": matricule})
       raise
"""
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
# SERVICE PRINCIPAL REFACTORISE - VERSION 4.1
# ================================================================

# Méthodes simplifiées pour les services disponibles
class KelioSynchronizationServiceV41:
    def __init__(self, configuration=None):
        """Initialise le service avec les API Kelio réellement disponibles"""
        if not SOAP_AVAILABLE:
            raise KelioConnectionError(
                "Dependances SOAP manquantes (zeep, requests)",
                details={'error': 'Dependances SOAP manquantes (zeep, requests)'}
            )
        
        from ..models import ConfigurationApiKelio
        
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
        
        self.session = self._create_session()
        self.clients = {}
        
        # Configuration des services avec les API réellement disponibles
        self.services_config = KELIO_SERVICES_CONFIG
        
        logger.info(f"Service Kelio V4.1 initialise pour {self.config.nom}")
        logger.info(f">>> {len(self.services_config)} services API disponibles")
    
    def _create_session(self):
        """Cree une session HTTP authentifiee"""
        try:
            username = self.config.username or KELIO_DEFAULT_AUTH['username']
            password = self.config.password or KELIO_DEFAULT_AUTH['password']
            
            print(f">>> Authentification Kelio:")
            print(f"  Username: '{username}'")
            print(f"  Password: '{password}'")
            
            session = Session()
            session.auth = HTTPBasicAuth(username, password)
            
            session.headers.update({
                'Content-Type': 'text/xml; charset=utf-8',
                'User-Agent': 'Django-Interim-Kelio-Sync/4.1-Fixed',
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
    
    def _get_soap_client(self, service_name):
        """Recupere ou cree un client SOAP pour un service disponible"""
        if service_name not in self.clients:
            # Trouver la configuration du service
            service_config = None
            for config in self.services_config.values():
                if config['service_name'] == service_name:
                    service_config = config
                    break
            
            if not service_config:
                raise ValueError(f"Service {service_name} non configure")
            
            wsdl_url = f"{self.config.url_base}/{service_config['wsdl_path']}"
            
            print(f">>> Creation client SOAP pour {service_name}")
            print(f">>> URL WSDL: {wsdl_url}")
            
            try:
                settings_soap = Settings(strict=False, xml_huge_tree=True)
                transport = Transport(session=self.session, timeout=service_config['timeout'])
                
                client = Client(wsdl_url, settings=settings_soap, transport=transport)
                
                self.clients[service_name] = client
                logger.info(f"OK Client SOAP cree pour {service_name}")
                
            except Exception as e:
                logger.error(f"ERROR Erreur creation client SOAP {service_name}: {e}")
                raise KelioConnectionError(
                    f"Erreur creation client SOAP {service_name}: {e}",
                    details={'url': wsdl_url, 'timeout': service_config['timeout'], 'service_name': service_name, 'error': str(e)}
                )
        
        return self.clients[service_name]
    
    def synchroniser_tous_les_employes(self, mode='complet'):
        """Synchronise tous les employes avec les services disponibles"""
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
            'metadata': {
                'nb_appels_api': 0,
                'duree_totale_ms': 0,
                'cache_hits': 0,
                'cache_miss': 0
            }
        }
        
        try:
            # ETAPE 1: Essayer d'abord EmployeeListService
            logger.info(">>> ETAPE 1: Recuperation via EmployeeListService")
            employees_data = self._get_employees_via_list_service()
            
            if not employees_data:
                # ETAPE 1 bis: Fallback vers EmployeeService
                logger.info(">>> ETAPE 1 bis: Fallback vers EmployeeService")
                employees_data = self._get_employees_via_employee_service()
            
            if not employees_data:
                resultats['statut_global'] = 'echec'
                resultats['erreur_critique'] = 'Aucun employe recupere depuis les services Kelio disponibles'
                return resultats
            
            logger.info(f">>> {len(employees_data)} employe(s) trouve(s) dans Kelio")
            resultats['employees_total'] = len(employees_data)
            
            # ETAPE 2: Traitement des employés
            logger.info(">>> ETAPE 2: Traitement des donnees employés")
            for i, employee in enumerate(employees_data):
                try:
                    resultats['employees_traites'] += 1
                    
                    # Traitement simple de l'employé
                    success = self._process_employee_data(employee)
                    
                    if success:
                        resultats['employees_reussis'] += 1
                    else:
                        resultats['employees_erreurs'] += 1
                    
                    resultats['metadata']['nb_appels_api'] += 1
                    
                    logger.info(f">>> Employe {i+1}/{len(employees_data)} traite")
                    
                except Exception as e:
                    resultats['employees_erreurs'] += 1
                    error_msg = f"Erreur employe {i+1}: {str(e)}"
                    resultats['erreurs'].append(error_msg)
                    logger.error(f"ERROR {error_msg}")
            
            # Determiner le statut global
            if resultats['employees_erreurs'] == 0:
                resultats['statut_global'] = 'reussi'
            elif resultats['employees_reussis'] > 0:
                resultats['statut_global'] = 'partiel'
            else:
                resultats['statut_global'] = 'echec'
            
            # Metadonnees finales
            duree_totale = (timezone.now() - resultats['timestamp_debut']).total_seconds() * 1000
            resultats['metadata']['duree_totale_ms'] = duree_totale
            resultats['timestamp_fin'] = timezone.now()
            
            # Resume final
            resultats['resume'] = {
                'employees_total': resultats.get('employees_total', 0),
                'employees_reussis': resultats['employees_reussis'],
                'employees_erreurs': resultats['employees_erreurs'],
                'taux_reussite': round(
                    (resultats['employees_reussis'] / max(1, resultats.get('employees_total', 1))) * 100, 1
                ),
                'duree_totale_sec': round(duree_totale / 1000, 2)
            }
            
            status_emoji = {
                'reussi': 'OK',
                'partiel': 'WARNING', 
                'echec': 'ERROR'
            }.get(resultats['statut_global'], 'UNKNOWN')
            
            logger.info(f"{status_emoji} Synchronisation employes V4.1 terminee: {resultats['statut_global']} en {duree_totale:.0f}ms")
            return resultats
            
        except Exception as e:
            logger.error(f"ERROR Erreur critique synchronisation employes V4.1: {e}")
            resultats['statut_global'] = 'erreur_critique'
            resultats['erreur_critique'] = str(e)
            resultats['timestamp_fin'] = timezone.now()
            return resultats
    
    def _get_employees_via_list_service(self):
        """Récupère les employés via EmployeeListService"""
        try:
            client = self._get_soap_client('EmployeeListService')
            
            logger.debug(">>> Appel EmployeeListService.exportEmployeesList")
            response = client.service.exportEmployeesList()
            
            employees_data = self._extract_employees_from_list_response(response)
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via EmployeeListService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur EmployeeListService: {e}")
            return []
    
    def _get_employees_via_employee_service(self):
        """Récupère les employés via EmployeeService"""
        try:
            client = self._get_soap_client('EmployeeService')
            
            logger.debug(">>> Appel EmployeeService.exportEmployees")
            response = client.service.exportEmployees()
            
            employees_data = self._extract_employees_from_employee_response(response)
            
            logger.info(f">>> {len(employees_data)} employe(s) recupere(s) via EmployeeService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur EmployeeService: {e}")
            return []
    
    def _extract_employees_from_list_response(self, response):
        """Extrait les données employés de EmployeeListService"""
        try:
            employees_data = []
            
            if hasattr(response, 'exportedEmployeesList'):
                employees_raw = response.exportedEmployeesList
            elif hasattr(response, 'employees'):
                employees_raw = response.employees
            else:
                logger.warning("Structure de reponse EmployeeListService non reconnue")
                return employees_data
            
            if not isinstance(employees_raw, list):
                employees_raw = [employees_raw] if employees_raw else []
            
            for emp in employees_raw:
                emp_data = {
                    'id': safe_get_attribute(emp, 'id'),
                    'matricule': safe_get_attribute(emp, 'employeeNumber', ''),
                    'prenom': safe_get_attribute(emp, 'firstName', ''),
                    'nom': safe_get_attribute(emp, 'lastName', ''),
                    'email': safe_get_attribute(emp, 'email', ''),
                    'telephone': safe_get_attribute(emp, 'phone', ''),
                    'actif': not safe_get_attribute(emp, 'archived', False),
                    'source': 'kelio_employee_list',
                    'timestamp_sync': timezone.now().isoformat()
                }
                employees_data.append(emp_data)
            
            logger.debug(f"OK {len(employees_data)} employe(s) extrait(s) depuis EmployeeListService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction EmployeeListService: {e}")
            return []
    
    def _extract_employees_from_employee_response(self, response):
        """Extrait les données employés de EmployeeService"""
        try:
            employees_data = []
            
            if hasattr(response, 'employees'):
                employees_raw = response.employees
            elif hasattr(response, 'employee'):
                employees_raw = response.employee
            else:
                logger.warning("Structure de reponse EmployeeService non reconnue")
                return employees_data
            
            if not isinstance(employees_raw, list):
                employees_raw = [employees_raw] if employees_raw else []
            
            for emp in employees_raw:
                emp_data = {
                    'id': safe_get_attribute(emp, 'id'),
                    'matricule': safe_get_attribute(emp, 'matricule', ''),
                    'prenom': safe_get_attribute(emp, 'prenom', ''),
                    'nom': safe_get_attribute(emp, 'nom', ''),
                    'email': safe_get_attribute(emp, 'email', ''),
                    'telephone': safe_get_attribute(emp, 'telephone', ''),
                    'actif': safe_get_attribute(emp, 'actif', True),
                    'source': 'kelio_employee_service',
                    'timestamp_sync': timezone.now().isoformat()
                }
                employees_data.append(emp_data)
            
            logger.debug(f"OK {len(employees_data)} employe(s) extrait(s) depuis EmployeeService")
            return employees_data
            
        except Exception as e:
            logger.error(f"ERROR Erreur extraction EmployeeService: {e}")
            return []
    
    def _process_employee_data(self, employee_data):
        """Traite les données d'un employé"""
        try:
            from ..models import ProfilUtilisateur
            from django.contrib.auth.models import User
            
            matricule = employee_data.get('matricule')
            if not matricule:
                return False
            
            prenom = employee_data.get('prenom', '')
            nom = employee_data.get('nom', '')
            email = employee_data.get('email', '')
            
            # Rechercher ou créer l'utilisateur
            user = None
            if email:
                user = User.objects.filter(email=email).first()
            
            if not user and matricule:
                user = User.objects.filter(username=matricule).first()
            
            if not user:
                # Créer un nouvel utilisateur
                user = User.objects.create_user(
                    username=matricule,
                    email=email,
                    first_name=prenom,
                    last_name=nom,
                    password=User.objects.make_random_password()
                )
            
            # Rechercher ou créer le profil
            profil, created = ProfilUtilisateur.objects.get_or_create(
                matricule=matricule,
                defaults={
                    'user': user,
                    'type_profil': 'UTILISATEUR',
                    'actif': employee_data.get('actif', True),
                    'kelio_last_sync': timezone.now(),
                    'kelio_sync_status': 'REUSSI'
                }
            )
            
            if not created:
                # Mettre à jour le profil existant
                profil.user = user
                profil.actif = employee_data.get('actif', True)
                profil.kelio_last_sync = timezone.now()
                profil.kelio_sync_status = 'REUSSI'
                profil.save()
            
            logger.debug(f"OK Employe {matricule} traite avec succes")
            return True
            
        except Exception as e:
            logger.error(f"ERROR Erreur traitement employe {employee_data.get('matricule', 'INCONNU')}: {e}")
            return False
    
    def test_connexion_complete_v41(self):
        """Test complet des services Kelio disponibles"""
        test_results = {
            'timestamp': timezone.now().isoformat(),
            'version': '4.1-Fixed',
            'configuration': self.config.nom,
            'services_status': {},
            'global_status': True
        }
        
        logger.info(">>> Test connexion complete Kelio V4.1 Fixed")
        
        try:
            # Tester chaque service configuré
            for service_type, config in self.services_config.items():
                try:
                    logger.info(f">>> Test service {service_type}")
                    client = self._get_soap_client(config['service_name'])
                    
                    test_results['services_status'][service_type] = {
                        'status': 'OK',
                        'service_name': config['service_name'],
                        'description': config['description'],
                        'data_source': config['data_source'],
                        'priority': config['priority']
                    }
                    
                    logger.info(f"OK Service {service_type} OK")
                    
                except Exception as e:
                    test_results['services_status'][service_type] = {
                        'status': 'ERREUR',
                        'error': str(e),
                        'service_name': config['service_name']
                    }
                    if config.get('required_for_creation'):
                        test_results['global_status'] = False
                    logger.error(f"ERROR Service {service_type} echoue: {e}")
            
            # Test spécifique du service principal disponible
            try:
                logger.info(">>> Test spécifique services employés")
                employees_sample = self._get_employees_via_list_service()
                
                if not employees_sample:
                    employees_sample = self._get_employees_via_employee_service()
                
                test_results['service_principal'] = {
                    'status': 'OK' if employees_sample else 'VIDE',
                    'nb_employees_found': len(employees_sample) if employees_sample else 0,
                    'sample_employee': employees_sample[0] if employees_sample else None
                }
                
                if not employees_sample:
                    test_results['global_status'] = False
                    
            except Exception as e:
                test_results['service_principal'] = {
                    'status': 'ERREUR',
                    'error': str(e)
                }
                test_results['global_status'] = False
            
            # Resume final
            services_ok = sum(1 for s in test_results['services_status'].values() if s['status'] == 'OK')
            services_total = len(self.services_config)
            
            test_results['summary'] = {
                'services_ok_count': services_ok,
                'services_total_count': services_total,
                'services_ok_percent': round((services_ok / services_total) * 100, 1) if services_total > 0 else 0,
                'global_success': test_results['global_status'],
                'service_principal_ok': test_results.get('service_principal', {}).get('status') == 'OK'
            }
            
            if test_results['global_status']:
                logger.info("OK Test connexion Kelio V4.1 Fixed REUSSI")
            else:
                logger.warning("WARNING Test connexion Kelio V4.1 Fixed PARTIEL")
            
            return test_results
            
        except Exception as e:
            logger.error(f"ERROR Erreur critique test connexion Kelio V4.1 Fixed: {e}")
            test_results['global_status'] = False
            test_results['error_critique'] = str(e)
            return test_results
        
# ================================================================
# FONCTIONS FACTORY ET UTILITAIRES - VERSION 4.1
# ================================================================

def get_kelio_sync_service_v41(configuration=None):
    """Factory function pour le service Kelio V4.1"""
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
    """Fonction principale pour synchroniser tous les employes depuis Kelio V4.1"""
    try:
        service = get_kelio_sync_service_v41()
        return service.synchroniser_tous_les_employes(mode)
    except Exception as e:
        logger.error(f"ERROR Erreur synchronisation complete V4.1: {e}")
        return {
            'statut_global': 'erreur_critique',
            'erreur_critique': str(e),
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

def creer_utilisateur_depuis_matricule_v41(matricule, mode='complet', **extra_fields):
    """
    Cree un utilisateur depuis Kelio avec les nouvelles API V4.1
    
    Args:
        matricule: Matricule de l'employe
        mode: Mode de synchronisation
        **extra_fields: Champs additionnels
        
    Returns:
        tuple: (ProfilUtilisateur, resultats_sync)
    """
    from ..models import ProfilUtilisateur
    
    try:
        # Verifier que l'employe n'existe pas deja
        if ProfilUtilisateur.objects.filter(matricule=matricule).exists():
            existing_employe = ProfilUtilisateur.objects.get(matricule=matricule)
            raise Exception(f"Employe {matricule} existe deja (ID: {existing_employe.id})")
        
        # Synchroniser avec Kelio V4.1
        resultats_sync = synchroniser_employe_specifique_kelio_v41(matricule, mode)
        
        if resultats_sync['statut_global'] not in ['reussi', 'partiel']:
            raise Exception(f"Echec synchronisation pour {matricule}: {resultats_sync.get('erreur', 'Erreur inconnue')}")
        
        # Recuperer le profil cree lors de la synchronisation
        profil = ProfilUtilisateur.objects.get(matricule=matricule)
        
        # Appliquer les champs supplementaires
        for field, value in extra_fields.items():
            if hasattr(profil, field):
                setattr(profil, field, value)
        
        if extra_fields:
            profil.save()
        
        logger.info(f"OK Utilisateur cree avec succes V4.1: {matricule} - Sync: {resultats_sync['statut_global']}")
        
        return profil, resultats_sync
        
    except Exception as e:
        logger.error(f"ERROR Erreur creation utilisateur V4.1 {matricule}: {e}")
        raise

def tester_nouvelle_configuration_kelio_v41(config_id=None):
    """
    Teste une configuration Kelio avec les nouvelles API V4.1
    
    Args:
        config_id: ID de la configuration a tester
        
    Returns:
        dict: Resultats du test
    """
    try:
        if config_id:
            from ..models import ConfigurationApiKelio
            config = ConfigurationApiKelio.objects.get(id=config_id)
            service = get_kelio_sync_service_v41(config)
        else:
            service = get_kelio_sync_service_v41()
        
        return service.test_connexion_complete_v41()
        
    except Exception as e:
        logger.error(f"ERROR Erreur test configuration V4.1: {e}")
        return {
            'success': False,
            'erreur': str(e),
            'timestamp': timezone.now().isoformat()
        }

# ================================================================
# FONCTIONS DE MIGRATION ET MAINTENANCE
# ================================================================

def migrer_vers_nouvelles_api_kelio_v41():
    """
    Migre les donnees existantes vers les nouvelles API Kelio V4.1
    
    Returns:
        dict: Rapport de migration
    """
    logger.info(">>> Debut migration vers nouvelles API Kelio V4.1")
    
    migration_rapport = {
        'timestamp_debut': timezone.now(),
        'employes_migres': 0,
        'employes_erreurs': 0,
        'services_testes': {},
        'erreurs': [],
        'statut_global': 'en_cours'
    }
    
    try:
        from ..models import ProfilUtilisateur
        
        # Test initial des nouvelles API
        test_api = tester_nouvelle_configuration_kelio_v41()
        migration_rapport['test_api'] = test_api
        
        if not test_api.get('global_status', False):
            migration_rapport['statut_global'] = 'echec_api'
            migration_rapport['erreur_critique'] = 'Nouvelles API Kelio V4.1 non accessibles'
            return migration_rapport
        
        # Recuperer tous les employes existants
        employes_existants = ProfilUtilisateur.objects.filter(actif=True)
        migration_rapport['employes_total'] = employes_existants.count()
        
        logger.info(f">>> Migration V4.1: {migration_rapport['employes_total']} employes a traiter")
        
        # Migrer chaque employe
        for employe in employes_existants:
            try:
                logger.info(f">>> Migration employe V4.1 {employe.matricule}")
                
                # Resynchroniser avec les nouvelles API V4.1
                resultats_sync = synchroniser_employe_specifique_kelio_v41(employe.matricule, mode='complet')
                
                if resultats_sync.get('statut_global') in ['reussi', 'partiel']:
                    migration_rapport['employes_migres'] += 1
                    
                    # Mettre a jour le statut de migration
                    employe.kelio_sync_status = 'REUSSI'
                    employe.kelio_last_sync = timezone.now()
                    employe.save(update_fields=['kelio_sync_status', 'kelio_last_sync'])
                else:
                    migration_rapport['employes_erreurs'] += 1
                    error_msg = f"Erreur migration {employe.matricule}: {resultats_sync.get('erreur', 'Erreur inconnue')}"
                    migration_rapport['erreurs'].append(error_msg)
                
            except Exception as e:
                migration_rapport['employes_erreurs'] += 1
                error_msg = f"Erreur migration {employe.matricule}: {str(e)}"
                migration_rapport['erreurs'].append(error_msg)
                logger.error(f"ERROR {error_msg}")
        
        # Determiner le statut final
        if migration_rapport['employes_erreurs'] == 0:
            migration_rapport['statut_global'] = 'reussi'
        elif migration_rapport['employes_migres'] > 0:
            migration_rapport['statut_global'] = 'partiel'
        else:
            migration_rapport['statut_global'] = 'echec'
        
        duree_totale = (timezone.now() - migration_rapport['timestamp_debut']).total_seconds()
        migration_rapport['timestamp_fin'] = timezone.now()
        migration_rapport['duree_totale_sec'] = round(duree_totale, 2)
        migration_rapport['taux_reussite'] = round(
            (migration_rapport['employes_migres'] / max(1, migration_rapport['employes_total'])) * 100, 1
        )
        
        status_emoji = {'reussi': 'OK', 'partiel': 'WARNING', 'echec': 'ERROR'}.get(migration_rapport['statut_global'], 'UNKNOWN')
        logger.info(f"{status_emoji} Migration V4.1 terminee: {migration_rapport['statut_global']} - {migration_rapport['taux_reussite']}% reussite")
        
        return migration_rapport
        
    except Exception as e:
        logger.error(f"ERROR Erreur critique migration V4.1: {e}")
        migration_rapport['statut_global'] = 'erreur_critique'
        migration_rapport['erreur_critique'] = str(e)
        migration_rapport['timestamp_fin'] = timezone.now()
        return migration_rapport

def nettoyer_cache_kelio_expire_v41():
    """Nettoie le cache Kelio expire V4.1"""
    try:
        from ..models import CacheApiKelio
        
        count = CacheApiKelio.objects.filter(
            date_expiration__lt=timezone.now()
        ).delete()[0]
        
        logger.info(f">>> Cache Kelio V4.1 nettoye: {count} entrees expirees supprimees")
        return count
        
    except Exception as e:
        logger.error(f"ERROR Erreur nettoyage cache Kelio V4.1: {e}")
        return 0

def obtenir_statistiques_cache_kelio_v41():
    """Obtient les statistiques du cache Kelio V4.1"""
    try:
        from ..models import CacheApiKelio
        from django.db import models        
        
        stats = {
            'total_entrees': CacheApiKelio.objects.count(),
            'entrees_valides': CacheApiKelio.objects.filter(
                date_expiration__gt=timezone.now()
            ).count(),
            'entrees_expirees': CacheApiKelio.objects.filter(
                date_expiration__lt=timezone.now()
            ).count(),
            'services_caches': list(
                CacheApiKelio.objects.values_list('service_name', flat=True).distinct()
            ),
            'timestamp': timezone.now().isoformat(),
            'version': '4.1'
        }
        
        # Calculer la taille totale
        total_size = CacheApiKelio.objects.aggregate(
            total=models.Sum('taille_donnees')
        ).get('total', 0)

        stats['taille_totale_bytes'] = total_size or 0
        stats['taille_totale_mb'] = round((total_size or 0) / 1024 / 1024, 2)
        
        return stats
        
    except Exception as e:
        logger.error(f"ERROR Erreur statistiques cache V4.1: {e}")
        return {}

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

# ================================================================
# FONCTIONS D'ASSISTANCE SUPPLEMENTAIRES V4.1
# ================================================================

def synchroniser_donnees_kelio_only_v41(matricule, services_specifiques=None):
    """
    Synchronise uniquement les donnees Kelio-only avec les nouvelles API V4.1
    
    Args:
        matricule: Matricule de l'employe
        services_specifiques: Liste des services a synchroniser (optionnel)
        
    Returns:
        dict: Resultats de synchronisation
    """
    try:
        service = get_kelio_sync_service_v41()
        
        # Services Kelio-only par defaut
        if not services_specifiques:
            services_specifiques = [
                'job_assignments',
                'employee_job_assignments',
                'professional_experience',
                'employee_pictures',
                'labor_contracts'
            ]
        
        resultats = {
            'matricule': matricule,
            'timestamp_debut': timezone.now(),
            'services_synchronises': {},
            'erreurs': [],
            'statut_global': 'en_cours'
        }
        
        # Synchroniser chaque service Kelio-only
        for service_type in services_specifiques:
            try:
                if service_type == 'job_assignments':
                    donnees = service._get_job_assignments_v41(matricule)
                elif service_type == 'employee_job_assignments':
                    donnees = service._get_employee_job_assignments_v41(matricule)
                elif service_type == 'professional_experience':
                    donnees = service._get_professional_experience_v41(matricule)
                elif service_type == 'employee_pictures':
                    donnees = service._get_employee_pictures_v41(matricule)
                elif service_type == 'labor_contracts':
                    donnees = service._get_labor_contracts_v41(matricule)
                else:
                    continue
                
                resultats['services_synchronises'][service_type] = donnees
                
                # Sauvegarder en cache
                service_config = service.services_config.get(service_type, {})
                cache_duration = service_config.get('cache_duration', 3600)
                service._save_to_kelio_cache(service_type, matricule, donnees, cache_duration)
                
            except Exception as e:
                error_msg = f"Erreur {service_type}: {str(e)}"
                resultats['erreurs'].append(error_msg)
                logger.error(f"ERROR {error_msg}")
        
        # Determiner le statut global
        nb_reussis = len(resultats['services_synchronises'])
        nb_erreurs = len(resultats['erreurs'])
        
        if nb_erreurs == 0:
            resultats['statut_global'] = 'reussi'
        elif nb_reussis > 0:
            resultats['statut_global'] = 'partiel'
        else:
            resultats['statut_global'] = 'echec'
        
        resultats['timestamp_fin'] = timezone.now()
        resultats['resume'] = {
            'services_reussis': nb_reussis,
            'services_erreur': nb_erreurs,
            'total_demandes': len(services_specifiques)
        }
        
        logger.info(f">>> Sync Kelio-only V4.1 {matricule}: {nb_reussis} reussis, {nb_erreurs} erreurs")
        return resultats
        
    except Exception as e:
        logger.error(f"ERROR Erreur sync Kelio-only V4.1 {matricule}: {e}")
        return {
            'matricule': matricule,
            'statut_global': 'erreur_critique',
            'erreur_critique': str(e),
            'timestamp': timezone.now().isoformat()
        }

def obtenir_resume_synchronisation_kelio_v41():
    """Obtient un resume des dernieres synchronisations V4.1"""
    try:
        from ..models import ProfilUtilisateur
        
        # Statistiques generales
        stats = {
            'total_employes': ProfilUtilisateur.objects.count(),
            'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
            'employes_syncs_kelio': ProfilUtilisateur.objects.filter(
                kelio_sync_status__in=['REUSSI', 'REUSSI_V4']
            ).count(),
            'timestamp': timezone.now().isoformat(),
            'version': '4.1'
        }
        
        # Dernieres synchronisations
        dernieres_syncs = ProfilUtilisateur.objects.filter(
            kelio_last_sync__isnull=False
        ).order_by('-kelio_last_sync')[:10]
        
        stats['dernieres_synchronisations'] = [
            {
                'matricule': emp.matricule,
                'nom_complet': f"{emp.user.first_name} {emp.user.last_name}" if emp.user else emp.matricule,
                'status': emp.kelio_sync_status,
                'derniere_sync': emp.kelio_last_sync.isoformat() if emp.kelio_last_sync else None
            }
            for emp in dernieres_syncs
        ]
        
        # Statuts de synchronisation
        from django.db import models
        status_counts = ProfilUtilisateur.objects.values('kelio_sync_status').annotate(
            count=models.Count('id')
        )
        stats['statuts_sync'] = {item['kelio_sync_status']: item['count'] for item in status_counts}
        
        # Statistiques des donnees peripheriques
        stats['donnees_peripheriques'] = {
            'competences': ProfilUtilisateur.objects.filter(
                competences__source_donnee='KELIO'
            ).distinct().count(),
            'formations': ProfilUtilisateur.objects.filter(
                formations__source_donnee='KELIO'
            ).distinct().count(),
            'absences': ProfilUtilisateur.objects.filter(
                absences__source_donnee='KELIO'
            ).distinct().count(),
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"ERROR Erreur resume synchronisation V4.1: {e}")
        return {}

def valider_donnees_synchronisees_v41(matricule):
    """Valide que toutes les donnees ont ete correctement synchronisees"""
    try:
        from ..models import (ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended,
                            CompetenceUtilisateur, FormationUtilisateur, AbsenceUtilisateur)
        
        rapport = {
            'matricule': matricule,
            'timestamp': timezone.now().isoformat(),
            'version': '4.1',
            'validations': {},
            'erreurs': [],
            'statut_global': 'en_cours'
        }
        
        try:
            profil = ProfilUtilisateur.objects.get(matricule=matricule)
            rapport['profil_trouve'] = True
            
            # Valider la presence des tables liees
            validations = {
                'user_associe': profil.user is not None,
                'donnees_kelio': hasattr(profil, 'kelio_data'),
                'donnees_etendues': hasattr(profil, 'extended_data'),
                'competences_kelio': profil.competences.filter(source_donnee='KELIO').exists(),
                'formations_kelio': profil.formations.filter(source_donnee='KELIO').exists(),
                'absences_kelio': profil.absences.filter(source_donnee='KELIO').exists(),
                'sync_recent': profil.kelio_last_sync and 
                               (timezone.now() - profil.kelio_last_sync).days < 1,
                'statut_sync_ok': profil.kelio_sync_status == 'REUSSI'
            }
            
            rapport['validations'] = validations
            
            # Compter les elements synchronises
            rapport['compteurs'] = {
                'competences_kelio': profil.competences.filter(source_donnee='KELIO').count(),
                'formations_kelio': profil.formations.filter(source_donnee='KELIO').count(),
                'absences_kelio': profil.absences.filter(source_donnee='KELIO').count(),
            }
            
            # Determiner le statut global
            validations_reussies = sum(1 for v in validations.values() if v)
            total_validations = len(validations)
            
            if validations_reussies == total_validations:
                rapport['statut_global'] = 'parfait'
            elif validations_reussies >= total_validations * 0.8:
                rapport['statut_global'] = 'bon'
            elif validations_reussies >= total_validations * 0.5:
                rapport['statut_global'] = 'moyen'
            else:
                rapport['statut_global'] = 'insuffisant'
            
            rapport['score_validation'] = round((validations_reussies / total_validations) * 100, 1)
            
        except ProfilUtilisateur.DoesNotExist:
            rapport['profil_trouve'] = False
            rapport['statut_global'] = 'erreur'
            rapport['erreurs'].append(f"ProfilUtilisateur {matricule} non trouve")
        
        return rapport
        
    except Exception as e:
        logger.error(f"ERROR Erreur validation donnees V4.1 {matricule}: {e}")
        return {
            'matricule': matricule,
            'statut_global': 'erreur_critique',
            'erreur_critique': str(e),
            'timestamp': timezone.now().isoformat()
        }

def executer_synchronisation_programmee_v41():
    """Execute une synchronisation programmee complete V4.1"""
    logger.info(">>> Debut synchronisation programmee V4.1")
    
    try:
        from ..models import ConfigurationApiKelio
        
        # Verifier qu'une configuration est active
        config_active = ConfigurationApiKelio.objects.filter(actif=True).first()
        if not config_active:
            logger.error("ERROR Aucune configuration Kelio active pour synchronisation programmee")
            return {
                'statut': 'erreur',
                'message': 'Aucune configuration Kelio active'
            }
        
        # Lancer la synchronisation complete
        resultats = synchroniser_tous_employes_kelio_v41(mode='complet')
        
        # Nettoyer le cache expire
        cache_nettoye = nettoyer_cache_kelio_expire_v41()
        resultats['cache_nettoye'] = cache_nettoye
        
        # Generer un rapport de synthese
        synthese = obtenir_resume_synchronisation_kelio_v41()
        resultats['synthese'] = synthese
        
        logger.info(f"OK Synchronisation programmee V4.1 terminee: {resultats.get('statut_global', 'inconnu')}")
        
        return resultats
        
    except Exception as e:
        logger.error(f"ERROR Erreur synchronisation programmee V4.1: {e}")
        return {
            'statut': 'erreur_critique',
            'erreur': str(e),
            'timestamp': timezone.now().isoformat()
        }

# ================================================================
# UTILITAIRES DE MAINTENANCE ET DEBUGGING V4.1
# ================================================================

def debug_service_kelio_v41(service_type, matricule=None):
    """Utilitaire de debug pour un service specifique V4.1"""
    try:
        service = get_kelio_sync_service_v41()
        
        debug_info = {
            'service_type': service_type,
            'matricule': matricule,
            'timestamp': timezone.now().isoformat(),
            'version': '4.1',
            'tests': {},
            'erreurs': []
        }
        
        # Test 1: Verifier la configuration du service
        if service_type in service.services_config:
            config = service.services_config[service_type]
            debug_info['configuration'] = config
            debug_info['tests']['configuration_ok'] = True
        else:
            debug_info['tests']['configuration_ok'] = False
            debug_info['erreurs'].append(f"Service {service_type} non configure")
            return debug_info
        
        # Test 2: Creer le client SOAP
        try:
            client = service._get_soap_client(config['service_name'])
            debug_info['tests']['client_soap_ok'] = True
            debug_info['client_info'] = {
                'service_name': config['service_name'],
                'wsdl_url': f"{service.config.url_base}/{config['wsdl_path']}"
            }
        except Exception as e:
            debug_info['tests']['client_soap_ok'] = False
            debug_info['erreurs'].append(f"Erreur creation client SOAP: {str(e)}")
            return debug_info
        
        # Test 3: Appel de test du service
        if matricule:
            try:
                if service_type == 'employee_professional_data':
                    donnees = service._get_single_employee_professional_data(matricule)
                elif service_type == 'skill_assignments':
                    donnees = service._get_skill_assignments_v41(matricule)
                elif service_type == 'training_history':
                    donnees = service._get_training_history_v41(matricule)
                elif service_type == 'absence_requests':
                    donnees = service._get_absence_requests_v41(matricule)
                else:
                    donnees = {'test': 'service non teste individuellement'}
                
                debug_info['tests']['appel_service_ok'] = True
                debug_info['donnees_retournees'] = {
                    'type': type(donnees).__name__,
                    'taille': len(str(donnees)),
                    'contient_erreur': 'erreur' in str(donnees).lower(),
                    'apercu': str(donnees)[:500] + '...' if len(str(donnees)) > 500 else str(donnees)
                }
                
            except Exception as e:
                debug_info['tests']['appel_service_ok'] = False
                debug_info['erreurs'].append(f"Erreur appel service: {str(e)}")
        
        # Determiner le statut global
        tests_reussis = sum(1 for v in debug_info['tests'].values() if v)
        total_tests = len(debug_info['tests'])
        
        debug_info['statut_global'] = 'ok' if tests_reussis == total_tests else 'erreur'
        debug_info['score_tests'] = f"{tests_reussis}/{total_tests}"
        
        return debug_info
        
    except Exception as e:
        logger.error(f"ERROR Erreur debug service V4.1: {e}")
        return {
            'service_type': service_type,
            'statut_global': 'erreur_critique',
            'erreur_critique': str(e),
            'timestamp': timezone.now().isoformat()
        }

def exporter_configuration_kelio_v41():
    """Exporte la configuration actuelle pour sauvegarde/debug"""
    try:
        from ..models import ConfigurationApiKelio
        
        config_active = ConfigurationApiKelio.objects.filter(actif=True).first()
        if not config_active:
            return {'erreur': 'Aucune configuration active'}
        
        export_data = {
            'version': '4.1',
            'timestamp': timezone.now().isoformat(),
            'configuration': {
                'nom': config_active.nom,
                'url_base': config_active.url_base,
                'username': config_active.username,
                'timeout_seconds': config_active.timeout_seconds,
                'services_disponibles': {
                    'service_employees': config_active.service_employees,
                    'service_absences': config_active.service_absences,
                    'service_formations': config_active.service_formations,
                    'service_competences': config_active.service_competences
                }
            },
            'services_configures': KELIO_SERVICES_CONFIG,
            'authentification_defaut': KELIO_DEFAULT_AUTH
        }
        
        return export_data
        
    except Exception as e:
        logger.error(f"ERROR Erreur export configuration V4.1: {e}")
        return {'erreur': str(e)}

# ================================================================
# AFFICHAGE DES STATISTIQUES AU CHARGEMENT
# ================================================================

# Afficher les statistiques au chargement du module
afficher_statistiques_service_v41()

# ================================================================
# FIN DU SERVICE KELIO V4.1 REFACTORISE
# ================================================================