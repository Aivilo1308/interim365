#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test immédiat du service Kelio - À exécuter depuis le shell Django
"""

import os
import sys

# Force l'encodage UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LC_ALL'] = 'C.UTF-8'
os.environ['LANG'] = 'C.UTF-8'

def test_encoding_environment():
    """Test l'environnement d'encodage"""
    print("=== TEST ENVIRONNEMENT ENCODAGE ===")
    print(f"sys.getdefaultencoding(): {sys.getdefaultencoding()}")
    print(f"sys.stdout.encoding: {getattr(sys.stdout, 'encoding', 'N/A')}")
    print(f"PYTHONIOENCODING: {os.environ.get('PYTHONIOENCODING', 'NON_DEFINI')}")
    
    # Test caractères problématiques
    test_string = "Test caractères: é è à ç"
    try:
        ascii_version = test_string.encode('ascii', 'ignore').decode('ascii')
        print(f"Original: {test_string}")
        print(f"ASCII safe: {ascii_version}")
        print("✅ Conversion ASCII réussie")
    except Exception as e:
        print(f"❌ Erreur conversion ASCII: {e}")

def test_kelio_config():
    """Test la configuration Kelio"""
    print("\n=== TEST CONFIGURATION KELIO ===")
    
    try:
        # Import Django models
        from mainapp.models import ConfigurationApiKelio
        
        configs = ConfigurationApiKelio.objects.filter(actif=True)
        print(f"Configurations actives trouvées: {configs.count()}")
        
        if configs.exists():
            config = configs.first()
            print(f"Configuration: {config.nom}")
            
            # Nettoyer l'URL pour éviter les caractères problématiques
            url_safe = config.url_base.encode('ascii', 'ignore').decode('ascii')
            print(f"URL (ASCII safe): {url_safe}")
            print(f"Username: {config.username}")
            print("✅ Configuration accessible")
            
            return config
        else:
            print("❌ Aucune configuration active")
            return None
            
    except Exception as e:
        print(f"❌ Erreur accès configuration: {e}")
        return None

def test_simple_http():
    """Test HTTP simple sans SOAP"""
    print("\n=== TEST HTTP SIMPLE ===")
    
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        
        config = test_kelio_config()
        if not config:
            print("❌ Impossible de tester sans configuration")
            return
        
        session = requests.Session()
        session.auth = HTTPBasicAuth(config.username, config.password)
        session.headers.update({
            'User-Agent': 'Test-Kelio-Script',
            'Accept': 'text/html,application/xml,text/xml',
        })
        
        # URL nettoyée
        clean_url = config.url_base.encode('ascii', 'ignore').decode('ascii')
        print(f"Test connexion vers: {clean_url}")
        
        response = session.get(clean_url, timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")
        
        if response.status_code == 200:
            print("✅ Connexion HTTP réussie")
        else:
            print(f"⚠️ Connexion HTTP avec code: {response.status_code}")
            
    except Exception as e:
        error_safe = str(e).encode('ascii', 'ignore').decode('ascii')
        print(f"❌ Erreur test HTTP: {error_safe}")

def test_kelio_simple_service():
    """Test le service Kelio simplifié"""
    print("\n=== TEST SERVICE KELIO SIMPLE ===")
    
    try:
        # Importer notre service simplifié
        from mainapp.services.kelio_sync_simple import sync_kelio_simple
        
        print("🔄 Lancement synchronisation simplifiée...")
        result = sync_kelio_simple()
        
        print(f"Status: {result.get('status', 'INCONNU')}")
        print(f"Employés traités: {result.get('employes_traites', 0)}")
        print(f"Erreurs: {result.get('erreurs', 0)}")
        
        if 'message' in result:
            print(f"Message: {result['message']}")
            
        if result.get('status') == 'reussi':
            print("✅ Service simplifié fonctionne")
        else:
            print("⚠️ Service simplifié avec problèmes")
            
    except ImportError:
        print("❌ Service kelio_sync_simple non trouvé")
    except Exception as e:
        error_safe = str(e).encode('ascii', 'ignore').decode('ascii')
        print(f"❌ Erreur service simple: {error_safe}")

def main():
    """Fonction principale de test"""
    print("🚀 DÉMARRAGE TESTS KELIO")
    print("=" * 50)
    
    test_encoding_environment()
    test_simple_http()
    test_kelio_simple_service()
    
    print("\n" + "=" * 50)
    print("📋 RÉSUMÉ:")
    print("1. Si les tests HTTP passent mais pas SOAP → Problème Zeep/encodage")
    print("2. Si tout échoue → Problème configuration/réseau")
    print("3. Utilisez le service simple en attendant la correction SOAP")
    print("=" * 50)

if __name__ == "__main__":
    main()