#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
from requests.auth import HTTPBasicAuth
import warnings
from django.core.cache import cache
from mainapp.models import ConfigurationApiKelio

# Logger securise
try:
    from django.conf import settings
    logger = settings.get_safe_kelio_logger()
except:
    import logging
    logger = logging.getLogger('kelio.sync')


# Force output flushing
def print_flush(message):
    print(message)
    sys.stdout.flush()

# Suppress SSL warnings
warnings.filterwarnings('ignore')

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

def main():
    print_flush("🚀 DÉBUT TEST KELIO")
    print_flush("=" * 50)
    
    # Configuration
    url = KELIO_BASE_URL
    auth = HTTPBasicAuth(KELIO_DEFAULT_AUTH['username'], KELIO_DEFAULT_AUTH['password'])
    
    print_flush(f"URL: {url}")
    print_flush(f"Auth: {auth.username} / {'*' * len('12345')}")
    print_flush("")
    
    # Test 1: Connectivité de base
    print_flush("TEST 1: Connectivité de base")
    print_flush("-" * 30)
    
    try:
        print_flush("Tentative de connexion...")
        response = requests.get(url, auth=auth, verify=False, timeout=15)
        print_flush(f"✅ Succès! Status: {response.status_code}")
        print_flush(f"Headers reçus: {len(response.headers)} éléments")
        
        if 'Server' in response.headers:
            print_flush(f"Serveur: {response.headers['Server']}")
        
    except requests.exceptions.Timeout:
        print_flush("❌ TIMEOUT - Le serveur ne répond pas")
        return
    except requests.exceptions.ConnectionError:
        print_flush("❌ ERREUR DE CONNEXION - Impossible de joindre le serveur")
        return
    except Exception as e:
        print_flush(f"❌ ERREUR: {e}")
        return
    
    print_flush("")
    
    # Test 2: Test des chemins de services
    print_flush("TEST 2: Chemins de services")
    print_flush("-" * 30)
    
    paths_to_test = ['services', 'webservices', 'soap', 'wsdl']
    
    for path in paths_to_test:
        try:
            test_url = f"{url}/{path}"
            print_flush(f"Test: {test_url}")
            
            response = requests.get(test_url, auth=auth, verify=False, timeout=10)
            print_flush(f"  ✅ {path}: HTTP {response.status_code}")
            
        except Exception as e:
            print_flush(f"  ❌ {path}: {str(e)[:50]}")
    
    print_flush("")
    
    # Test 3: Services SOAP spécifiques
    print_flush("TEST 3: Services SOAP")
    print_flush("-" * 30)
    
    services_to_test = [
        'EmployeeService',
        'EmployeeListService',
        'AbsenceRequestService'
    ]
    
    session = requests.Session()
    session.auth = auth
    session.verify = False
    
    available_services = []
    
    for service in services_to_test:
        try:
            wsdl_url = f"{url}/services/{service}?wsdl"
            print_flush(f"Test: {service}")
            
            response = session.head(wsdl_url, timeout=10)
            
            if response.status_code == 200:
                available_services.append(service)
                print_flush(f"  ✅ {service}: DISPONIBLE")
            elif response.status_code == 404:
                print_flush(f"  ❌ {service}: NON TROUVÉ (404)")
            else:
                print_flush(f"  ⚠️  {service}: HTTP {response.status_code}")
                
        except Exception as e:
            print_flush(f"  ❌ {service}: {str(e)[:50]}")
    
    print_flush("")
    print_flush(f"📊 RÉSULTAT: {len(available_services)} services trouvés")
    
    for service in available_services:
        print_flush(f"   • {service}")
    
    print_flush("")
    
    # Test 4: Test ZEEP (optionnel)
    print_flush("TEST 4: Module ZEEP")
    print_flush("-" * 30)
    
    try:
        import zeep
        print_flush("✅ Module zeep disponible")
        
        if available_services:
            first_service = available_services[0]
            print_flush(f"Test parsing WSDL: {first_service}")
            
            try:
                from zeep import Client, Settings, Transport
                
                wsdl_url = f"{url}/services/{first_service}?wsdl"
                settings = Settings(strict=False, xml_huge_tree=True)
                transport = Transport(session=session, timeout=30)
                
                client = Client(wsdl_url, settings=settings, transport=transport)
                print_flush(f"✅ WSDL parsing réussi pour {first_service}")
                
                # Lister les méthodes
                methods = [name for name in dir(client.service) if not name.startswith('_')]
                print_flush(f"Méthodes trouvées: {len(methods)}")
                for method in methods[:3]:  # Afficher seulement les 3 premières
                    print_flush(f"   • {method}")
                if len(methods) > 3:
                    print_flush(f"   ... et {len(methods) - 3} autres")
                
            except Exception as e:
                print_flush(f"❌ Erreur parsing WSDL: {e}")
        
    except ImportError:
        print_flush("❌ Module zeep non installé")
        print_flush("   Pour installer: pip install zeep")
    
    print_flush("")
    print_flush("🎯 TEST TERMINÉ")
    print_flush("=" * 50)

if __name__ == "__main__":
    main()