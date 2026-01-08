# -*- coding: utf-8 -*-
"""
Service de synchronisation Kelio - Version 4.2 CORRIGÉE
Corrections spécifiques pour les problèmes identifiés dans les logs

CORRECTIONS V4.2 :
- Amélioration de l'extraction des données employés (stratégies multiples)
- Gestion robuste des erreurs de concurrence 
- Traitement intelligent des structures non reconnues
- Déduplication des employés
- Retry automatique avec backoff exponentiel
- Meilleure gestion des timeouts
"""

import json
import logging
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import User
from django.core.cache import cache

# Import des modèles
from ..models import (
    ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended,
    ConfigurationApiKelio, CacheApiKelio, Departement, Site, Poste,
    Competence, CompetenceUtilisateur, FormationUtilisateur, 
    AbsenceUtilisateur, MotifAbsence
)

# Imports SOAP avec gestion des erreurs
try:
    from zeep import Client, Settings, Transport
    from zeep.exceptions import Fault, TransportError
    from zeep.helpers import serialize_object
    from requests import Session
    from requests.auth import HTTPBasicAuth
    import requests
    SOAP_AVAILABLE = True
except ImportError:
    SOAP_AVAILABLE = False

logger = logging.getLogger('kelio.sync')

class KelioSyncServiceV42:
    """Service de synchronisation Kelio corrigé - Version 4.2"""
    
    def __init__(self, configuration=None):
        """Initialise le service avec gestion d'erreurs robuste"""
        if not SOAP_AVAILABLE:
            raise Exception("Dépendances SOAP manquantes (zeep, requests)")
        
        self.config = configuration or ConfigurationApiKelio.objects.filter(actif=True).first()
        if not self.config:
            raise Exception("Aucune configuration Kelio active trouvée")
        
        # Configuration retry
        self.max_retries = 3
        self.retry_delay = 2  # secondes
        self.timeout = self.config.timeout_seconds or 60
        
        # Statistiques
        self.stats = {
            'employees_processed': 0,
            'employees_success': 0,
            'employees_errors': 0,
            'retries_count': 0,
            'duplicates_handled': 0
        }
        
        # Cache pour éviter les doublons
        self.processed_employees = set()
        
        # Session HTTP optimisée
        self.session = self._create_optimized_session()
        self.clients = {}
        
        logger.info(f"Service Kelio V4.2 initialisé pour {self.config.nom}")
    
    def _create_optimized_session(self):
        """Crée une session HTTP optimisée avec retry et auth"""
        session = Session()
        
        # Auth basique
        username = self.config.username or 'webservices'
        password = self.config.password or '12345'
        session.auth = HTTPBasicAuth(username, password)
        
        # Headers optimisés
        session.headers.update({
            'Content-Type': 'text/xml; charset=utf-8',
            'User-Agent': 'Django-Interim-Kelio-V4.2',
            'Accept': 'text/xml, application/xml',
            'Connection': 'keep-alive'
        })
        
        # Retry automatique
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        logger.info(f"Session HTTP créée pour {username}")
        return session
    
    def _get_soap_client_with_retry(self, service_name, use_fallback=False):
        """Récupère un client SOAP avec retry automatique"""
        client_key = f"{service_name}_fallback" if use_fallback else service_name
        
        if client_key in self.clients:
            return self.clients[client_key]
        
        # Mapping des services
        service_config = {
            'EmployeeListService': {
                'wsdl': 'EmployeeListService?wsdl',
                'fallback_wsdl': 'EmployeeService?wsdl'
            },
            'EmployeeService': {
                'wsdl': 'EmployeeService?wsdl'
            },
            'SkillAssignmentService': {
                'wsdl': 'SkillAssignmentService?wsdl'
            },
            'InitialFormationAssignmentService': {
                'wsdl': 'InitialFormationAssignmentService?wsdl'
            },
            'AbsenceRequestService': {
                'wsdl': 'AbsenceRequestService?wsdl'
            },
            'EmployeeTrainingHistoryService': {
                'wsdl': 'EmployeeTrainingHistoryService?wsdl'
            },
            'CoefficientAssignmentService': {
                'wsdl': 'CoefficientAssignmentService?wsdl'
            }
        }
        
        config = service_config.get(service_name, {})
        wsdl_path = config.get('fallback_wsdl' if use_fallback else 'wsdl', f"{service_name}?wsdl")
        wsdl_url = f"{self.config.url_base}/{wsdl_path}"
        
        for attempt in range(self.max_retries):
            try:
                print(f">>> Création client SOAP pour {service_name}")
                print(f">>> URL WSDL: {wsdl_url}")
                
                settings = Settings(strict=False, xml_huge_tree=True)
                transport = Transport(session=self.session, timeout=self.timeout)
                
                client = Client(wsdl_url, settings=settings, transport=transport)
                self.clients[client_key] = client
                
                logger.info(f"OK Client SOAP créé pour {service_name}")
                return client
                
            except Exception as e:
                self.stats['retries_count'] += 1
                logger.error(f"ERROR Erreur création client SOAP {service_name}: {e}")
                
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)  # Backoff exponentiel
                    logger.info(f"Retry dans {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Erreur création client SOAP {service_name}: {e}")
        
        return None
    
    def synchroniser_tous_employes_optimise(self):
        """Synchronisation optimisée de tous les employés avec gestion d'erreurs robuste"""
        logger.info("🚀 === DÉBUT SYNCHRONISATION EMPLOYÉS V4.2 OPTIMISÉE ===")
        
        start_time = timezone.now()
        
        resultats = {
            'statut_global': 'en_cours',
            'timestamp_debut': start_time,
            'donnees_globales': {
                'employes_traites': 0,
                'nouveaux_employes': 0,
                'employes_mis_a_jour': 0,
                'erreurs': 0,
                'doublons_geres': 0
            },
            'metadata': {
                'service_utilise': None,
                'fallback_utilise': False,
                'retries_total': 0
            },
            'erreurs_details': []
        }
        
        try:
            # ÉTAPE 1: Récupération des employés avec fallback intelligent
            employees_data = self._get_employees_with_smart_fallback()
            
            if not employees_data:
                resultats['statut_global'] = 'echec'
                resultats['erreur'] = 'Aucun employé récupéré depuis Kelio'
                return resultats
            
            logger.info(f"📋 {len(employees_data)} employé(s) récupéré(s)")
            
            # ÉTAPE 2: Déduplication intelligente
            employees_deduplicated = self._deduplicate_employees(employees_data)
            resultats['donnees_globales']['doublons_geres'] = len(employees_data) - len(employees_deduplicated)
            
            logger.info(f"🔄 {len(employees_deduplicated)} employé(s) après déduplication")
            
            # ÉTAPE 3: Traitement par lots avec gestion d'erreurs
            batch_size = 10  # Traiter par petits lots
            total_batches = (len(employees_deduplicated) + batch_size - 1) // batch_size
            
            for i in range(0, len(employees_deduplicated), batch_size):
                batch = employees_deduplicated[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                
                logger.info(f"📦 Traitement lot {batch_num}/{total_batches} ({len(batch)} employés)")
                
                batch_results = self._process_employee_batch(batch)
                
                # Agrégation des résultats
                resultats['donnees_globales']['employes_traites'] += batch_results['processed']
                resultats['donnees_globales']['nouveaux_employes'] += batch_results['created']
                resultats['donnees_globales']['employes_mis_a_jour'] += batch_results['updated']
                resultats['donnees_globales']['erreurs'] += batch_results['errors']
                resultats['erreurs_details'].extend(batch_results['error_details'])
            
            # ÉTAPE 4: Finalisation
            duration = (timezone.now() - start_time).total_seconds()
            
            # Déterminer le statut global
            total_success = resultats['donnees_globales']['nouveaux_employes'] + resultats['donnees_globales']['employes_mis_a_jour']
            if resultats['donnees_globales']['erreurs'] == 0:
                resultats['statut_global'] = 'reussi'
            elif total_success > 0:
                resultats['statut_global'] = 'partiel'
            else:
                resultats['statut_global'] = 'echec'
            
            resultats.update({
                'timestamp_fin': timezone.now(),
                'metadata': {
                    **resultats['metadata'],
                    'duree_totale_sec': round(duration, 2),
                    'retries_total': self.stats['retries_count']
                }
            })
            
            logger.info(f"✅ Synchronisation terminée: {resultats['statut_global']} en {duration:.2f}s")
            return resultats
            
        except Exception as e:
            logger.error(f"ERROR Erreur critique synchronisation V4.2: {e}")
            resultats.update({
                'statut_global': 'erreur_critique',
                'erreur': str(e),
                'timestamp_fin': timezone.now()
            })
            return resultats
    
    def _get_employees_with_smart_fallback(self):
        """Récupération intelligente des employés avec fallback"""
        employees_data = []
        
        # Stratégie 1: EmployeeListService
        try:
            logger.info(">>> ÉTAPE 1: Récupération via EmployeeListService")
            client = self._get_soap_client_with_retry('EmployeeListService')
            response = client.service.exportEmployeeList()
            employees_data = self._extract_employees_robust(response, 'EmployeeListService')
            
            if employees_data:
                logger.info(f"✅ EmployeeListService: {len(employees_data)} employés")
                return employees_data
                
        except Exception as e:
            logger.error(f"ERROR EmployeeListService échoué: {e}")
        
        # Stratégie 2: EmployeeService (fallback)
        try:
            logger.info(">>> ÉTAPE 1 bis: Fallback vers EmployeeService")
            client = self._get_soap_client_with_retry('EmployeeService')
            response = client.service.exportEmployees()
            employees_data = self._extract_employees_robust(response, 'EmployeeService')
            
            if employees_data:
                logger.info(f"✅ EmployeeService: {len(employees_data)} employés")
                return employees_data
                
        except Exception as e:
            logger.error(f"ERROR EmployeeService échoué: {e}")
        
        return employees_data
    
    def _extract_employees_robust(self, response, service_name):
        """Extraction robuste avec multiples stratégies AMÉLIORÉES"""
        logger.info(f"🔍 Extraction robuste depuis {service_name}")
        
        employees = []
        
        try:
            # STRATÉGIE 1: Sérialisation Zeep (améliorée)
            serialized = serialize_object(response)
            logger.info(f"📦 Sérialisé: {type(serialized)}")
            
            if isinstance(serialized, list) and serialized:
                logger.info(f"📋 Liste de {len(serialized)} éléments")
                for i, item in enumerate(serialized):
                    emp_data = self._extract_employee_from_any_format(item, f"{service_name}[{i}]")
                    if emp_data:
                        employees.append(emp_data)
                        
            elif isinstance(serialized, dict):
                logger.info(f"📋 Dict avec clés: {list(serialized.keys())}")
                employees = self._extract_employees_from_dict_structure(serialized, service_name)
                
            if employees:
                logger.info(f"✅ STRATÉGIE 1 RÉUSSIE: {len(employees)} employés")
                return employees
                
        except Exception as e:
            logger.debug(f"⚠️ Stratégie 1 échouée: {e}")
        
        # STRATÉGIE 2: Exploration directe des attributs (améliorée)
        try:
            logger.info("🔍 STRATÉGIE 2: exploration attributs...")
            
            # Attributs prometteurs pour employés
            employee_attrs = [
                'exportedEmployeeList', 'employeeList', 'employees', 'exportEmployees',
                'Employee', 'employee', 'data', 'result', 'response'
            ]
            
            for attr_name in employee_attrs:
                if hasattr(response, attr_name):
                    attr_value = getattr(response, attr_name)
                    logger.info(f"🎯 Attribut trouvé: {attr_name} ({type(attr_value)})")
                    
                    if isinstance(attr_value, list) and attr_value:
                        for item in attr_value:
                            emp_data = self._extract_employee_from_any_format(item, f"{attr_name}")
                            if emp_data:
                                employees.append(emp_data)
                    
                    elif attr_value and not isinstance(attr_value, (str, int, float, bool)):
                        emp_data = self._extract_employee_from_any_format(attr_value, attr_name)
                        if emp_data:
                            employees.append(emp_data)
                    
                    if employees:
                        logger.info(f"✅ STRATÉGIE 2 RÉUSSIE: {len(employees)} employés via {attr_name}")
                        return employees
                        
        except Exception as e:
            logger.debug(f"⚠️ Stratégie 2 échouée: {e}")
        
        # STRATÉGIE 3: Exploration récursive limitée
        try:
            logger.info("🔍 STRATÉGIE 3: exploration récursive...")
            employees = self._recursive_employee_search(response, max_depth=3)
            if employees:
                logger.info(f"✅ STRATÉGIE 3 RÉUSSIE: {len(employees)} employés")
                return employees
                
        except Exception as e:
            logger.debug(f"⚠️ Stratégie 3 échouée: {e}")
        
        logger.warning(f"⚠️ Toutes les stratégies ont échoué pour {service_name}")
        return []
    
    def _extract_employees_from_dict_structure(self, data_dict, source):
        """Extrait employés depuis une structure dictionnaire"""
        employees = []
        
        for key, value in data_dict.items():
            key_lower = key.lower()
            
            # Chercher des clés prometteuses
            if any(keyword in key_lower for keyword in ['employee', 'export', 'list', 'data']):
                logger.debug(f"🎯 Clé prometteuse: {key}")
                
                if isinstance(value, list) and value:
                    for i, item in enumerate(value):
                        emp_data = self._extract_employee_from_any_format(item, f"{source}.{key}[{i}]")
                        if emp_data:
                            employees.append(emp_data)
                
                elif value and not isinstance(value, (str, int, float, bool)):
                    emp_data = self._extract_employee_from_any_format(value, f"{source}.{key}")
                    if emp_data:
                        employees.append(emp_data)
        
        return employees
    
    def _extract_employee_from_any_format(self, item, source):
        """Extrait un employé depuis n'importe quel format"""
        if not item:
            return None
        
        try:
            # Mapping amélioré des champs employés
            field_mappings = {
                'matricule': [
                    'employeeIdentificationNumber', 'identificationNumber', 'employeeNumber',
                    'id', 'matricule', 'empId', 'badgeNumber', 'employeeId'
                ],
                'employee_key': [
                    'employeeKey', 'key', 'employee_id', 'empKey'
                ],
                'badge_code': [
                    'employeeBadgeCode', 'badgeCode', 'badge', 'badgeNumber'
                ],
                'nom': [
                    'employeeSurname', 'surname', 'lastName', 'nom', 'familyName'
                ],
                'prenom': [
                    'employeeFirstName', 'firstName', 'prenom', 'givenName'
                ],
                'email': [
                    'professionalEmail', 'email', 'emailAddress', 'workEmail'
                ],
                'telephone': [
                    'professionalPhoneNumber1', 'phoneNumber', 'telephone', 'phone'
                ],
                'archived': [
                    'archivedEmployee', 'archived', 'inactive', 'isArchived'
                ],
                'department': [
                    'currentDepartmentDescription', 'departmentDescription', 'department'
                ],
                'job': [
                    'currentJobDescription', 'jobDescription', 'job', 'jobTitle'
                ]
            }
            
            emp_data = {}
            
            # Extraction selon le type d'item
            if isinstance(item, dict):
                for target_field, possible_keys in field_mappings.items():
                    for key in possible_keys:
                        if key in item and item[key] is not None and item[key] != '':
                            emp_data[target_field] = str(item[key]).strip()
                            break
            
            elif hasattr(item, '__dict__') or hasattr(item, '__getattribute__'):
                for target_field, possible_keys in field_mappings.items():
                    for key in possible_keys:
                        try:
                            value = getattr(item, key, None)
                            if value is not None and str(value).strip():
                                emp_data[target_field] = str(value).strip()
                                break
                        except:
                            continue
            
            # Validation et nettoyage
            if not emp_data.get('matricule'):
                # Générer matricule temporaire basé sur d'autres champs
                nom = emp_data.get('nom', '')
                prenom = emp_data.get('prenom', '')
                if nom or prenom:
                    import uuid
                    emp_data['matricule'] = f"{prenom[:3]}{nom[:3]}_{uuid.uuid4().hex[:4]}".upper()
                else:
                    return None  # Pas assez d'infos
            
            # Ajouter métadonnées
            emp_data.update({
                'source': source,
                'timestamp_sync': timezone.now().isoformat()
            })
            
            return emp_data
            
        except Exception as e:
            logger.debug(f"Erreur extraction employé: {e}")
            return None
    
    def _recursive_employee_search(self, obj, path="", depth=0, max_depth=3):
        """Recherche récursive d'employés avec limitation de profondeur"""
        if depth > max_depth:
            return []
        
        employees = []
        
        try:
            if isinstance(obj, list):
                for i, item in enumerate(obj[:20]):  # Limiter à 20 éléments
                    sub_employees = self._recursive_employee_search(
                        item, f"{path}[{i}]", depth+1, max_depth
                    )
                    employees.extend(sub_employees)
            
            elif self._looks_like_employee(obj):
                emp_data = self._extract_employee_from_any_format(obj, path)
                if emp_data:
                    employees.append(emp_data)
            
            elif hasattr(obj, '__dict__') and depth < max_depth:
                for attr_name, attr_value in list(obj.__dict__.items())[:10]:  # Limiter
                    if not attr_name.startswith('_') and attr_value is not None:
                        sub_employees = self._recursive_employee_search(
                            attr_value, f"{path}.{attr_name}", depth+1, max_depth
                        )
                        employees.extend(sub_employees)
        
        except Exception as e:
            logger.debug(f"Erreur recherche récursive: {e}")
        
        return employees
    
    def _looks_like_employee(self, obj):
        """Détermine si un objet ressemble à un employé"""
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return False
        
        employee_indicators = [
            'employee', 'name', 'nom', 'surname', 'firstname', 'prenom',
            'id', 'key', 'matricule', 'badge', 'identification',
            'email', 'phone', 'telephone', 'department'
        ]
        
        obj_attrs = []
        
        try:
            if isinstance(obj, dict):
                obj_attrs = list(obj.keys())
            elif hasattr(obj, '__dict__'):
                obj_attrs.extend(obj.__dict__.keys())
            
            if hasattr(obj, '__class__'):
                obj_attrs.extend([attr for attr in dir(obj) if not attr.startswith('_')][:10])
        except:
            return False
        
        matches = 0
        for attr in obj_attrs:
            attr_lower = str(attr).lower()
            for indicator in employee_indicators:
                if indicator in attr_lower:
                    matches += 1
                    break
        
        return matches >= 2
    
    def _deduplicate_employees(self, employees_data):
        """Déduplique les employés selon plusieurs critères"""
        seen_matricules = set()
        seen_emails = set()
        seen_keys = set()
        deduplicated = []
        
        for emp_data in employees_data:
            matricule = emp_data.get('matricule', '').strip()
            email = emp_data.get('email', '').strip().lower()
            emp_key = emp_data.get('employee_key', '').strip()
            
            # Clé unique combinée
            unique_key = f"{matricule}|{email}|{emp_key}"
            
            is_duplicate = False
            
            # Vérifications de doublons
            if matricule and matricule in seen_matricules:
                is_duplicate = True
            elif email and email in seen_emails:
                is_duplicate = True
            elif emp_key and emp_key in seen_keys:
                is_duplicate = True
            
            if not is_duplicate:
                deduplicated.append(emp_data)
                if matricule:
                    seen_matricules.add(matricule)
                if email:
                    seen_emails.add(email)
                if emp_key:
                    seen_keys.add(emp_key)
            else:
                self.stats['duplicates_handled'] += 1
                logger.debug(f"Doublon éliminé: {matricule}")
        
        return deduplicated
    
    def _process_employee_batch(self, batch):
        """Traite un lot d'employés avec gestion d'erreurs par employé"""
        results = {
            'processed': 0,
            'created': 0,
            'updated': 0,
            'errors': 0,
            'error_details': []
        }
        
        for emp_data in batch:
            matricule = emp_data.get('matricule', 'INCONNU')
            
            try:
                with transaction.atomic():
                    # Traitement sécurisé de l'employé
                    created, updated = self._process_single_employee_safe(emp_data)
                    
                    results['processed'] += 1
                    if created:
                        results['created'] += 1
                    elif updated:
                        results['updated'] += 1
                    
                    self.processed_employees.add(matricule)
                    
            except Exception as e:
                results['errors'] += 1
                error_detail = f"Erreur employé {matricule}: {str(e)}"
                results['error_details'].append(error_detail)
                logger.error(f"ERROR {error_detail}")
        
        return results
    
    def _process_single_employee_safe(self, emp_data):
        """Traite un employé unique de manière sécurisée"""
        matricule = emp_data.get('matricule')
        
        # 1. Créer/mettre à jour User Django
        user, user_created = self._create_or_update_user_safe(emp_data)
        
        # 2. Créer/mettre à jour ProfilUtilisateur
        profil, profil_created = self._create_or_update_profil_safe(emp_data, user)
        
        # 3. Créer/mettre à jour données étendues
        self._create_or_update_extended_data_safe(emp_data, profil)
        
        # 4. Mettre à jour statut de synchronisation
        profil.kelio_last_sync = timezone.now()
        profil.kelio_sync_status = 'REUSSI'
        profil.save(update_fields=['kelio_last_sync', 'kelio_sync_status'])
        
        return profil_created, not profil_created and user
    
    def _create_or_update_user_safe(self, emp_data):
        """Création/mise à jour sécurisée de User Django"""
        matricule = emp_data.get('matricule', '')
        prenom = emp_data.get('prenom', '')
        nom = emp_data.get('nom', '')
        email = emp_data.get('email', '')
        
        # Username unique basé sur matricule
        username = matricule or f"emp_{timezone.now().timestamp()}"
        
        try:
            # Chercher utilisateur existant
            user = None
            if email:
                user = User.objects.filter(email=email).first()
            
            if not user and matricule:
                user = User.objects.filter(username=username).first()
            
            if user:
                # Mise à jour
                user.first_name = prenom
                user.last_name = nom
                if email and not user.email:
                    user.email = email
                user.save()
                return user, False
            else:
                # Création
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=prenom,
                    last_name=nom,
                    password=User.objects.make_random_password()
                )
                return user, True
                
        except Exception as e:
            logger.error(f"Erreur User pour {matricule}: {e}")
            raise
    
    def _create_or_update_profil_safe(self, emp_data, user):
        """Création/mise à jour sécurisée de ProfilUtilisateur"""
        matricule = emp_data.get('matricule')
        kelio_employee_key = emp_data.get('employee_key')
        
        try:
            # Chercher profil existant
            profil = None
            if matricule:
                profil = ProfilUtilisateur.objects.filter(matricule=matricule).first()
            
            # Gestion sécurisée de kelio_employee_key
            if kelio_employee_key and not profil:
                existing_with_key = ProfilUtilisateur.objects.filter(
                    kelio_employee_key=kelio_employee_key
                ).first()
                if existing_with_key:
                    profil = existing_with_key
                    logger.warning(f"Profil trouvé par kelio_employee_key: {kelio_employee_key}")
            
            if profil:
                # Mise à jour
                profil.user = user
                profil.actif = not emp_data.get('archived', False)
                profil.kelio_badge_code = emp_data.get('badge_code', '')
                profil.save()
                return profil, False
            else:
                # Création avec gestion des contraintes UNIQUE
                profil_data = {
                    'user': user,
                    'matricule': matricule,
                    'type_profil': 'UTILISATEUR',
                    'statut_employe': 'ACTIF',
                    'actif': not emp_data.get('archived', False),
                    'kelio_badge_code': emp_data.get('badge_code', '')
                }
                
                # Ajouter kelio_employee_key seulement si unique
                if kelio_employee_key:
                    existing_key = ProfilUtilisateur.objects.filter(
                        kelio_employee_key=kelio_employee_key
                    ).exists()
                    
                    if not existing_key:
                        profil_data['kelio_employee_key'] = kelio_employee_key
                
                profil = ProfilUtilisateur.objects.create(**profil_data)
                return profil, True
                
        except Exception as e:
            logger.error(f"Erreur ProfilUtilisateur pour {matricule}: {e}")
            raise
    
    def _create_or_update_extended_data_safe(self, emp_data, profil):
        """Création/mise à jour sécurisée des données étendues"""
        try:
            extended_data, created = ProfilUtilisateurExtended.objects.get_or_create(
                profil=profil,
                defaults={
                    'telephone': emp_data.get('telephone', ''),
                    'date_embauche': None,  # À définir selon les données disponibles
                    'type_contrat': '',
                    'temps_travail': 1.0,
                    'disponible_interim': not emp_data.get('archived', False),
                    'rayon_deplacement_km': 50
                }
            )
            
            if not created:
                extended_data.telephone = emp_data.get('telephone', '')
                extended_data.disponible_interim = not emp_data.get('archived', False)
                extended_data.save()
            
            return extended_data
            
        except Exception as e:
            logger.error(f"Erreur données étendues pour {profil.matricule}: {e}")
            # Ne pas faire échouer le processus pour les données étendues
            pass


