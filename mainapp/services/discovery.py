import requests
from urllib.parse import urljoin
import logging

logger = logging.getLogger(__name__)

def discover_available_kelio_services(base_url, username, password):
    """
    Découvre automatiquement les services WSDL disponibles sur le serveur Kelio
    """
    # Services potentiels à tester (liste classique des services Kelio)
    potential_services = [
        'EmployeeService',
        'EmployeeListService',
        'AbsenceRequestService',
        'EmployeePictureService',
        'EmployeeTrainingHistoryService',
        'SkillAssignmentService',
        'JobAssignmentService',
        'EmployeeJobAssignmentService',
        'LaborContractAssignmentService',
        'CoefficientAssignmentService',
        'ProfessionalExperienceAssignmentService',
        'InitialFormationAssignmentService',
        'EmployeeProfessionalDataService',  # Service de la V4.1 qui n'existe peut-être pas
    ]
    
    available_services = {}
    session = requests.Session()
    session.auth = requests.auth.HTTPBasicAuth(username, password)
    session.verify = False  # Pour les certificats auto-signés
    
    logger.info(f">>> Découverte des services Kelio disponibles sur {base_url}")
    
    for service_name in potential_services:
        wsdl_url = urljoin(base_url, f"services/{service_name}?wsdl")
        
        try:
            response = session.head(wsdl_url, timeout=10)
            
            if response.status_code == 200:
                available_services[service_name] = {
                    'url': wsdl_url,
                    'status': 'AVAILABLE',
                    'description': f"Service {service_name} disponible"
                }
                logger.info(f"✅ Service disponible: {service_name}")
            elif response.status_code == 404:
                logger.debug(f"❌ Service non disponible: {service_name} (404)")
            else:
                logger.debug(f"⚠️ Service {service_name}: status {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.debug(f"❌ Erreur test {service_name}: {e}")
    
    logger.info(f">>> {len(available_services)} service(s) Kelio découvert(s)")
    return available_services

def test_kelio_service_method(base_url, username, password, service_name, method_name='exportEmployees'):
    """
    Teste si une méthode spécifique existe sur un service
    """
    try:
        from zeep import Client, Settings, Transport
        from requests import Session
        
        session = Session()
        session.auth = requests.auth.HTTPBasicAuth(username, password)
        session.verify = False
        
        wsdl_url = urljoin(base_url, f"services/{service_name}?wsdl")
        
        settings_soap = Settings(strict=False, xml_huge_tree=True)
        transport = Transport(session=session, timeout=30)
        
        client = Client(wsdl_url, settings=settings_soap, transport=transport)
        
        # Vérifier si la méthode existe
        if hasattr(client.service, method_name):
            logger.info(f"✅ Méthode {method_name} disponible sur {service_name}")
            return True
        else:
            logger.info(f"❌ Méthode {method_name} non disponible sur {service_name}")
            available_methods = [name for name in dir(client.service) if not name.startswith('_')]
            logger.info(f"   Méthodes disponibles: {available_methods}")
            return False
            
    except Exception as e:
        logger.error(f"Erreur test méthode {method_name} sur {service_name}: {e}")
        return False

def create_dynamic_kelio_config(base_url, username, password):
    """
    Crée une configuration dynamique basée sur les services réellement disponibles
    """
    available_services = discover_available_kelio_services(base_url, username, password)
    
    # Configuration dynamique basée sur les services trouvés
    dynamic_config = {}
    
    # Mapping des services vers leur configuration
    service_mappings = {
        'EmployeeService': {
            'priority': 1,
            'timeout': 60,
            'method_all': 'exportEmployees',
            'description': 'Service de base pour les employés',
            'maps_to_models': ['ProfilUtilisateur']
        },
        'EmployeeListService': {
            'priority': 1,
            'timeout': 45,
            'method': 'exportEmployeesList',
            'description': 'Liste des employés',
            'maps_to_models': ['ProfilUtilisateur']
        },
        'AbsenceRequestService': {
            'priority': 2,
            'timeout': 30,
            'method': 'exportAbsenceRequestsFromEmployeeList',
            'description': 'Demandes d\'absences',
            'maps_to_models': ['AbsenceUtilisateur']
        },
        'EmployeePictureService': {
            'priority': 4,
            'timeout': 45,
            'method': 'exportEmployeePicturesList',
            'description': 'Photos des employés',
            'data_source': 'KELIO_ONLY'
        },
    }
    
    for service_name, service_info in available_services.items():
        if service_name in service_mappings:
            config = service_mappings[service_name].copy()
            config.update({
                'service_name': service_name,
                'wsdl_path': f'services/{service_name}?wsdl',
                'status': 'AVAILABLE',
                'data_source': config.get('data_source', 'KELIO'),
                'cache_duration': 3600,
                'required_for_creation': config.get('priority', 1) == 1
            })
            
            dynamic_config[service_name.lower().replace('service', '')] = config
    
    return dynamic_config

# Fonction pour mettre à jour le service Kelio avec la configuration découverte
def update_kelio_service_with_discovery(kelio_service):
    """
    Met à jour un service Kelio existant avec la découverte automatique
    """
    if not hasattr(kelio_service, 'config'):
        return False
    
    try:
        base_url = kelio_service.config.url_base
        username = kelio_service.config.username or 'webservices'
        password = kelio_service.config.get_password() or '12345'
        
        # Découvrir les services disponibles
        dynamic_config = create_dynamic_kelio_config(base_url, username, password)
        
        if dynamic_config:
            # Remplacer la configuration statique par la configuration dynamique
            kelio_service.services_config = dynamic_config
            logger.info(f"Configuration Kelio mise à jour avec {len(dynamic_config)} services découverts")
            return True
        else:
            logger.warning("Aucun service Kelio découvert - conservation de la configuration par défaut")
            return False
            
    except Exception as e:
        logger.error(f"Erreur mise à jour configuration Kelio: {e}")
        return False

# Exemple d'utilisation
def test_kelio_discovery():
    """
    Fonction de test pour la découverte de services
    """
    base_url = "https://keliodemo-safesecur.kelio.io/open/"
    username = "webservices"
    password = "12345"
    
    print("=== Test de découverte des services Kelio ===")
    
    # Découvrir les services
    services = discover_available_kelio_services(base_url, username, password)
    
    print(f"\nServices découverts : {len(services)}")
    for service_name, info in services.items():
        print(f"  ✅ {service_name}: {info['description']}")
    
    # Tester des méthodes spécifiques
    if 'EmployeeListService' in services:
        print(f"\n=== Test des méthodes sur EmployeeListService ===")
        test_kelio_service_method(base_url, username, password, 'EmployeeListService', 'exportEmployeesList')
    
    if 'EmployeeService' in services:
        print(f"\n=== Test des méthodes sur EmployeeService ===")
        test_kelio_service_method(base_url, username, password, 'EmployeeService', 'exportEmployees')
    
    # Créer la configuration dynamique
    print(f"\n=== Configuration dynamique ===")
    config = create_dynamic_kelio_config(base_url, username, password)
    
    for key, value in config.items():
        print(f"  {key}: {value['description']}")
    
    return config

if __name__ == "__main__":
    test_kelio_discovery()