# ================================================================
# FONCTIONS UTILITAIRES V4.2
# ================================================================

def synchroniser_tous_employes_kelio_v42():
    """Fonction principale de synchronisation V4.2"""
    try:
        service = KelioSyncServiceV42()
        return service.synchroniser_tous_employes_optimise()
    except Exception as e:
        logger.error(f"ERROR Synchronisation V4.2: {e}")
        return {
            'statut_global': 'erreur_critique',
            'erreur': str(e),
            'timestamp': timezone.now().isoformat()
        }

def get_kelio_sync_service_v42(configuration=None):
    """Factory pour le service V4.2"""
    return KelioSyncServiceV42(configuration)

# ================================================================
# MANAGER GLOBAL STANDALONE POUR V4.2
# ================================================================

class KelioGlobalSyncManagerV42:
    """Manager global standalone utilisant le service V4.2 amélioré"""
    
    def __init__(self, sync_mode='complete', force_sync=True, notify_users=False, 
                 include_archived=False, requesting_user=None):
        self.sync_mode = sync_mode
        self.force_sync = force_sync
        self.notify_users = notify_users
        self.include_archived = include_archived
        self.requesting_user = requesting_user
        
        # Statistiques globales
        self.stats = {
            'total_employees_processed': 0,
            'total_created': 0,
            'total_updated': 0,
            'total_errors': 0,
            'duration_seconds': 0,
            'employees_per_second': 0,
            'services_results': {},
            'sync_mode': sync_mode,
            'started_at': timezone.now().isoformat(),
            'completed_at': None,
            'service_utilise': 'KelioSyncServiceV42',
            'fallback_utilise': False
        }
        
        logger.info(f"[KELIO-GLOBAL-MANAGER-V42] Initialisé pour synchronisation {sync_mode}")
    
    def execute_global_sync(self):
        """Execute la synchronisation globale avec le service V4.2"""
        start_time = timezone.now()
        
        try:
            logger.info(f"[KELIO-GLOBAL-MANAGER-V42] Début synchronisation globale mode {self.sync_mode}")
            
            # ETAPE 1: Exécution de la synchronisation V4.2
            if self.sync_mode == 'complete':
                result = self._execute_complete_sync_v42()
            elif self.sync_mode == 'employees_only':
                result = self._execute_employees_only_sync_v42()
            else:
                result = self._execute_complete_sync_v42()  # Fallback
            
            # ETAPE 2: Calcul durée et résultats finaux
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            # Calculer la vitesse de traitement
            if self.stats['total_employees_processed'] > 0 and duration > 0:
                self.stats['employees_per_second'] = self.stats['total_employees_processed'] / duration
            
            logger.info(f"[KELIO-GLOBAL-MANAGER-V42] Synchronisation terminée en {duration:.2f}s")
            
            return result
            
        except Exception as e:
            duration = (timezone.now() - start_time).total_seconds()
            self.stats['duration_seconds'] = duration
            self.stats['completed_at'] = timezone.now().isoformat()
            
            logger.error(f"[KELIO-GLOBAL-MANAGER-V42] Erreur synchronisation: {e}")
            return self._error_response(f"Erreur: {str(e)}", e)
    
    def _execute_complete_sync_v42(self):
        """Execute une synchronisation complète avec le service V4.2"""
        logger.info("[KELIO-GLOBAL-MANAGER-V42] Début synchronisation complète")
        
        try:
            # Utiliser directement le service V4.2
            sync_result = self._sync_employees_v42()
            
            # Mettre à jour les statistiques
            self.stats['total_employees_processed'] = sync_result.get('processed', 0)
            self.stats['total_created'] = sync_result.get('created', 0)
            self.stats['total_updated'] = sync_result.get('updated', 0)
            self.stats['total_errors'] = sync_result.get('error_count', 0)
            
            # Enregistrer les résultats du service
            self.stats['services_results']['employees'] = {
                'status': 'SUCCESS' if sync_result['success'] else 'FAILED',
                'processed': sync_result.get('processed', 0),
                'success_count': sync_result.get('success_count', 0),
                'error_count': sync_result.get('error_count', 0),
                'service_utilise': sync_result.get('service_utilise', 'KelioSyncServiceV42'),
                'doublons_geres': sync_result.get('doublons_geres', 0)
            }
            
            if sync_result['success']:
                return self._success_response("Synchronisation complète V4.2 terminée avec succès")
            else:
                return self._error_response(f"Échec synchronisation V4.2: {sync_result.get('message', 'Erreur inconnue')}")
                
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER-V42] Erreur synchronisation complète: {e}")
            return self._error_response(f"Erreur synchronisation complète V4.2: {str(e)}")
    
    def _execute_employees_only_sync_v42(self):
        """Execute synchronisation employés seulement avec V4.2"""
        logger.info("[KELIO-GLOBAL-MANAGER-V42] Début synchronisation employés seulement")
        return self._execute_complete_sync_v42()  # Même logique pour V4.2
    
    def _sync_employees_v42(self):
        """Synchronise les employés avec le service V4.2"""
        try:
            logger.info("[KELIO-GLOBAL-MANAGER-V42] Début synchronisation employés V4.2")
            
            # Utiliser le nouveau service V4.2
            result = synchroniser_tous_employes_kelio_v42()
            
            if result.get('statut_global') in ['reussi', 'partiel']:
                donnees = result.get('donnees_globales', {})
                
                return {
                    'success': True,
                    'message': f"Employés synchronisés avec succès (Service V4.2)",
                    'processed': donnees.get('employes_traites', 0),
                    'success_count': donnees.get('employes_traites', 0),
                    'created': donnees.get('nouveaux_employes', 0),
                    'updated': donnees.get('employes_mis_a_jour', 0),
                    'error_count': donnees.get('erreurs', 0),
                    'service_utilise': 'KelioSyncServiceV42 optimisé',
                    'fallback_utilise': False,
                    'doublons_geres': donnees.get('doublons_geres', 0)
                }
            else:
                error_msg = result.get('erreur', 'Erreur inconnue')
                
                return {
                    'success': False,
                    'message': f'Échec synchronisation employés V4.2: {error_msg}',
                    'processed': result.get('donnees_globales', {}).get('employes_traites', 0),
                    'error_count': result.get('donnees_globales', {}).get('erreurs', 1),
                    'service_utilise': 'KelioSyncServiceV42',
                    'fallback_utilise': False
                }
                
        except Exception as e:
            logger.error(f"[KELIO-GLOBAL-MANAGER-V42] Erreur sync employés: {e}")
            return {
                'success': False,
                'message': f'Erreur synchronisation employés V4.2: {str(e)}',
                'processed': 0,
                'error_count': 1,
                'service_utilise': 'Erreur KelioSyncServiceV42',
                'fallback_utilise': False
            }
    
    def _success_response(self, message):
        """Génère une réponse de succès"""
        return {
            'success': True,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'total_employees_processed': self.stats['total_employees_processed'],
                'service_utilise': self.stats.get('service_utilise'),
                'fallback_utilise': self.stats.get('fallback_utilise', False)
            },
            'stats': self.stats,
            'timestamp': timezone.now().isoformat()
        }
    
    def _error_response(self, message, exception=None):
        """Génère une réponse d'erreur"""
        return {
            'success': False,
            'message': message,
            'data': {
                'sync_mode': self.sync_mode,
                'service_utilise': self.stats.get('service_utilise'),
                'fallback_utilise': self.stats.get('fallback_utilise', False)
            },
            'stats': self.stats,
            'error_details': str(exception) if exception else None,
            'timestamp': timezone.now().isoformat()
        }
